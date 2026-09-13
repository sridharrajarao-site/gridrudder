"""Hardware-free contracts for a fixed-workload, whole-server energy trial.

Collectors must synchronize GPU completion before recording job completion.
No hardware, clock, or workload measurements are synthesized by this module.
"""
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Callable

from .performance_trial import MeterSample, WorkSample, _measure


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class JobOutcome:
    job_id: str
    started_seconds: float
    finished_seconds: float
    succeeded: bool


@dataclass(frozen=True)
class WorkloadWindow:
    workload_sha256: str
    duration_seconds: float
    jobs: tuple[JobOutcome, ...]
    meter_samples: tuple[MeterSample, ...]


@dataclass(frozen=True)
class BenchmarkMeasurement:
    phase: str
    repetition: int
    workload_sha256: str
    completed_jobs: int
    failed_jobs: int
    duration_seconds: float
    throughput_jobs_per_second: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    host_energy_joules: float
    joules_per_completed_job: float
    work_sample: WorkSample


def measure_window(window: WorkloadWindow, *, phase: str, repetition: int,
                   expected_sha256: str, expected_duration: float,
                   meter_source_id: str, chassis_id: str) -> BenchmarkMeasurement:
    """Count only successfully validated jobs; retain errors for claim gating."""
    if phase not in ("baseline", "capped", "restored"):
        raise ValueError("unknown benchmark phase")
    if type(repetition) is not int or repetition < 0:
        raise ValueError("repetition must be a nonnegative integer")
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in expected_sha256) or
            window.workload_sha256 != expected_sha256):
        raise ValueError("workload manifest SHA-256 mismatch")
    if (not _finite(expected_duration) or expected_duration <= 0 or
            not _finite(window.duration_seconds) or window.duration_seconds <= 0):
        raise ValueError("window durations must be finite and positive")
    seen = set()
    latencies = []
    failures = 0
    for job in window.jobs:
        if not isinstance(job.job_id, str) or not job.job_id.strip() or job.job_id in seen:
            raise ValueError("jobs require unique nonempty identifiers")
        seen.add(job.job_id)
        if (not _finite(job.started_seconds) or not _finite(job.finished_seconds) or
                not 0 <= job.started_seconds < job.finished_seconds <= window.duration_seconds):
            raise ValueError("jobs must start and finish inside the measured window")
        if type(job.succeeded) is not bool:
            raise ValueError("job success must be explicit boolean")
        if job.succeeded:
            latencies.append(job.finished_seconds - job.started_seconds)
        else:
            failures += 1
    if not latencies:
        raise ValueError("no completed useful jobs; efficiency is undefined")
    # Use the attended-trial meter validation/integration rather than a second formula.
    raw = WorkSample(len(latencies), window.duration_seconds, window.meter_samples)
    measured = _measure(phase, repetition, raw, expected_duration, meter_source_id, chassis_id)
    timestamps = window.meter_samples
    origin = datetime.fromisoformat(timestamps[0].timestamp_utc.replace("Z", "+00:00"))
    for sample in timestamps:
        timestamp = datetime.fromisoformat(sample.timestamp_utc.replace("Z", "+00:00"))
        if abs((timestamp - origin).total_seconds() - sample.elapsed_seconds) > 0.1:
            raise ValueError("meter UTC and elapsed windows disagree")
    values = (measured.host_energy_joules, measured.throughput_per_second,
              measured.joules_per_useful_unit)
    if any(not _finite(value) or value <= 0 for value in values):
        raise ValueError("energy and work metrics must be finite and positive")
    latencies.sort()
    return BenchmarkMeasurement(phase, repetition, expected_sha256, len(latencies), failures,
        window.duration_seconds, measured.throughput_per_second,
        sum(latencies) / len(latencies), latencies[math.ceil(0.95 * len(latencies)) - 1],
        measured.host_energy_joules, measured.joules_per_useful_unit, raw)


class BenchmarkRunner:
    """Injected collection adapter for run_attended_performance_trial.

    Warmup uses the same validated workload but is excluded from measurements.
    An error during any window fails the trial so its restoration path runs.
    """
    def __init__(self, collector: Callable[[str, int, float], WorkloadWindow], *,
                 workload_sha256: str, meter_source_id: str, chassis_id: str):
        self.collector = collector
        self.workload_sha256 = workload_sha256
        self.meter_source_id = meter_source_id
        self.chassis_id = chassis_id
        self.measurements: list[BenchmarkMeasurement] = []
        self._last_window_end = None
        self._unavailable = False

    def __call__(self, phase: str, repetition: int, duration: float) -> WorkSample:
        if self._unavailable:
            raise ValueError("benchmark runner unavailable after failure; stop and drain work before creating a new runner")
        self._unavailable = True
        result = self._run_once(phase, repetition, duration)
        self._unavailable = False
        return result

    def _run_once(self, phase: str, repetition: int, duration: float) -> WorkSample:
        warmup = phase.endswith("_warmup")
        base_phase = phase[:-7] if warmup else phase
        if warmup and repetition != -1:
            raise ValueError("warmup repetition must be -1")
        if not warmup and any(m.phase == phase and m.repetition == repetition for m in self.measurements):
            raise ValueError("duplicate measurement")
        measured = measure_window(self.collector(phase, repetition, duration), phase=base_phase,
            repetition=0 if warmup else repetition, expected_sha256=self.workload_sha256,
            expected_duration=duration, meter_source_id=self.meter_source_id, chassis_id=self.chassis_id)
        start, end = _window_bounds(measured)
        if self._last_window_end is not None and start < self._last_window_end:
            raise ValueError("meter windows overlap, replay, or regress in time")
        self._last_window_end = end
        if not warmup:
            self.measurements.append(measured)
        if measured.failed_jobs:
            raise ValueError("workload errors invalidate the performance trial")
        return measured.work_sample


def _window_bounds(measurement: BenchmarkMeasurement) -> tuple[datetime, datetime]:
    samples = measurement.work_sample.meter_samples
    return tuple(datetime.fromisoformat(sample.timestamp_utc.replace("Z", "+00:00"))
                 for sample in (samples[0], samples[-1]))


def validate_comparison(measurements: tuple[BenchmarkMeasurement, ...], repetitions: int) -> None:
    """Require a complete repeated comparison before interpreting results."""
    if type(repetitions) is not int or repetitions < 2:
        raise ValueError("at least two repetitions required")
    expected = {(phase, i) for phase in ("baseline", "capped", "restored") for i in range(repetitions)}
    if len(measurements) != len(expected) or {(m.phase, m.repetition) for m in measurements} != expected:
        raise ValueError("comparison requires each baseline/capped/restored repetition exactly once")
    if len({m.workload_sha256 for m in measurements}) != 1 or any(m.failed_jobs for m in measurements):
        raise ValueError("comparison mixes workloads or contains errors")
    ordered = sorted(measurements, key=lambda m: (("baseline", "capped", "restored").index(m.phase), m.repetition))
    previous_end = None
    for measured in ordered:
        start, end = _window_bounds(measured)
        if previous_end is not None and start < previous_end:
            raise ValueError("comparison meter windows overlap, replay, or regress in time")
        previous_end = end
