import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from gridgpu.power_adapter import NvidiaSingleGpuPowerControl, PowerAdapterError
from gridgpu.audit import AuditLog
from gridgpu.performance_trial import (
    MeterSample, WorkSample, PerformanceTrialConfig, OperatorAuthorization,
    PerformanceTrialError, run_attended_performance_trial,
)


class PowerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "nvidia-smi"
        self.path.write_text("test executable fixture")
        self.path.chmod(0o700)
        self.limit = 175.0
        self.calls = []
        self.fail_cap = False
        self.ignore_restore = False
        self.extra_gpu = False
        self.hot = False
        self.adapter = NvidiaSingleGpuPowerControl(executable=self.path,
            gpu_uuid="GPU-abcd-1234", target_power_limit_watts=125.0,
            runner=self.run_command, required_owner_uid=os.getuid())

    def run_command(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        if "-pl" in argv:
            watts = float(argv[-1])
            if not (self.ignore_restore and watts == 175):
                self.limit = watts
            if self.fail_cap and watts == 125:
                raise subprocess.TimeoutExpired(argv, 10)
            return subprocess.CompletedProcess(argv, 0, "Power limit set", "")
        row = f"GPU-abcd-1234, 550.1, {self.limit}, 100, 175, {90 if self.hot else 40}, N/A, Default\n"
        return subprocess.CompletedProcess(argv, 0, row * (2 if self.extra_gpu else 1), "")

    def test_cap_restore_and_exact_argv(self):
        self.assertTrue(self.adapter.preflight()[0].healthy)
        self.adapter.set_limit("GPU-abcd-1234", 125)
        self.adapter.set_limit("GPU-abcd-1234", 175)
        self.assertEqual(self.limit, 175)
        writes = [call for call in self.calls if "-pl" in call]
        self.assertEqual(writes, [(str(self.path), "-i", "GPU-abcd-1234", "-pl", "125.000"),
                                 (str(self.path), "-i", "GPU-abcd-1234", "-pl", "175.000")])

    def test_timeout_after_partial_mutation_still_allows_restore(self):
        self.adapter.preflight()
        self.fail_cap = True
        with self.assertRaises(PowerAdapterError):
            self.adapter.set_limit("GPU-abcd-1234", 125)
        self.hot = True
        self.adapter.set_limit("GPU-abcd-1234", 175)
        self.assertEqual(self.limit, 175)

    def test_restore_mismatch_is_explicit(self):
        self.adapter.preflight()
        self.adapter.set_limit("GPU-abcd-1234", 125)
        self.ignore_restore = True
        with self.assertRaisesRegex(PowerAdapterError, "readback"):
            self.adapter.set_limit("GPU-abcd-1234", 175)

    def test_reject_scope_and_arbitrary_limits_without_writes(self):
        self.adapter.preflight()
        for uuid, watts in [("GPU-dead", 125), ("GPU-abcd-1234", 150), ("GPU-abcd-1234", float("nan"))]:
            with self.assertRaises(PowerAdapterError):
                self.adapter.set_limit(uuid, watts)
        self.assertFalse(any("-pl" in call for call in self.calls))

    def test_reject_multiple_gpus_and_hot_device(self):
        self.extra_gpu = True
        with self.assertRaises(PowerAdapterError):
            self.adapter.preflight()
        self.extra_gpu = False
        self.hot = True
        with self.assertRaises(PowerAdapterError):
            self.adapter.preflight()

    def test_executable_replacement_fails_closed(self):
        self.adapter.preflight()
        self.path.write_text("replacement")
        with self.assertRaisesRegex(PowerAdapterError, "provenance"):
            self.adapter.set_limit("GPU-abcd-1234", 125)
        self.assertFalse(any("-pl" in call for call in self.calls))

    def test_cap_cannot_be_replayed(self):
        self.adapter.preflight()
        self.adapter.set_limit("GPU-abcd-1234", 125)
        self.adapter.set_limit("GPU-abcd-1234", 175)
        with self.assertRaisesRegex(PowerAdapterError, "already attempted"):
            self.adapter.set_limit("GPU-abcd-1234", 125)

    def test_preflight_required(self):
        with self.assertRaises(PowerAdapterError):
            self.adapter.set_limit("GPU-abcd-1234", 125)
        self.assertEqual(self.calls, [])

    def test_unattempted_restore_proves_unchanged_without_write(self):
        self.adapter.preflight()
        self.hot = True
        self.adapter.set_limit("GPU-abcd-1234", 175)
        self.assertFalse(any("-pl" in call for call in self.calls))
        self.limit = 150
        with self.assertRaisesRegex(PowerAdapterError, "unexpected state"):
            self.adapter.set_limit("GPU-abcd-1234", 175)
        self.assertFalse(any("-pl" in call for call in self.calls))

    def test_trial_pre_cap_screening_rejection_is_verified_safe(self):
        directory = self.path.parent
        artifact = directory / "workload"
        artifact.write_bytes(b"fixture")
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        config = PerformanceTrialConfig("host", "GPU-abcd-1234", "fixture",
            hashlib.sha256(artifact.read_bytes()).hexdigest(), 125, "meter", "chassis", 2, 10, 2)
        authorization = OperatorAuthorization.bind(config, approval_id="approval", operator="operator",
            expires_at_utc=(now + timedelta(minutes=5)).isoformat(), nonce="nonce")
        def workload(phase, repetition, duration):
            if phase == "baseline" and repetition == 1:
                self.hot = True
            return WorkSample(10, duration, tuple(MeterSample(t, 200,
                (now + timedelta(seconds=t)).isoformat(), "meter", "chassis")
                for t in (0, duration / 2, duration)))
        audit = AuditLog(directory / "audit.jsonl")
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
            run_attended_performance_trial(config, authorization, audit_log=audit,
                control=self.adapter, workload_runner=workload, verify_authorization=lambda _: True,
                attended_confirmation=lambda phrase: phrase, lock_directory=directory,
                workload_artifact_path=artifact, now=lambda: now)
        self.assertEqual(self.limit, 175)
        self.assertFalse(any("-pl" in call for call in self.calls))
