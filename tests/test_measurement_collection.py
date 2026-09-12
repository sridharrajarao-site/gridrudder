from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from gridgpu.measurement_collection import CollectionError, CompleteFreshCollector
from gridgpu.performance_trial import MeterSample
from gridgpu.workload_benchmark import BenchmarkRunner, JobOutcome, WorkloadWindow


class MeasurementCollectionTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0.0
        self.origin = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.fault = None
        self.calls = 0
        self.wrapper = CompleteFreshCollector(self.collect,
            expected_jobs=lambda *_: ("one", "two"),
            utc_clock=lambda: self.origin + timedelta(seconds=self.elapsed),
            monotonic_clock=lambda: self.elapsed)
        self.runner = BenchmarkRunner(self.wrapper, workload_sha256="a" * 64,
            meter_source_id="meter", chassis_id="chassis")

    def collect(self, request):
        self.calls += 1
        self.assertEqual(request.expected_job_ids, ("one", "two"))
        start = self.origin + timedelta(seconds=self.elapsed)
        self.elapsed += request.duration_seconds
        if self.fault == "timeout":
            self.elapsed += 3
        if self.fault == "raises_timeout":
            raise TimeoutError("collector deadline")
        if self.fault == "stale":
            start -= timedelta(days=1)
        jobs = (JobOutcome("one", 0, 1, True), JobOutcome("two", 1, 2, True))
        if self.fault == "omit":
            jobs = jobs[:1]
        if self.fault == "duplicate":
            jobs = (jobs[0], jobs[0])
        if self.fault == "unexpected":
            jobs = (jobs[0], replace(jobs[1], job_id="other"))
        if self.fault == "failed":
            jobs = (jobs[0], replace(jobs[1], succeeded=False))
        return WorkloadWindow("a" * 64, request.duration_seconds, jobs, tuple(
            MeterSample(t, 200, (start + timedelta(seconds=t)).isoformat(), "meter", "chassis")
            for t in (0, request.duration_seconds / 2, request.duration_seconds)))

    def test_compatible_chronological_runner(self):
        for phase in ("baseline", "capped", "restored"):
            self.runner(phase + "_warmup", -1, 10)
            self.runner(phase, 0, 10)
        self.assertEqual(len(self.runner.measurements), 3)

    def test_omitted_jobs_rejected(self):
        self.fault = "omit"
        with self.assertRaisesRegex(CollectionError, "omit"):
            self.runner("baseline", 0, 10)

    def test_duplicates_and_unexpected_outcomes_rejected(self):
        for i, fault in enumerate(("duplicate", "unexpected")):
            self.setUp()
            self.fault = fault
            with self.assertRaisesRegex(CollectionError, "submitted IDs"):
                self.runner("baseline", i, 10)

    def test_entire_stale_chronological_run_rejected(self):
        for phase in ("baseline", "capped", "restored"):
            self.setUp()
            self.fault = "stale"
            with self.assertRaisesRegex(CollectionError, "stale"):
                self.runner(phase, 0, 10)

    def test_deadline_overrun_rejected_and_cannot_retry(self):
        self.fault = "timeout"
        with self.assertRaisesRegex(CollectionError, "deadline"):
            self.runner("baseline", 0, 10)
        with self.assertRaisesRegex(CollectionError, "unavailable"):
            self.runner("baseline", 0, 10)
        self.assertEqual(self.calls, 1)

    def test_collector_timeout_propagates_and_cannot_retry(self):
        self.fault = "raises_timeout"
        with self.assertRaises(TimeoutError):
            self.runner("baseline", 0, 10)
        with self.assertRaisesRegex(CollectionError, "unavailable"):
            self.runner("baseline", 0, 10)

    def test_failed_complete_job_accounting_reaches_runner(self):
        self.fault = "failed"
        with self.assertRaisesRegex(ValueError, "errors invalidate"):
            self.runner("capped", 0, 10)
        self.assertEqual(self.runner.measurements[0].failed_jobs, 1)
        with self.assertRaisesRegex(CollectionError, "unavailable"):
            self.runner("restored", 0, 10)

    def test_failure_blocks_different_phase_and_repetition_without_collection(self):
        for fault in ("timeout", "raises_timeout", "omit", "duplicate", "stale"):
            self.setUp()
            self.fault = fault
            with self.assertRaises((CollectionError, TimeoutError)):
                self.wrapper("baseline", 0, 10)
            self.fault = None
            for phase, repetition in (("baseline", 1), ("capped", 0), ("restored_warmup", -1)):
                with self.assertRaisesRegex(CollectionError, "unavailable"):
                    self.wrapper(phase, repetition, 10)
            self.assertEqual(self.calls, 1)

    def test_interruption_poisoning(self):
        def interrupted(_):
            raise KeyboardInterrupt()
        wrapper = CompleteFreshCollector(interrupted, expected_jobs=lambda *_: ("one",),
            utc_clock=lambda: self.origin, monotonic_clock=lambda: 0)
        with self.assertRaises(KeyboardInterrupt):
            wrapper("baseline", 0, 10)
        with self.assertRaisesRegex(CollectionError, "unavailable"):
            wrapper("capped", 0, 10)

    def test_duplicate_expected_ids_rejected_before_collection(self):
        wrapper = CompleteFreshCollector(self.collect, expected_jobs=lambda *_: ("same", "same"),
            utc_clock=lambda: self.origin, monotonic_clock=lambda: 0)
        with self.assertRaisesRegex(CollectionError, "unique"):
            wrapper("baseline", 0, 10)
        self.assertEqual(self.calls, 0)

    def test_clock_regression_rejected(self):
        times = iter((20, 10))
        wrapper = CompleteFreshCollector(self.collect, expected_jobs=lambda *_: ("one", "two"),
            utc_clock=lambda: self.origin, monotonic_clock=lambda: next(times))
        with self.assertRaisesRegex(CollectionError, "clocks"):
            wrapper("baseline", 0, 10)
