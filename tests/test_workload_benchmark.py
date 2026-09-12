from dataclasses import replace
import unittest

from gridgpu.performance_trial import MeterSample, PerformanceTrialError
from gridgpu.workload_benchmark import (
    BenchmarkRunner, JobOutcome, WorkloadWindow, measure_window, validate_comparison,
)


class WorkloadBenchmarkTests(unittest.TestCase):
    def window(self):
        return WorkloadWindow("a" * 64, 10.0,
            (JobOutcome("first", 0, 2, True), JobOutcome("second", 2, 6, True)),
            tuple(MeterSample(t, w, f"2030-01-01T00:00:{t:02d}+00:00", "meter", "host")
                  for t, w in ((0, 100), (5, 200), (10, 100))))

    def measure(self, window=None, **kwargs):
        options = dict(phase="baseline", repetition=0, expected_sha256="a" * 64,
                       expected_duration=10, meter_source_id="meter", chassis_id="host")
        options.update(kwargs)
        return measure_window(window or self.window(), **options)

    def test_measured_energy_counts_and_latency(self):
        m = self.measure()
        self.assertEqual((m.completed_jobs, m.failed_jobs), (2, 0))
        self.assertEqual(m.throughput_jobs_per_second, 0.2)
        self.assertEqual((m.mean_latency_seconds, m.p95_latency_seconds), (3, 4))
        self.assertEqual(m.host_energy_joules, 1500)
        self.assertEqual(m.joules_per_completed_job, 750)
        self.assertEqual(m.work_sample.useful_units, 2)

    def test_failures_not_counted_as_work(self):
        window = self.window()
        m = self.measure(replace(window, jobs=window.jobs + (JobOutcome("bad", 1, 2, False),)))
        self.assertEqual((m.completed_jobs, m.failed_jobs, m.joules_per_completed_job), (2, 1, 750))

    def test_no_work_and_all_failed_rejected(self):
        for jobs in ((), (JobOutcome("bad", 0, 1, False),)):
            with self.assertRaisesRegex(ValueError, "no completed"):
                self.measure(replace(self.window(), jobs=jobs))

    def test_invalid_job_records_rejected(self):
        cases = (JobOutcome("", 0, 1, True), JobOutcome("a", -1, 1, True),
                 JobOutcome("a", 0, 11, True), JobOutcome("a", 1, 1, True),
                 JobOutcome("a", 0, float("inf"), True), JobOutcome("a", float("nan"), 1, True),
                 JobOutcome("a", False, 1, True), JobOutcome("a", 0, 1, 1))
        for job in cases:
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.measure(replace(self.window(), jobs=(job,)))

    def test_duplicate_job_rejected(self):
        job = self.window().jobs[0]
        with self.assertRaisesRegex(ValueError, "unique"):
            self.measure(replace(self.window(), jobs=(job, job)))

    def test_duration_invalid_or_outside_authorized_window(self):
        for duration in (0, -1, float("nan"), float("inf"), True, "10", 100):
            with self.subTest(duration=duration), self.assertRaises((ValueError, PerformanceTrialError)):
                self.measure(replace(self.window(), duration_seconds=duration))

    def test_bad_manifest_or_phase_rejected(self):
        for kwargs in (dict(expected_sha256="z" * 64), dict(expected_sha256="b" * 64),
                       dict(phase="unknown"), dict(repetition=-1), dict(repetition=True)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.measure(**kwargs)

    def test_meter_must_bind_and_span_window(self):
        window = self.window()
        cases = (window.meter_samples[:-1], tuple(replace(m, source_id="wrong") for m in window.meter_samples),
                 tuple(replace(m, host_watts=float("nan")) for m in window.meter_samples))
        for samples in cases:
            with self.assertRaises(PerformanceTrialError):
                self.measure(replace(window, meter_samples=samples))

    def test_zero_energy_and_overflow_rejected(self):
        for watts in (0, 1e308):
            with self.assertRaisesRegex(ValueError, "finite and positive"):
                self.measure(replace(self.window(), meter_samples=tuple(
                    replace(m, host_watts=watts) for m in self.window().meter_samples)))

    def test_utc_window_must_match_elapsed_window(self):
        samples = self.window().meter_samples
        samples = samples[:2] + (replace(samples[-1], timestamp_utc="2030-01-01T00:00:20+00:00"),)
        with self.assertRaisesRegex(ValueError, "UTC"):
            self.measure(replace(self.window(), meter_samples=samples))

    def runner(self, collector=None):
        return BenchmarkRunner(collector or (lambda *_: self.window()), workload_sha256="a" * 64,
                               meter_source_id="meter", chassis_id="host")

    def test_runner_collects_only_measured_phases(self):
        runner = self.runner()
        for phase in ("baseline", "capped", "restored"):
            runner(phase + "_warmup", -1, 10)
            for i in range(2):
                runner(phase, i, 10)
        self.assertEqual(len(runner.measurements), 6)
        validate_comparison(tuple(runner.measurements), 2)

    def test_runner_error_retained_and_raised(self):
        window = self.window()
        runner = self.runner(lambda *_: replace(window, jobs=window.jobs + (JobOutcome("bad", 0, 1, False),)))
        with self.assertRaisesRegex(ValueError, "errors invalidate"):
            runner("capped", 0, 10)
        self.assertEqual(runner.measurements[0].failed_jobs, 1)

    def test_collector_failure_propagates(self):
        def collector(*_):
            raise RuntimeError("GPU synchronization failed")
        with self.assertRaisesRegex(RuntimeError, "synchronization"):
            self.runner(collector)("baseline", 0, 10)

    def test_duplicate_measurement_rejected(self):
        runner = self.runner()
        runner("baseline", 0, 10)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner("baseline", 0, 10)

    def test_incomplete_comparison_and_workload_changes_rejected(self):
        measurements = tuple(self.measure(phase=p, repetition=i)
                             for p in ("baseline", "capped", "restored") for i in range(2))
        for invalid in (measurements[:-1], measurements[:-1] + (measurements[0],),
                        measurements[:-1] + (replace(measurements[-1], workload_sha256="b" * 64),),
                        measurements[:-1] + (replace(measurements[-1], failed_jobs=1),)):
            with self.assertRaises(ValueError):
                validate_comparison(invalid, 2)


if __name__ == "__main__":
    unittest.main()
