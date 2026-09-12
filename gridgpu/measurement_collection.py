"""Freshness and complete fixed-job accounting around an injected collector."""

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Callable

from .workload_benchmark import WorkloadWindow


class CollectionError(ValueError):
    pass


@dataclass(frozen=True)
class CollectionRequest:
    phase: str
    repetition: int
    duration_seconds: float
    expected_job_ids: tuple[str, ...]
    deadline_monotonic: float


class CompleteFreshCollector:
    """Callable accepted directly by BenchmarkRunner's existing collector seam.

    A trusted scheduler supplies expected IDs *before* collection; the collector
    cannot declare its own expected count after seeing which jobs completed.
    Deadlines are cooperative: this wrapper detects overruns after return, and
    does not kill threads/processes or interrupt blocked hardware calls.
    """

    def __init__(self, collector: Callable[[CollectionRequest], WorkloadWindow], *,
                 expected_jobs: Callable[[str, int], tuple[str, ...]],
                 utc_clock: Callable[[], datetime], monotonic_clock: Callable[[], float],
                 completion_grace_seconds: float = 2.0,
                 clock_tolerance_seconds: float = 0.25):
        for value in (completion_grace_seconds, clock_tolerance_seconds):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("collection tolerances must be finite and nonnegative")
        self._collector = collector
        self._expected_jobs = expected_jobs
        self._utc = utc_clock
        self._monotonic = monotonic_clock
        self._grace = completion_grace_seconds
        self._tolerance = clock_tolerance_seconds
        self._used = set()
        self._unavailable = False

    @staticmethod
    def _aware(value):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise CollectionError("UTC clock must provide aware timestamps")
        return value

    def __call__(self, phase: str, repetition: int, duration: float) -> WorkloadWindow:
        if self._unavailable:
            raise CollectionError("collector unavailable after failure or during collection; externally drain work before creating a new instance")
        # Keep the instance unavailable on any exception, including interruption.
        # There is deliberately no reset: this object cannot prove external drain.
        self._unavailable = True
        result = self._collect_once(phase, repetition, duration)
        self._unavailable = any(job.succeeded is not True for job in result.jobs)
        return result

    def _collect_once(self, phase: str, repetition: int, duration: float) -> WorkloadWindow:
        valid_phases = {p for base in ("baseline", "capped", "restored")
                        for p in (base, base + "_warmup")}
        if (phase not in valid_phases or type(repetition) is not int or
                (repetition != -1 if phase.endswith("_warmup") else repetition < 0)):
            raise CollectionError("invalid collection phase or repetition")
        if isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
            raise CollectionError("collection duration must be finite and positive")
        key = (phase, repetition)
        if key in self._used:
            raise CollectionError("collection request already consumed")
        expected = tuple(self._expected_jobs(phase, repetition))
        if (not expected or any(not isinstance(job, str) or not job.strip() for job in expected)
                or len(set(expected)) != len(expected)):
            raise CollectionError("expected job IDs must be nonempty and unique")
        before = self._aware(self._utc())
        started = self._monotonic()
        if not math.isfinite(started):
            raise CollectionError("monotonic clock is invalid")
        self._used.add(key)  # A timeout may leave work running; do not resubmit it.
        request = CollectionRequest(phase, repetition, duration, expected, started + duration + self._grace)
        window = self._collector(request)
        finished = self._monotonic()
        after = self._aware(self._utc())
        elapsed = finished - started
        wall_elapsed = (after - before).total_seconds()
        if (not math.isfinite(elapsed) or elapsed < 0 or wall_elapsed < 0 or
                abs(wall_elapsed - elapsed) > self._tolerance):
            raise CollectionError("collection clocks regressed or disagree")
        if finished > request.deadline_monotonic:
            raise CollectionError("collection deadline exceeded")
        if elapsed + self._tolerance < duration:
            raise CollectionError("collection returned before the requested window elapsed")
        actual = tuple(job.job_id for job in window.jobs)
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise CollectionError("job outcomes omit, duplicate, or add submitted IDs")
        if len(window.meter_samples) < 3:
            raise CollectionError("meter collection requires a complete window")
        for sample in window.meter_samples:
            try:
                timestamp = self._aware(datetime.fromisoformat(sample.timestamp_utc.replace("Z", "+00:00")))
            except (TypeError, ValueError) as exc:
                raise CollectionError("invalid meter timestamp") from exc
            if ((timestamp - before).total_seconds() < -self._tolerance or
                    (timestamp - after).total_seconds() > self._tolerance):
                raise CollectionError("meter evidence is stale or outside this collection")
        first, last = window.meter_samples[0], window.meter_samples[-1]
        start = datetime.fromisoformat(first.timestamp_utc.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last.timestamp_utc.replace("Z", "+00:00"))
        if ((start - before).total_seconds() > self._grace + self._tolerance or
                (after - end).total_seconds() > self._grace + self._tolerance):
            raise CollectionError("meter window is detached from collection boundaries")
        # BenchmarkRunner still validates job results, hash, durations, source,
        # energy samples and chronology; failed jobs are retained then rejected.
        return window
