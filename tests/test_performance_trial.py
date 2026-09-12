import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gridgpu.audit import AuditLog
from gridgpu.performance_trial import (
    ExclusiveTrialLock, GpuPreflight, MeterSample, OperatorAuthorization, PerformanceTrialConfig,
    PerformanceTrialError, WorkSample, run_attended_performance_trial,
)


class Control:
    def __init__(self, fail_restore=False, inventory=None):
        self.limit = 175.0
        self.calls = []
        self.fail_restore = fail_restore
        self.inventory = inventory

    def observe_limit(self, gpu_uuid):
        return self.limit

    def preflight(self):
        return self.inventory or (GpuPreflight("GPU-a", True, False, "550.1", "b" * 64),)

    def set_limit(self, gpu_uuid, watts):
        self.calls.append(watts)
        if watts == 175.0 and self.fail_restore:
            raise RuntimeError("restore failed")
        self.limit = watts


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class PerformanceTrialTests(unittest.TestCase):
    def config(self):
        return PerformanceTrialConfig("host-a", "GPU-a", "gemm-v1", "a" * 64,
                                      125.0, "bmc:host-a", "chassis-a", 2.0, 10.0, 2)

    @staticmethod
    def artifact(directory):
        path = Path(directory) / "workload.bin"
        path.write_bytes(b"deterministic-workload")
        return path

    def bound_config(self, artifact):
        return PerformanceTrialConfig("host-a", "GPU-a", "gemm-v1",
            hashlib.sha256(artifact.read_bytes()).hexdigest(), 125.0,
            "bmc:host-a", "chassis-a", 2.0, 10.0, 2)

    def authorization(self, config):
        return OperatorAuthorization.bind(config, approval_id="approve-1", operator="operator:a",
            expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="nonce-1")

    @staticmethod
    def runner(phase, repetition, duration):
        watts = 150.0 if phase.startswith("capped") else 200.0
        units = 900.0 if phase.startswith("capped") else 1000.0
        samples = tuple(MeterSample(t, watts, (NOW + timedelta(seconds=t)).isoformat(),
                                    "bmc:host-a", "chassis-a")
                        for t in (0.0, duration / 2, duration))
        return WorkSample(units, duration, samples)

    def test_deterministic_comparison_and_restoration(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact)
            authorization = self.authorization(config); control = Control()
            result = run_attended_performance_trial(config, authorization,
                audit_log=AuditLog(Path(directory) / "audit.jsonl"), control=control,
                workload_runner=self.runner, verify_authorization=lambda _: True,
                attended_confirmation=lambda phrase: phrase,
                lock_directory=Path(directory), workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([125.0, 175.0, 175.0], control.calls)
            self.assertEqual(100.0, result.baseline[0].throughput_per_second)
            self.assertEqual(90.0, result.capped[0].throughput_per_second)
            self.assertEqual(2000.0, result.baseline[0].host_energy_joules)
            self.assertEqual(2, len(result.restored_samples))
            self.assertEqual(100.0, result.restored_samples[0].throughput_per_second)
            self.assertEqual(2.0, result.restored_samples[0].joules_per_useful_unit)
            self.assertTrue(result.restored)

    def test_restored_workload_failure_reasserts_original_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            def failing(phase, repetition, duration):
                if phase == "restored":
                    raise RuntimeError("restored workload failed")
                return self.runner(phase, repetition, duration)
            with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=failing, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([125.0, 175.0, 175.0], control.calls)
            self.assertEqual(175.0, control.limit)

    def test_nan_cap_observation_stops_work_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact)
            class NanControl(Control):
                def observe_limit(self, gpu_uuid):
                    return float("nan") if self.limit == 125 else self.limit
            control = NanControl()
            phases = []
            def runner(phase, repetition, duration):
                phases.append(phase)
                return self.runner(phase, repetition, duration)
            with self.assertRaisesRegex(PerformanceTrialError, "capped limit"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=runner, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertNotIn("capped_warmup", phases)
            self.assertEqual(175.0, control.limit)

    def test_expiry_during_baseline_prevents_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            times = iter((NOW, NOW + timedelta(minutes=6)))
            with self.assertRaisesRegex(PerformanceTrialError, "expired before"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=self.runner, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: next(times))
            self.assertEqual([], control.calls)

    def test_nonfinite_meter_time_prevents_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            def invalid(phase, repetition, duration):
                raw = self.runner(phase, repetition, duration)
                middle = MeterSample(float("nan"), 200.0,
                    (NOW + timedelta(seconds=5)).isoformat(), "bmc:host-a", "chassis-a")
                return WorkSample(raw.useful_units, duration,
                    (raw.meter_samples[0], middle, raw.meter_samples[-1]))
            with self.assertRaisesRegex(PerformanceTrialError, "elapsed times must be finite"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=invalid, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([], control.calls)

    def test_workload_mutation_during_baseline_prevents_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            def mutate(phase, repetition, duration):
                if phase == "baseline":
                    artifact.write_bytes(b"changed-workload")
                return self.runner(phase, repetition, duration)
            with self.assertRaisesRegex(PerformanceTrialError, "changed before cap"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=mutate, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([], control.calls)

    def test_wrong_binding_or_confirmation_prevents_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            wrong = self.authorization(PerformanceTrialConfig("other", "GPU-a", "gemm-v1", config.workload_sha256,
                125.0, "bmc:host-a", "chassis-a", 2, 10, 2))
            with self.assertRaisesRegex(PerformanceTrialError, "authorization"):
                run_attended_performance_trial(config, wrong, audit_log=AuditLog(Path(directory)/"a"),
                    control=control, workload_runner=self.runner, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([], control.calls)

    def test_failure_after_cap_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact); control = Control()
            def failing(phase, repetition, duration):
                if phase == "capped": raise RuntimeError("workload failed")
                return self.runner(phase, repetition, duration)
            with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=control,
                    workload_runner=failing, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual(175.0, control.limit)
            self.assertEqual("performance_trial.failed_safe",
                             tuple(AuditLog(Path(directory)/"a").records())[-1]["event_type"])

    def test_restore_failure_is_critical(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact)
            audit = AuditLog(Path(directory)/"a")
            with self.assertRaisesRegex(PerformanceTrialError, "CRITICAL"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=audit, control=Control(fail_restore=True),
                    workload_runner=self.runner, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual("performance_trial.restore_failed", tuple(audit.records())[-1]["event_type"])

    def test_lock_excludes_second_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            with ExclusiveTrialLock(Path(directory), "host-a", "GPU-a"):
                with self.assertRaisesRegex(PerformanceTrialError, "owns"):
                    with ExclusiveTrialLock(Path(directory), "host-a", "GPU-a"):
                        pass

    def test_meter_requires_window_and_stable_source(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact)
            def bad(phase, repetition, duration):
                return WorkSample(1, duration, (MeterSample(0, 1, "t", "a", "c"),
                    MeterSample(duration, 1, "t", "b", "c")))
            with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
                run_attended_performance_trial(config, self.authorization(config),
                    audit_log=AuditLog(Path(directory)/"a"), control=Control(), workload_runner=bad,
                    verify_authorization=lambda _: True, attended_confirmation=lambda phrase: phrase,
                    lock_directory=Path(directory), workload_artifact_path=artifact, now=lambda: NOW)

    def test_workload_hash_fails_before_audit_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); control = Control(); config = self.config()
            audit = AuditLog(Path(directory)/"a")
            with self.assertRaisesRegex(PerformanceTrialError, "authorized SHA-256"):
                run_attended_performance_trial(config, self.authorization(config), audit_log=audit,
                    control=control, workload_runner=self.runner, verify_authorization=lambda _: True,
                    attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                    workload_artifact_path=artifact, now=lambda: NOW)
            self.assertEqual([], control.calls)
            self.assertEqual(0, audit.verify().record_count)

    def test_unhealthy_or_mig_gpu_fails_before_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory); config = self.bound_config(artifact)
            for selected in (
                GpuPreflight("GPU-a", False, False, "550.1", "b"*64),
                GpuPreflight("GPU-a", True, True, "550.1", "b"*64),
            ):
                audit = AuditLog(Path(directory)/(selected.healthy and "mig" or "health"))
                control = Control(inventory=(selected, GpuPreflight("GPU-b", True, False, "550.1", "b"*64)))
                with self.assertRaisesRegex(PerformanceTrialError, "preflight"):
                    run_attended_performance_trial(config, self.authorization(config), audit_log=audit,
                        control=control, workload_runner=self.runner, verify_authorization=lambda _: True,
                        attended_confirmation=lambda phrase: phrase, lock_directory=Path(directory),
                        workload_artifact_path=artifact, now=lambda: NOW)
                self.assertEqual([], control.calls)


if __name__ == "__main__":
    unittest.main()
