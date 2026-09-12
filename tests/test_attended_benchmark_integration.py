"""Compose real orchestration classes around entirely injected fake hardware."""

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from gridgpu.audit import AuditLog
from gridgpu.performance_trial import (
    MeterSample, OperatorAuthorization, PerformanceTrialConfig,
    PerformanceTrialError, run_attended_performance_trial,
)
from gridgpu.power_adapter import NvidiaSingleGpuPowerControl
from gridgpu.workload_benchmark import (
    BenchmarkRunner, JobOutcome, WorkloadWindow, validate_comparison,
)


class AttendedBenchmarkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.executable = self.directory / "fake-nvidia-smi"
        self.executable.write_bytes(b"not an executable program; injected runner only")
        self.executable.chmod(0o700)
        self.artifact = self.directory / "workload-fixture"
        self.artifact.write_bytes(b"fixed workload identity")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.config = PerformanceTrialConfig("host", "GPU-abcd-1234", "fixture", self.digest,
            125, "bmc:host", "chassis", 2, 10, 2)
        self.authorization = OperatorAuthorization.bind(self.config, approval_id="test-only",
            operator="test", expires_at_utc=(self.now + timedelta(minutes=10)).isoformat(), nonce="test")
        self.limit = 175.0
        self.offset = 0.0
        self.writes = []
        self.phases = []
        self.fault = None
        self.audit = AuditLog(self.directory / "audit.jsonl")
        self.control = NvidiaSingleGpuPowerControl(executable=self.executable,
            gpu_uuid=self.config.gpu_uuid, target_power_limit_watts=125,
            runner=self.command, required_owner_uid=os.getuid())
        self.benchmark = BenchmarkRunner(self.collect, workload_sha256=self.digest,
            meter_source_id=self.config.meter_source_id, chassis_id=self.config.chassis_id)

    def command(self, argv, **kwargs):
        if "-pl" in argv:
            requested = float(argv[-1])
            self.writes.append(requested)
            if not (self.fault == "restore_mismatch" and requested == 175):
                self.limit = requested
            if self.fault == "partial_cap_timeout" and requested == 125:
                raise subprocess.TimeoutExpired(argv, 10)
            return subprocess.CompletedProcess(argv, 0, "fixture acknowledgement", "")
        return subprocess.CompletedProcess(argv, 0,
            f"GPU-abcd-1234, 550.1, {self.limit}, 100, 175, 40, N/A, Default\n", "")

    def collect(self, phase, repetition, duration):
        self.phases.append((phase, repetition))
        origin = self.now + timedelta(seconds=self.offset)
        if self.fault == "replayed_meter" and phase == "capped":
            origin = self.now
        self.offset += duration
        watts = 150 if self.limit == 125 else 200
        jobs = (JobOutcome("job-1", 0, duration / 3, True),
                JobOutcome("job-2", duration / 3, duration * 2 / 3, True))
        if phase == "capped" and self.fault == "missing_jobs":
            jobs = ()
        if phase == "capped" and self.fault == "failed_job":
            jobs += (JobOutcome("job-failed", 0, duration / 2, False),)
        samples = tuple(MeterSample(t, watts, (origin + timedelta(seconds=t)).isoformat(),
            "bmc:host", "chassis") for t in (0, duration / 2, duration))
        return WorkloadWindow(self.digest, duration, jobs, samples)

    def run_trial(self):
        return run_attended_performance_trial(self.config, self.authorization,
            audit_log=self.audit, control=self.control, workload_runner=self.benchmark,
            verify_authorization=lambda _: True, attended_confirmation=lambda phrase: phrase,
            lock_directory=self.directory, workload_artifact_path=self.artifact, now=lambda: self.now)

    def test_full_chronological_comparison_and_restoration(self):
        result = self.run_trial()
        validate_comparison(tuple(self.benchmark.measurements), 2)
        self.assertEqual(len(self.phases), 9)
        self.assertEqual(self.writes, [125, 175, 175])
        self.assertEqual(self.limit, 175)
        self.assertTrue(result.restored)
        self.assertEqual(result.baseline[0].host_energy_joules, 2000)
        self.assertEqual(result.capped[0].host_energy_joules, 1500)
        self.assertEqual(result.capped[0].joules_per_useful_unit, 750)
        self.assertEqual(result.restored_samples[0].joules_per_useful_unit, 1000)
        samples = [m.work_sample.meter_samples for m in self.benchmark.measurements]
        self.assertTrue(all(left[-1].timestamp_utc <= right[0].timestamp_utc
                            for left, right in zip(samples, samples[1:])))

    def test_missing_all_jobs_restores_and_rejects_comparison(self):
        self.fault = "missing_jobs"
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely.*no completed"):
            self.run_trial()
        self.assertEqual(self.limit, 175)
        self.assertEqual(self.writes, [125, 175])
        with self.assertRaises(ValueError):
            validate_comparison(tuple(self.benchmark.measurements), 2)

    def test_failed_job_is_retained_and_restoration_runs(self):
        self.fault = "failed_job"
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely.*errors invalidate"):
            self.run_trial()
        self.assertEqual(self.limit, 175)
        self.assertEqual(self.benchmark.measurements[-1].failed_jobs, 1)
        self.assertEqual(self.benchmark.measurements[-1].completed_jobs, 2)
        self.assertFalse(any(phase == "restored" for phase, _ in self.phases))

    def test_partial_cap_timeout_restores_before_any_capped_work(self):
        self.fault = "partial_cap_timeout"
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
            self.run_trial()
        self.assertEqual(self.limit, 175)
        self.assertEqual(self.writes, [125, 175])
        self.assertFalse(any(phase.startswith("capped") for phase, _ in self.phases))

    def test_failed_restoration_is_critical_and_never_runs_restored_work(self):
        self.fault = "restore_mismatch"
        with self.assertRaisesRegex(PerformanceTrialError, "CRITICAL.*restoration is unproven"):
            self.run_trial()
        self.assertEqual(self.limit, 125)
        self.assertEqual(self.writes, [125, 175, 175])
        self.assertFalse(any(phase.startswith("restored") for phase, _ in self.phases))

    def test_replayed_meter_window_rejects_and_restores(self):
        self.fault = "replayed_meter"
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely.*overlap"):
            self.run_trial()
        self.assertEqual(self.limit, 175)
        self.assertFalse(any(m.phase == "capped" for m in self.benchmark.measurements))
