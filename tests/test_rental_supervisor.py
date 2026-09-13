from dataclasses import replace
from datetime import datetime, timezone
import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from gridgpu.recovery_journal import RecoveryError, RecoveryIntent, RecoveryJournal, RecoveryObservation
from gridgpu.rental_supervisor import OriginalLimitBroker, PosixBoundedRunner, SupervisionError, supervise_attended_controller, arm_parent_death
from gridgpu.supervised_recovery import RecoveryApproval, intent_digest


@unittest.skipUnless(os.name == "posix", "POSIX process containment")
class RentalSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.intent = RecoveryIntent("trial", "host", "GPU-abc", "a" * 64, 175, 125, self.now.isoformat())
        self.journal = RecoveryJournal(self.directory / "intent.jsonl")

    def command(self, source):
        return (sys.executable, "-c", source)

    def test_harmless_child_exits_and_reaped(self):
        command = self.command("print('fixture')")
        runner = PosixBoundedRunner((command,), maximum_seconds=2)
        result = runner(command)
        self.assertEqual(result.stdout, "fixture\n")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(runner.group_gone)
        with self.assertRaises(ChildProcessError):
            os.waitpid(runner.last_group, os.WNOHANG)

    def test_real_hard_deadline_kills_and_reaps_child(self):
        command = self.command("import time; time.sleep(30)")
        runner = PosixBoundedRunner((command,), maximum_seconds=0.15)
        began = time.monotonic()
        with self.assertRaises(SupervisionError):
            runner(command)
        self.assertLess(time.monotonic() - began, 3)
        self.assertTrue(runner.group_gone)
        with self.assertRaises(ProcessLookupError):
            os.killpg(runner.last_group, 0)

    def test_descendant_inherited_group_is_killed(self):
        pidfile = self.directory / "child.pid"
        command = self.command("import subprocess,sys,time,pathlib; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(30)")
        runner = PosixBoundedRunner((command,), maximum_seconds=0.5)
        with self.assertRaises(SupervisionError):
            runner(command)
        self.assertTrue(pidfile.exists())
        self.assertTrue(runner.group_gone)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_output_overflow_is_stopped_while_running(self):
        command = self.command("import os,time; os.write(1,b'x'*200000); time.sleep(30)")
        runner = PosixBoundedRunner((command,), maximum_seconds=2)
        with self.assertRaisesRegex(SupervisionError, "output exceeds"):
            runner(command)
        self.assertTrue(runner.group_gone)

    def test_unauthorized_command_and_environment_rejected(self):
        command = self.command("pass")
        runner = PosixBoundedRunner((command,))
        with self.assertRaises(SupervisionError):
            runner(self.command("print('other')"))
        with self.assertRaises(SupervisionError):
            runner(command, env={"LD_PRELOAD": "untrusted"})
        self.assertIsNone(runner.last_group)

    def test_original_only_broker_with_harmless_executable(self):
        self.journal.create(self.intent)
        executable = self.directory / "fixture-command"
        executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\"\n")
        executable.chmod(0o700)
        broker = OriginalLimitBroker(self.journal, executable, authorize_restore=lambda _: True,
                                     required_owner_uid=os.getuid())
        self.assertEqual(broker.command[-4:], ("-i", "GPU-abc", "-pl", "175.000"))
        broker(self.intent)
        with self.assertRaises(RecoveryError):
            broker(replace(self.intent, original_watts=180))
        executable.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaisesRegex(RecoveryError, "provenance"):
            broker(self.intent)

    def test_controller_loss_reconciles_existing_durable_intent(self):
        source = ("import os,sys,signal; "
            f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r}); "
            "from pathlib import Path; "
            "from gridgpu.recovery_journal import RecoveryJournal,RecoveryIntent; "
            f"RecoveryJournal(Path({str(self.journal.path)!r})).create("
            "RecoveryIntent('trial','host','GPU-abc','a'*64,175,125,'2030-01-01T00:00:00+00:00')); "
            "os.kill(os.getpid(),signal.SIGKILL)")
        readings = iter((125, 175))
        restored = []
        result = supervise_attended_controller(self.command(source), self.journal,
            authorize_launch=lambda _: True, maximum_seconds=2,
            recovery_approval=RecoveryApproval(intent_digest(self.intent), "operator", "nonce", "2030-01-01T01:00:00Z"),
            reconciliation_options=dict(lock_directory=self.directory,
                verify_and_consume=lambda _: True, confirm=lambda phrase: phrase,
                observe=lambda intent: RecoveryObservation("host", "GPU-abc", next(readings), self.now.isoformat(), "fixture"),
                restore=lambda intent: restored.append(intent.original_watts), clock=lambda: self.now,
                monotonic=time.monotonic, source_id="fixture"))
        self.assertTrue(result["controller_failed"])
        self.assertEqual(restored, [175])
        self.assertIsNotNone(self.journal.read().restored_observation)

    def test_existing_journal_blocks_launch_on_restart(self):
        self.journal.create(self.intent)
        with self.assertRaisesRegex(SupervisionError, "pre-existing"):
            supervise_attended_controller(self.command("pass"), self.journal,
                authorize_launch=lambda _: self.fail("must block before launch approval"),
                maximum_seconds=2, recovery_approval=None, reconciliation_options={})

    def test_missing_journal_does_not_authorize_recovery(self):
        with self.assertRaises(RecoveryError):
            supervise_attended_controller(self.command("pass"), self.journal,
                authorize_launch=lambda _: True, maximum_seconds=2, recovery_approval=None,
                reconciliation_options={})

    def test_pipe_setup_failure_still_kills_and_reaps(self):
        command = self.command("import time; time.sleep(30)")
        runner = PosixBoundedRunner((command,), maximum_seconds=1)
        with patch("gridgpu.rental_supervisor.os.set_blocking", side_effect=OSError("setup failed")):
            with self.assertRaises(SupervisionError):
                runner(command)
        self.assertTrue(runner.group_gone)
        with self.assertRaises(ProcessLookupError):
            os.killpg(runner.last_group, 0)

    def test_bounded_confirmation_input_reaches_child(self):
        command = self.command("import sys; print(sys.stdin.read())")
        runner = PosixBoundedRunner((command,), maximum_seconds=2)
        self.assertEqual(runner(command, input_text="confirmed\n").stdout, "confirmed\n\n")
        with self.assertRaises(SupervisionError):
            runner(command, input_text="x" * 4097)

    def test_inherited_command_timeout_keeps_controller_alive(self):
        source = ("import os,sys; "
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
            "from gridgpu.rental_supervisor import PosixBoundedRunner,SupervisionError; "
            "command=(sys.executable,'-c','import time; time.sleep(30)'); "
            "runner=PosixBoundedRunner((command,),maximum_seconds=.1,supervised_process_group=os.getpid());\n"
            "try: runner(command)\n"
            "except SupervisionError: print('controller alive',os.getpgrp()==os.getpid(),runner.group_gone)\n")
        command = self.command(source)
        result = PosixBoundedRunner((command,), maximum_seconds=3)(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("controller alive True False", result.stdout)

    def test_parent_death_arms_exact_kill_signal(self):
        libc = MagicMock()
        libc.prctl.return_value = 0
        with patch("gridgpu.rental_supervisor.sys.platform", "linux"), patch("os.getppid", return_value=42), patch("ctypes.CDLL", return_value=libc):
            arm_parent_death(42)
        libc.prctl.assert_called_once_with(1, signal.SIGKILL, 0, 0, 0)

    def test_parent_death_race_and_syscall_failure_rejected(self):
        for pids, result in (((42, 1), 0), ((42,), -1), ((1,), 0)):
            libc = MagicMock()
            libc.prctl.return_value = result
            with patch("gridgpu.rental_supervisor.sys.platform", "linux"), patch("os.getppid", side_effect=pids), patch("ctypes.CDLL", return_value=libc):
                with self.assertRaises(SupervisionError):
                    arm_parent_death(42)

    def test_parent_death_nonlinux_and_invalid_pid_rejected(self):
        with patch("gridgpu.rental_supervisor.sys.platform", "darwin"):
            with self.assertRaises(SupervisionError):
                arm_parent_death(42)
        with patch("gridgpu.rental_supervisor.sys.platform", "linux"):
            for value in (1, 0, -1, True, "42"):
                with self.assertRaises(SupervisionError):
                    arm_parent_death(value)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death kernel test")
    def test_linux_orphan_is_killed_by_kernel(self):
        from gridgpu.rental_supervisor import _adopt_linux_orphans
        _adopt_linux_orphans()
        marker = self.directory / "armed.pid"
        worker = ("import os,sys,pathlib,time; "
            f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r}); "
            "from gridgpu.rental_supervisor import arm_parent_death; "
            "arm_parent_death(int(sys.argv[1])); "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)")
        parent = ("import os,sys,subprocess,time,pathlib; "
            f"subprocess.Popen([sys.executable,'-c',{worker!r},str(os.getpid())]); "
            f"marker=pathlib.Path({str(marker)!r});\n"
            "while not marker.exists(): time.sleep(.01)\n"
            "os._exit(0)")
        process = subprocess.Popen(self.command(parent), start_new_session=True)
        try:
            process.wait(timeout=5)
            child = int(marker.read_text())
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                pid, status = os.waitpid(child, os.WNOHANG)
                if pid:
                    self.assertTrue(os.WIFSIGNALED(status))
                    self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                    break
                time.sleep(.01)
            else:
                self.fail("kernel did not kill orphaned fixture")
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
