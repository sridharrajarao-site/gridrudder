"""POSIX process-group containment for one attended rental experiment.

No service is installed and no commands run at import. Workload descendants must
inherit their controller's process group; daemonizing/setsid children are forbidden.
"""
import os
from pathlib import Path
import signal
import subprocess
import selectors
import time
import math
import sys

from .qualification import inspect_pinned_executable
from .recovery_journal import RecoveryError, RecoveryJournal
from .supervised_recovery import reconcile_attended_once


class SupervisionError(RecoveryError):
    def __init__(self, message, *, group_gone=False):
        super().__init__(message)
        self.group_gone = group_gone


def arm_parent_death(expected_parent_pid):
    """Linux-only parent-death SIGKILL; call before launching or touching CUDA.

    The post-prctl parent check closes the parent-exited-before-arming race.
    This stops a process on supervisor loss; it cannot restore GPU power limits.
    """
    if not sys.platform.startswith("linux"):
        raise SupervisionError("parent-death containment requires Linux")
    if type(expected_parent_pid) is not int or expected_parent_pid <= 1:
        raise SupervisionError("exact live supervisor PID required")
    if os.getppid() != expected_parent_pid:
        raise SupervisionError("supervisor disappeared before parent-death setup")
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise SupervisionError("cannot arm Linux parent-death signal")
    if os.getppid() != expected_parent_pid:
        raise SupervisionError("supervisor disappeared during parent-death setup")


def _group_exists(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False


def _adopt_linux_orphans():
    # A dedicated Linux supervisor can reap workload grandchildren after the
    # controller dies. This process-local flag does not install an OS service.
    if sys.platform.startswith("linux"):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise SupervisionError("cannot enable Linux orphan reaping")


def _reap_group_children(group):
    while True:
        try:
            pid, _ = os.waitpid(-group, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


class PosixBoundedRunner:
    """Run only exact argv tuples with a hard wait deadline and bounded output.

    All children are placed in a fresh process group. Residual group members are
    killed even after successful leader exit; uncertain group disappearance is an
    error and must not authorize recovery or a new experiment.
    """
    def __init__(self, allowed_commands, *, maximum_seconds=10.0, reap_seconds=2.0,
                 supervised_process_group=None):
        if os.name != "posix":
            raise SupervisionError("POSIX supervision required")
        for value in (maximum_seconds, reap_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
                raise ValueError("positive bounded process timeout required")
        self.allowed = frozenset(tuple(command) for command in allowed_commands)
        if not self.allowed or any(not command or any(not isinstance(v, str) or not v for v in command) for command in self.allowed):
            raise ValueError("exact nonempty command allowlist required")
        self.maximum_seconds, self.reap_seconds = maximum_seconds, reap_seconds
        self.last_group = None
        self.group_gone = False
        if supervised_process_group is not None and (type(supervised_process_group) is not int or
                supervised_process_group != os.getpgrp() or supervised_process_group != os.getpid()):
            raise SupervisionError("inherited command mode requires supervised group leader")
        self.inherited_group = supervised_process_group

    def __call__(self, argv, *, timeout=None, capture_output=True, text=True, check=False, env=None,
                 input_text=None):
        command = tuple(argv)
        if command not in self.allowed or capture_output is not True or text is not True or check is not False:
            raise SupervisionError("command outside approved bounded runner contract")
        duration = self.maximum_seconds if timeout is None else timeout
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= self.maximum_seconds:
            raise SupervisionError("command timeout outside approved bound")
        clean_env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        if env is not None and env != clean_env:
            raise SupervisionError("command environment outside approved clean environment")
        if input_text is not None and (not isinstance(input_text, str) or len(input_text.encode()) > 4096):
            raise SupervisionError("controller input exceeds bounded confirmation channel")
        self.group_gone = False
        failure = None
        _adopt_linux_orphans()
        with selectors.DefaultSelector() as selector:
            process = subprocess.Popen(command, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=clean_env, close_fds=True, start_new_session=self.inherited_group is None)
            self.last_group = process.pid
            output = {"stdout": bytearray(), "stderr": bytearray()}
            try:
                for name in output:
                    stream = getattr(process, name)
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                if input_text is not None:
                    process.stdin.write(input_text.encode())
                    process.stdin.close()
                deadline = time.monotonic() + duration
                while selector.get_map() or process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, duration)
                    if self.inherited_group is None and process.poll() is not None and _group_exists(process.pid):
                        raise SupervisionError("controller left residual descendants")
                    for event, _ in selector.select(min(0.05, remaining)):
                        chunk = os.read(event.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(event.fileobj)
                            continue
                        if len(output[event.data]) + len(chunk) > 65536:
                            raise SupervisionError("command output exceeds evidence bound")
                        output[event.data].extend(chunk)
            except BaseException as exc:
                failure = exc
            finally:
                if (process.poll() is None if self.inherited_group is not None else _group_exists(process.pid)):
                    try:
                        if self.inherited_group is None:
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=self.reap_seconds)
                except subprocess.TimeoutExpired:
                    raise SupervisionError("controller could not be reaped; group state uncertain")
                deadline = time.monotonic() + self.reap_seconds
                while self.inherited_group is None and _group_exists(process.pid) and time.monotonic() < deadline:
                    _reap_group_children(process.pid)
                    time.sleep(0.01)
                self.group_gone = self.inherited_group is None and not _group_exists(process.pid)
                process.stdout.close()
                process.stderr.close()
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
            if self.inherited_group is None and not self.group_gone:
                raise SupervisionError("descendant group did not disappear; require external drain")
            if failure is not None:
                raise SupervisionError(f"command failed supervision: {failure}", group_gone=self.group_gone) from failure
            return subprocess.CompletedProcess(command, process.returncode,
                output["stdout"].decode("utf-8", errors="replace"), output["stderr"].decode("utf-8", errors="replace"))


class OriginalLimitBroker:
    """One pinned local original-limit command, gated by fresh exact-intent approval."""
    def __init__(self, journal: RecoveryJournal, executable: Path, *, authorize_restore,
                 required_owner_uid=0, timeout_seconds=10.0):
        self.journal = journal
        self.provenance = inspect_pinned_executable(executable, required_owner_uid)
        self.owner, self.authorize = required_owner_uid, authorize_restore
        state = journal.read()
        self.intent = state.intent
        self.command = (self.provenance.resolved_path, "-i", self.intent.gpu_uuid,
                        "-pl", f"{self.intent.original_watts:.3f}")
        if float(self.command[-1]) != self.intent.original_watts:
            raise RecoveryError("original limit cannot be exactly represented")
        self.runner = PosixBoundedRunner((self.command,), maximum_seconds=timeout_seconds)

    def __call__(self, intent):
        state = self.journal.read()
        if intent != self.intent or state.intent != intent or state.restored_observation is not None:
            raise RecoveryError("restoration command does not bind an unfinished intent")
        if self.authorize(intent) is not True:
            raise RecoveryError("restoration broker authorization denied")
        if inspect_pinned_executable(Path(self.provenance.resolved_path), self.owner) != self.provenance:
            raise RecoveryError("restoration executable provenance changed")
        result = self.runner(self.command)
        if inspect_pinned_executable(Path(self.provenance.resolved_path), self.owner) != self.provenance:
            raise RecoveryError("restoration executable changed during command")
        if result.returncode:
            raise RecoveryError("restoration command failed; hardware state uncertain")


def supervise_attended_controller(command, journal: RecoveryJournal, *, authorize_launch,
        maximum_seconds, recovery_approval, reconciliation_options, controller_input=None):
    """Run controller and reconcile its open journal only after its group is gone.

    recovery_approval and reconciliation_options feed the attended recovery helper;
    operator confirmation and durable nonce consumption remain mandatory there.
    """
    if journal.path.exists() or journal.path.is_symlink():
        raise SupervisionError("pre-existing journal requires separate attended reconciliation before launch")
    if authorize_launch(tuple(command)) is not True:
        raise SupervisionError("controller launch is not authorized")
    runner = PosixBoundedRunner((tuple(command),), maximum_seconds=maximum_seconds)
    failed = False
    detail = None
    try:
        result = runner(command, input_text=controller_input)
        failed = result.returncode != 0
        if failed:
            detail = f"controller exited with code {result.returncode}"
    except SupervisionError as exc:
        if not runner.group_gone:
            raise
        failed = True
        detail = str(exc)
    state = journal.read()  # Missing/corrupt inventory never establishes safe state.
    if state.restored_observation is None:
        options = dict(reconciliation_options)
        options["process_gone"] = lambda: runner.group_gone and not _group_exists(runner.last_group)
        result = reconcile_attended_once(journal, recovery_approval, **options)
        return {"controller_failed": failed, "failure_detail": detail, "recovery": result}
    return {"controller_failed": failed, "failure_detail": detail, "recovery": "closed_historical_record"}
