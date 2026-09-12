import subprocess
import tempfile
import unittest
from pathlib import Path

from gridgpu.audit import AuditLog
from gridgpu.hardware_lab import (
    DcmiPowerMeter,
    GpuPowerState,
    HardwareTrialConfig,
    HardwareTrialError,
    NvidiaLabPowerControl,
    run_hardware_trial,
)


UUID = "GPU-test-uuid"


class FakeControl:
    def __init__(self, *, ineffective=False, fail_restore=False, mutate_persistence_then_raise=False,
                 fail_restore_observe=False):
        self.limit = 175.0
        self.persistence = False
        self.ineffective = ineffective
        self.fail_restore = fail_restore
        self.mutate_persistence_then_raise = mutate_persistence_then_raise
        self.fail_restore_observe = fail_restore_observe
        self.calls = []

    def observe(self, expected_uuid):
        self.calls.append(("observe", expected_uuid))
        if self.fail_restore_observe and any(call[0] == "limit" for call in self.calls):
            raise RuntimeError("observation unavailable")
        draw = 150.0 if self.limit < 175.0 else 170.0
        return GpuPowerState(UUID, draw, self.limit, 125.0, 175.0, self.persistence)

    def set_persistence(self, gpu_uuid, enabled):
        self.calls.append(("persistence", gpu_uuid, enabled))
        self.persistence = enabled
        if enabled and self.mutate_persistence_then_raise:
            raise RuntimeError("timeout after mutation")

    def set_power_limit(self, gpu_uuid, watts):
        self.calls.append(("limit", gpu_uuid, watts))
        if watts == 175.0 and self.fail_restore:
            raise RuntimeError("restore unavailable")
        if not self.ineffective or watts == 175.0:
            self.limit = watts


class FakeMeter:
    def __init__(self):
        self.values = iter((280.0, 250.0))

    def read_watts(self):
        return next(self.values)


class FailingAudit:
    def append(self, *args, **kwargs):
        raise RuntimeError("disk unavailable")


class HardwareLabTests(unittest.TestCase):
    def config(self, target=125.0):
        return HardwareTrialConfig(UUID, target, "approval-1", "operator:test", 0.0)

    def test_success_is_audited_and_restores_all_device_state(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            control = FakeControl()
            result = run_hardware_trial(
                self.config(), audit_log=audit, control=control, meter=FakeMeter(), sleeper=lambda _: None
            )
            self.assertEqual(-20.0, result.gpu_delta_watts)
            self.assertEqual(-30.0, result.host_delta_watts)
            self.assertTrue(result.restored)
            self.assertEqual(175.0, control.limit)
            self.assertFalse(control.persistence)
            self.assertEqual(
                ["physical_trial.intent", "physical_trial.completed"],
                [record["event_type"] for record in audit.records()],
            )
            self.assertEqual(audit.verify().head_hash, result.audit_head_hash)

    def test_audit_must_succeed_before_any_mutation(self):
        control = FakeControl()
        with self.assertRaisesRegex(RuntimeError, "disk unavailable"):
            run_hardware_trial(
                self.config(), audit_log=FailingAudit(), control=control, meter=FakeMeter()
            )
        self.assertFalse(any(call[0] in {"limit", "persistence"} for call in control.calls))

    def test_ineffective_cap_fails_safe_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            control = FakeControl(ineffective=True)
            with self.assertRaisesRegex(HardwareTrialError, "did not become effective"):
                run_hardware_trial(
                    self.config(), audit_log=audit, control=control, meter=FakeMeter(), sleeper=lambda _: None
                )
            self.assertEqual(175.0, control.limit)
            self.assertFalse(control.persistence)
            self.assertEqual("physical_trial.failed_safe", tuple(audit.records())[-1]["event_type"])

    def test_restore_failure_is_critical_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            with self.assertRaisesRegex(HardwareTrialError, "CRITICAL"):
                run_hardware_trial(
                    self.config(),
                    audit_log=audit,
                    control=FakeControl(fail_restore=True),
                    meter=FakeMeter(),
                    sleeper=lambda _: None,
                )
            self.assertEqual("physical_trial.restore_failed", tuple(audit.records())[-1]["event_type"])

    def test_partial_persistence_failure_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            control = FakeControl(mutate_persistence_then_raise=True)
            with self.assertRaisesRegex(HardwareTrialError, "trial failed"):
                run_hardware_trial(
                    self.config(), audit_log=audit, control=control, meter=FakeMeter(), sleeper=lambda _: None
                )
            self.assertFalse(control.persistence)
            self.assertIn(("persistence", UUID, False), control.calls)

    def test_unobservable_restoration_is_critical_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            with self.assertRaisesRegex(HardwareTrialError, "restoration is unproven"):
                run_hardware_trial(
                    self.config(), audit_log=audit, control=FakeControl(fail_restore_observe=True),
                    meter=FakeMeter(), sleeper=lambda _: None
                )
            self.assertEqual("physical_trial.restore_failed", tuple(audit.records())[-1]["event_type"])

    def test_special_or_symlink_audit_path_is_rejected(self):
        control = FakeControl()
        with self.assertRaisesRegex(HardwareTrialError, "regular non-symlink"):
            run_hardware_trial(self.config(), audit_log=AuditLog("/dev/null"), control=control, meter=FakeMeter())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.jsonl"
            target.touch()
            link = Path(directory) / "audit.jsonl"
            link.symlink_to(target)
            with self.assertRaisesRegex(HardwareTrialError, "regular non-symlink"):
                run_hardware_trial(self.config(), audit_log=AuditLog(link), control=control, meter=FakeMeter())
        self.assertFalse(any(call[0] in {"limit", "persistence"} for call in control.calls))

    def test_invalid_target_fails_before_audit_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "physical.jsonl")
            control = FakeControl()
            with self.assertRaisesRegex(HardwareTrialError, "outside device bounds"):
                run_hardware_trial(self.config(100.0), audit_log=audit, control=control, meter=FakeMeter())
            self.assertEqual(0, audit.verify().record_count)
            self.assertFalse(any(call[0] in {"limit", "persistence"} for call in control.calls))

    def test_dcmi_parser_and_nvidia_commands_are_argv_only(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(tuple(command))
            if "--query-gpu=" in " ".join(command):
                output = f"{UUID}, 20, 175, 125, 175, Disabled\n"
            else:
                output = "Instantaneous power reading: 143 Watts\n"
            return subprocess.CompletedProcess(command, 0, output, "")

        state = NvidiaLabPowerControl(runner=runner).observe(UUID)
        watts = DcmiPowerMeter(runner=runner).read_watts()
        self.assertEqual(175.0, state.power_limit_watts)
        self.assertEqual(143.0, watts)
        self.assertTrue(all(isinstance(command, tuple) for command in calls))


if __name__ == "__main__":
    unittest.main()
