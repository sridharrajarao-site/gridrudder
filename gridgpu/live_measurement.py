"""Local read-only GPU/BMC sampling around an explicitly supplied workload.

No result is marked qualified by this module. Real clocks, validated independent
meter qualification and workload completion synchronization remain caller duties.
"""
from dataclasses import dataclass
import csv
from datetime import datetime
import math
from pathlib import Path
import subprocess
from typing import Callable

from .measurement_collection import CollectionRequest, CollectionError
from .performance_trial import MeterSample
from .qualification import BmcPowerObserver, inspect_pinned_executable
from .workload_benchmark import JobOutcome, WorkloadWindow


@dataclass(frozen=True)
class ReadOnlySampleEvidence:
    utc: datetime
    elapsed_seconds: float
    gpu_watts: float
    gpu_uuid: str
    driver_version: str
    gpu_response: str
    nvidia_sha256: str
    bmc: object
    acquisition_seconds: float


class LiveReadOnlyCollector:
    """CollectionRequest -> WorkloadWindow seam for CompleteFreshCollector.

    start_workload(request, monotonic_origin) must submit precisely the provided
    IDs and return promptly. finish_workload(request, monotonic_origin) must
    synchronize completion and return every JobOutcome with times relative to
    that origin. Neither callback is implemented or authorized by this class.
    """
    NVIDIA_QUERY = "--query-gpu=uuid,power.draw,driver_version"

    def __init__(self, *, host_id: str, chassis_id: str, gpu_uuid: str,
                 meter_id: str, physical_boundary: str, source_epoch: str,
                 workload_sha256: str, nvidia_executable: Path, bmc_executable: Path,
                 runner: Callable, utc_clock: Callable, monotonic_clock: Callable,
                 sleeper: Callable, start_workload: Callable, finish_workload: Callable,
                 sample_interval_seconds: float = 1.0, maximum_acquisition_seconds: float = 0.25,
                 required_owner_uid: int = 0):
        for value in (sample_interval_seconds, maximum_acquisition_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("sample interval and acquisition budget must be positive")
        self._nvidia = inspect_pinned_executable(nvidia_executable, required_owner_uid)
        self._bmc_provenance = inspect_pinned_executable(bmc_executable, required_owner_uid)
        self._owner = required_owner_uid
        self._runner, self._utc, self._mono, self._sleep = runner, utc_clock, monotonic_clock, sleeper
        self._start, self._finish = start_workload, finish_workload
        self._interval, self._budget = sample_interval_seconds, maximum_acquisition_seconds
        self._deadline = None
        self._used = False
        self._failed = False
        self.gpu_uuid, self.workload_sha256 = gpu_uuid, workload_sha256
        self.evidence = []
        self._bmc = BmcPowerObserver(host_id=host_id, expected_chassis_id=chassis_id,
            meter_id=meter_id, physical_boundary=physical_boundary, source_epoch=source_epoch,
            executable=bmc_executable, runner=self._run, clock=utc_clock,
            monotonic=monotonic_clock, required_owner_uid=required_owner_uid,
            clock_synchronized=False)

    def _run(self, argv, **kwargs):
        allowed = {(self._nvidia.resolved_path, self.NVIDIA_QUERY, "--format=csv,noheader,nounits"),
                   (self._bmc_provenance.resolved_path, "fru", "print", "0"),
                   (self._bmc_provenance.resolved_path, "dcmi", "power", "reading")}
        if tuple(argv) not in allowed:
            raise CollectionError("command outside read-only allowlist")
        remaining = self._deadline - self._mono()
        if remaining <= 0:
            raise CollectionError("collection deadline exceeded")
        try:
            result = self._runner(tuple(argv), capture_output=True, text=True, check=False,
                timeout=min(10.0, remaining, self._budget),
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        except (OSError, subprocess.SubprocessError) as exc:
            raise CollectionError("read-only command failed or timed out") from exc
        if result.returncode != 0:
            raise CollectionError("read-only command returned nonzero")
        return result

    def _sample(self, origin):
        began = self._mono()
        if origin is None:
            origin = began
            self._sample_origin = began
        bmc = self._bmc.collect()
        if inspect_pinned_executable(Path(self._nvidia.resolved_path), self._owner) != self._nvidia:
            raise CollectionError("NVIDIA provenance changed")
        raw = self._run((self._nvidia.resolved_path, self.NVIDIA_QUERY, "--format=csv,noheader,nounits")).stdout
        if inspect_pinned_executable(Path(self._nvidia.resolved_path), self._owner) != self._nvidia:
            raise CollectionError("NVIDIA provenance changed")
        rows = list(csv.reader(raw.splitlines()))
        if len(rows) != 1 or len(rows[0]) != 3 or rows[0][0].strip() != self.gpu_uuid:
            raise CollectionError("expected one exact GPU observation")
        try:
            gpu_watts = float(rows[0][1])
        except ValueError as exc:
            raise CollectionError("malformed NVIDIA watts") from exc
        driver = rows[0][2].strip()
        latency = self._mono() - began
        if not math.isfinite(gpu_watts) or gpu_watts < 0 or not driver or not 0 <= latency <= self._budget:
            raise CollectionError("invalid GPU reading or excessive acquisition skew")
        snapshot = bmc.observation.snapshot
        reading = snapshot.active_power
        elapsed = began - origin
        self.evidence.append(ReadOnlySampleEvidence(reading.timestamp_utc, elapsed, gpu_watts,
            self.gpu_uuid, driver, raw, self._nvidia.sha256, bmc, latency))
        return MeterSample(elapsed, reading.value, reading.timestamp_utc.isoformat(),
            reading.source_id, bmc.chassis_id)

    def __call__(self, request: CollectionRequest) -> WorkloadWindow:
        if self._used or self._failed:
            raise CollectionError("collector is active or failed; external workload drain required")
        self._used = True
        try:
            self._deadline = request.deadline_monotonic
            if (not math.isfinite(request.duration_seconds) or request.duration_seconds <= 0 or
                    not math.isfinite(request.deadline_monotonic) or
                    self._interval > request.duration_seconds / 2):
                raise CollectionError("window requires at least three scheduled meter samples")
            samples = [self._sample(None)]
            origin = self._sample_origin
            self._start(request, origin)
            target = origin + self._interval
            end = origin + request.duration_seconds
            while True:
                target = min(target, end)
                self._sleep(max(0, target - self._mono()))
                samples.append(self._sample(origin))
                if target == end:
                    break
                target += self._interval
            jobs = tuple(self._finish(request, origin))
            if self._mono() > self._deadline:
                raise CollectionError("workload completion exceeded collection deadline")
            ids = tuple(job.job_id for job in jobs)
            if len(ids) != len(set(ids)) or set(ids) != set(request.expected_job_ids):
                raise CollectionError("workload outcomes do not account for every submitted ID")
            window = WorkloadWindow(self.workload_sha256, samples[-1].elapsed_seconds, jobs, tuple(samples))
            if any(job.succeeded is not True for job in jobs):
                self._failed = True
            return window
        except BaseException:
            self._failed = True
            raise
        finally:
            self._used = False
