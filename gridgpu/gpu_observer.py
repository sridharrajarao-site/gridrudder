"""Provenance-qualified, read-only NVIDIA power observation collector."""

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

from .adapters import AdapterError
from .nvml import NvidiaSmiShadowAdapter
from .telemetry import Quality


class GpuObservationError(RuntimeError):
    """Raised when no qualified observation may be emitted."""


@dataclass(frozen=True)
class ExecutableProvenance:
    resolved_path: str
    sha256: str
    owner_uid: int
    owner_gid: int
    mode: int
    is_symlink: bool


@dataclass(frozen=True)
class QualifiedGpuPowerObservation:
    """Compatible with ``alignment.GpuPowerObservation`` plus provenance."""

    timestamp_utc: datetime
    ingested_at_utc: datetime
    watts: float
    source_id: str
    quality: Quality
    host_alias: str
    gpu_uuid: str
    source_epoch: str
    monotonic_sequence: int
    executable: ExecutableProvenance
    driver_version: str
    command_duration_ms: float

    def __post_init__(self) -> None:
        for name, value in (
            ("host_alias", self.host_alias),
            ("gpu_uuid", self.gpu_uuid),
            ("source_id", self.source_id),
            ("source_epoch", self.source_epoch),
            ("driver_version", self.driver_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("{} must be non-empty".format(name))
        if self.source_id != "{}:{}".format(self.host_alias, self.gpu_uuid):
            raise ValueError("source_id must bind host_alias and gpu_uuid")
        for field, value in (
            ("timestamp_utc", self.timestamp_utc),
            ("ingested_at_utc", self.ingested_at_utc),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("{} must be timezone-aware".format(field))
        if self.ingested_at_utc < self.timestamp_utc:
            raise ValueError("ingest timestamp precedes collection timestamp")
        if not math.isfinite(self.watts) or self.watts < 0:
            raise ValueError("watts must be finite and non-negative")
        if self.quality is not Quality.GOOD:
            raise ValueError("qualified observations must have GOOD quality")
        if self.monotonic_sequence < 0:
            raise ValueError("monotonic_sequence must be non-negative")
        if not math.isfinite(self.command_duration_ms) or self.command_duration_ms < 0:
            raise ValueError("command_duration_ms must be finite and non-negative")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NvidiaPowerObserver:
    """Collect telemetry through query-only ``nvidia-smi`` invocations."""

    def __init__(
        self,
        *,
        host_alias: str,
        source_epoch: str,
        executable: str = "nvidia-smi",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        which: Callable[[str], Optional[str]] = shutil.which,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        maximum_ingest_age_seconds: float = 5.0,
    ) -> None:
        if not host_alias.strip() or not source_epoch.strip():
            raise ValueError("host_alias and source_epoch must be non-empty")
        if maximum_ingest_age_seconds < 0 or not math.isfinite(maximum_ingest_age_seconds):
            raise ValueError("maximum_ingest_age_seconds must be finite and non-negative")
        resolved = executable if "/" in executable else which(executable)
        if resolved is None:
            raise GpuObservationError("nvidia-smi executable not found")
        self.host_alias = host_alias
        self.source_epoch = source_epoch
        self._runner = runner
        self._clock = clock
        self._monotonic = monotonic
        self._maximum_age = maximum_ingest_age_seconds
        self._requested_path = Path(resolved)
        self._pinned = self._inspect_executable(self._requested_path)
        self._adapter = NvidiaSmiShadowAdapter(
            executable=self._pinned.resolved_path,
            runner=runner,
            which=lambda _: self._pinned.resolved_path,
        )
        self._sequences: Dict[str, int] = {}

    @staticmethod
    def _inspect_executable(path: Path) -> ExecutableProvenance:
        try:
            if path.is_symlink():
                raise GpuObservationError("nvidia-smi executable must not be a symlink")
            resolved = path.resolve(strict=True)
            information = resolved.stat()
            if not stat.S_ISREG(information.st_mode):
                raise GpuObservationError("nvidia-smi executable is not a regular file")
            mode = stat.S_IMODE(information.st_mode)
            if mode & 0o111 == 0:
                raise GpuObservationError("nvidia-smi file is not executable")
            digest = hashlib.sha256()
            with resolved.open("rb") as stream:
                for block in iter(lambda: stream.read(128 * 1024), b""):
                    digest.update(block)
        except GpuObservationError:
            raise
        except OSError as exc:
            raise GpuObservationError("cannot inspect nvidia-smi executable: {}".format(exc)) from exc
        return ExecutableProvenance(
            str(resolved), digest.hexdigest(), information.st_uid, information.st_gid, mode, False
        )

    def _require_pinned_executable(self) -> ExecutableProvenance:
        current = self._inspect_executable(self._requested_path)
        if current != self._pinned:
            raise GpuObservationError("nvidia-smi executable provenance changed")
        return current

    def _driver_versions(self) -> Dict[str, str]:
        command: Sequence[str] = (
            self._pinned.resolved_path,
            "--query-gpu=uuid,driver_version",
            "--format=csv,noheader,nounits",
        )
        try:
            result = self._runner(command, capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GpuObservationError("driver identity query failed: {}".format(exc)) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise GpuObservationError("driver identity query failed: {}".format(detail))
        versions: Dict[str, str] = {}
        for row in csv.reader(result.stdout.splitlines()):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != 2:
                raise GpuObservationError("invalid driver identity response")
            uuid, version = (value.strip() for value in row)
            if not uuid or not version:
                raise GpuObservationError("driver identity is incomplete")
            if uuid in versions:
                raise GpuObservationError("duplicate GPU UUID in driver identity response")
            versions[uuid] = version
        return versions

    def collect(self) -> Tuple[QualifiedGpuPowerObservation, ...]:
        provenance = self._require_pinned_executable()
        collected_at = self._clock()
        started = self._monotonic()
        try:
            devices = self._adapter.list_devices()
        except AdapterError as exc:
            raise GpuObservationError("GPU telemetry query failed: {}".format(exc)) from exc
        drivers = self._driver_versions()
        finished = self._monotonic()
        ingested_at = self._clock()
        final_provenance = self._require_pinned_executable()

        if provenance != final_provenance:
            raise GpuObservationError("nvidia-smi executable changed during collection")
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise GpuObservationError("collection timestamp must be timezone-aware")
        if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
            raise GpuObservationError("ingest timestamp must be timezone-aware")
        age = (ingested_at - collected_at).total_seconds()
        if age < 0 or age > self._maximum_age:
            raise GpuObservationError("GPU observation is stale or clock-regressed")
        duration_ms = (finished - started) * 1_000.0
        if not math.isfinite(duration_ms) or duration_ms < 0:
            raise GpuObservationError("command duration is invalid")
        if not devices:
            raise GpuObservationError("no NVIDIA GPUs were observed")
        device_ids = {device.device_id for device in devices}
        if set(drivers) != device_ids:
            raise GpuObservationError("driver identity does not match observed GPU UUIDs")
        if any(device.power_watts is None for device in devices):
            raise GpuObservationError("GPU power telemetry is unavailable")

        observations = []
        next_sequences = dict(self._sequences)
        for device in devices:
            sequence = next_sequences.get(device.device_id, -1) + 1
            next_sequences[device.device_id] = sequence
            observations.append(
                QualifiedGpuPowerObservation(
                    collected_at,
                    ingested_at,
                    float(device.power_watts),
                    "{}:{}".format(self.host_alias, device.device_id),
                    Quality.GOOD,
                    self.host_alias,
                    device.device_id,
                    self.source_epoch,
                    sequence,
                    provenance,
                    drivers[device.device_id],
                    duration_ms,
                )
            )
        self._sequences = next_sequences
        return tuple(observations)

