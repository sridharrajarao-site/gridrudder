from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from gridgpu.live_measurement import LiveReadOnlyCollector
from gridgpu.measurement_collection import CompleteFreshCollector, CollectionError
from gridgpu.workload_benchmark import BenchmarkRunner, JobOutcome


class LiveMeasurementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        for name in ("nvidia", "ipmi"):
            path = self.directory / name
            path.write_text("fixture only")
            path.chmod(0o700)
        self.elapsed = 0.0
        self.origin = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.fault = None
        self.calls = []
        self.submitted = []
        self.collector = LiveReadOnlyCollector(host_id="host", chassis_id="chassis",
            gpu_uuid="GPU-abcd", meter_id="meter", physical_boundary="whole-host",
            source_epoch="test", workload_sha256="a" * 64,
            nvidia_executable=self.directory / "nvidia", bmc_executable=self.directory / "ipmi",
            runner=self.command, utc_clock=self.utc, monotonic_clock=lambda: self.elapsed,
            sleeper=self.sleep, start_workload=self.start, finish_workload=self.finish,
            required_owner_uid=os.getuid())
        wrapper = CompleteFreshCollector(self.collector, expected_jobs=lambda *_: ("one",),
            utc_clock=self.utc, monotonic_clock=lambda: self.elapsed)
        self.benchmark = BenchmarkRunner(wrapper, workload_sha256="a" * 64,
            meter_source_id="host:meter", chassis_id="chassis")

    def utc(self):
        return self.origin + timedelta(seconds=self.elapsed)

    def sleep(self, duration):
        self.elapsed += duration

    def start(self, request, origin):
        self.submitted.append(request.expected_job_ids)

    def finish(self, request, origin):
        if self.fault == "late_finish":
            self.elapsed += 0.1
            return (JobOutcome("one", 0.5, self.elapsed - origin, True),)
        if self.fault == "missing":
            return ()
        return (JobOutcome("one", 0.5, 1.5, True),)

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(kwargs["timeout"], 0.25)
        if self.fault == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if self.fault == "nonzero":
            return subprocess.CompletedProcess(argv, 1, "", "rejected")
        if self.fault == "slow":
            self.elapsed += 0.1
        if "fru" in argv:
            output = "Chassis Serial : chassis\n"
        elif "dcmi" in argv:
            output = "Instantaneous power reading: 200 Watts\n"
        else:
            output = "GPU-abcd, N/A, 550.1\n" if self.fault == "bad_nvidia" else "GPU-abcd, 120, 550.1\n"
        if self.fault == "malformed":
            output = "bad response"
        return subprocess.CompletedProcess(argv, 0, output, "")

    def test_collector_composes_with_freshness_and_benchmark(self):
        sample = self.benchmark("baseline", 0, 2)
        self.assertEqual(sample.useful_units, 1)
        self.assertEqual(len(sample.meter_samples), 3)
        self.assertEqual(self.benchmark.measurements[0].host_energy_joules, 400)
        self.assertEqual(self.submitted, [("one",)])
        self.assertEqual(len(self.collector.evidence), 3)
        self.assertFalse(any(flag in argv for argv in self.calls for flag in ("-pl", "-pm", "sudo")))

    def test_subprocess_timeout_and_nonzero_fail_closed(self):
        for fault in ("timeout", "nonzero"):
            with self.subTest(fault=fault):
                self.setUp()
                self.fault = fault
                with self.assertRaises(CollectionError):
                    self.benchmark("baseline", 0, 2)
                self.assertEqual(self.submitted, [])

    def test_malformed_bmc_fails_closed(self):
        self.fault = "malformed"
        with self.assertRaises(RuntimeError):
            self.benchmark("baseline", 0, 2)
        self.assertEqual(self.submitted, [])

    def test_missing_outcomes_fail_closed(self):
        self.fault = "missing"
        with self.assertRaisesRegex(CollectionError, "every submitted"):
            self.benchmark("baseline", 0, 2)

    def test_completion_after_meter_window_is_rejected_and_runner_poisoned(self):
        self.fault = "late_finish"
        with self.assertRaises(ValueError):
            self.benchmark("baseline", 0, 2)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.benchmark("capped", 0, 2)
        self.assertEqual(len(self.submitted), 1)

    def test_malformed_nvidia_watts_fail_closed(self):
        self.fault = "bad_nvidia"
        with self.assertRaisesRegex(CollectionError, "NVIDIA watts"):
            self.benchmark("baseline", 0, 2)
        self.assertEqual(self.submitted, [])

    def test_excess_acquisition_skew_rejected(self):
        self.fault = "slow"
        with self.assertRaisesRegex(CollectionError, "acquisition skew"):
            self.benchmark("baseline", 0, 2)

    def test_changed_nvidia_executable_rejected(self):
        (self.directory / "nvidia").write_text("changed")
        with self.assertRaisesRegex(CollectionError, "provenance"):
            self.benchmark("baseline", 0, 2)
