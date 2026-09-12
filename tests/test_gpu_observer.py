from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from gridgpu.gpu_observer import GpuObservationError, NvidiaPowerObserver
from gridgpu.telemetry import Quality


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
DEVICE_ROW = "0, GPU-abc, NVIDIA Test, 225.5, 80, 300, 150, 350\n"
DRIVER_ROW = "GPU-abc, 580.10\n"


class FakeRunner:
    def __init__(self, device_output=DEVICE_ROW, driver_output=DRIVER_ROW, returncode=0, hook=None):
        self.device_output = device_output
        self.driver_output = driver_output
        self.returncode = returncode
        self.hook = hook
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        if self.hook is not None:
            self.hook(len(self.commands))
        output = self.driver_output if "uuid,driver_version" in command[1] else self.device_output
        return subprocess.CompletedProcess(command, self.returncode, stdout=output, stderr="failed")


class Clock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class GpuObserverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.executable = Path(self.directory.name) / "nvidia-smi"
        self.executable.write_bytes(b"test executable\n")
        self.executable.chmod(0o755)

    def tearDown(self):
        self.directory.cleanup()

    def observer(self, runner=None, clock=None, monotonic=None, **kwargs):
        return NvidiaPowerObserver(
            host_alias="lab-host-a",
            source_epoch="boot-001",
            executable=str(self.executable),
            runner=runner or FakeRunner(),
            clock=clock or Clock((NOW, NOW + timedelta(milliseconds=100))),
            monotonic=monotonic or Clock((10.0, 10.05)),
            **kwargs,
        )

    def test_collects_qualified_compatible_read_only_observation(self):
        runner = FakeRunner()
        observation = self.observer(runner=runner).collect()[0]
        self.assertEqual(observation.timestamp_utc, NOW)
        self.assertEqual(observation.ingested_at_utc, NOW + timedelta(milliseconds=100))
        self.assertEqual(observation.watts, 225.5)
        self.assertEqual(observation.source_id, "lab-host-a:GPU-abc")
        self.assertEqual(observation.gpu_uuid, "GPU-abc")
        self.assertEqual(observation.source_epoch, "boot-001")
        self.assertEqual(observation.monotonic_sequence, 0)
        self.assertIs(observation.quality, Quality.GOOD)
        self.assertEqual(observation.driver_version, "580.10")
        self.assertAlmostEqual(observation.command_duration_ms, 50.0)
        self.assertEqual(observation.executable.resolved_path, str(self.executable.resolve()))
        self.assertEqual(len(observation.executable.sha256), 64)
        self.assertEqual(observation.executable.owner_uid, os.stat(self.executable).st_uid)
        self.assertFalse(observation.executable.is_symlink)
        self.assertTrue(all("--query-gpu=" in command[1] for command in runner.commands))
        self.assertTrue(all("-pl" not in part and "--power-limit" not in part for command in runner.commands for part in command))

    def test_sequence_advances_only_after_successful_collection(self):
        clock = Clock((NOW, NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=1)))
        monotonic = Clock((1.0, 1.1, 2.0, 2.1))
        observer = self.observer(clock=clock, monotonic=monotonic)
        self.assertEqual(observer.collect()[0].monotonic_sequence, 0)
        self.assertEqual(observer.collect()[0].monotonic_sequence, 1)

    def test_missing_symlink_and_changed_executable_fail_closed(self):
        with self.assertRaises(GpuObservationError):
            NvidiaPowerObserver(host_alias="h", source_epoch="e", executable=str(self.executable) + "-missing")
        link = Path(self.directory.name) / "nvidia-smi-link"
        link.symlink_to(self.executable)
        with self.assertRaises(GpuObservationError):
            NvidiaPowerObserver(host_alias="h", source_epoch="e", executable=str(link))

        def mutate(call_number):
            if call_number == 1:
                self.executable.write_bytes(b"changed\n")
                self.executable.chmod(0o755)

        with self.assertRaises(GpuObservationError):
            self.observer(runner=FakeRunner(hook=mutate)).collect()

    def test_command_error_duplicate_or_mismatched_identity_fail_closed(self):
        cases = (
            FakeRunner(returncode=9),
            FakeRunner(device_output=DEVICE_ROW + DEVICE_ROW),
            FakeRunner(driver_output="GPU-abc, 580.10\nGPU-abc, 580.10\n"),
            FakeRunner(driver_output="GPU-other, 580.10\n"),
            FakeRunner(device_output="0, GPU-abc, Test, N/A, 0, 300, 150, 350\n"),
        )
        for runner in cases:
            with self.subTest(runner=runner):
                with self.assertRaises(GpuObservationError):
                    self.observer(runner=runner).collect()

    def test_stale_error_and_naive_timestamps_fail_closed(self):
        clocks = (
            Clock((NOW, NOW + timedelta(seconds=6))),
            Clock((NOW + timedelta(seconds=1), NOW)),
            Clock((datetime(2026, 8, 30, 12, 0), datetime(2026, 8, 30, 12, 0))),
        )
        for clock in clocks:
            with self.subTest(clock=clock):
                with self.assertRaises(GpuObservationError):
                    self.observer(clock=clock, maximum_ingest_age_seconds=5).collect()


if __name__ == "__main__":
    unittest.main()
