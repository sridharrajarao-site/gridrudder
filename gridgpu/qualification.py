"""Read-only NVIDIA/BMC qualification collection for an attended lab.

There are no write commands in this module. Command execution is argv-only and
restricted to pinned executables and explicit read-only queries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Callable, Optional, Sequence

from .alignment import (
    AlignmentPolicy, AlignmentReport, GpuPowerObservation, HostOverheadModel,
    ValidatedGpuObservation, ValidatedMeterObservation, align_power_signals,
    validate_gpu_for_alignment, validate_meter_for_alignment,
)
from .gpu_observer import ExecutableProvenance, NvidiaPowerObserver, QualifiedGpuPowerObservation
from .meter import MeterObservation, MeterProvenance
from .telemetry import FreshnessPolicy, MeterSnapshot, Quality, TelemetrySample


class QualificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BmcCollection:
    observation: MeterObservation
    chassis_id: str
    fru_response_sha256: str
    power_response_sha256: str
    executable: ExecutableProvenance


def inspect_pinned_executable(path: Path, required_owner_uid: int = 0) -> ExecutableProvenance:
    """Inspect a fixed executable without following a caller-visible symlink."""

    try:
        if not path.is_absolute() or path.is_symlink():
            raise QualificationError("executable must be an absolute non-symlink path")
        resolved = path.resolve(strict=True)
        information = resolved.stat()
        if not stat.S_ISREG(information.st_mode) or stat.S_IMODE(information.st_mode) & 0o111 == 0:
            raise QualificationError("executable must be a regular executable file")
        if information.st_uid != required_owner_uid:
            raise QualificationError("executable owner does not match the required trusted uid")
        if stat.S_IMODE(information.st_mode) & 0o022:
            raise QualificationError("trusted executable must not be group/world writable")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(128 * 1024), b""):
                digest.update(block)
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError(f"cannot inspect executable: {exc}") from exc
    return ExecutableProvenance(str(resolved), digest.hexdigest(), information.st_uid,
                                information.st_gid, stat.S_IMODE(information.st_mode), False)


class BmcPowerObserver:
    """Pinned, read-only local IPMI DCMI collector with FRU chassis binding."""

    _WATTS = re.compile(r"Instantaneous power reading:\s*([0-9]+(?:\.[0-9]+)?)\s+Watts")
    _SERIAL = re.compile(r"^(?:Chassis|Product) Serial\s*:\s*(\S.*?)\s*$", re.MULTILINE)

    def __init__(
        self, *, host_id: str, expected_chassis_id: str, meter_id: str,
        physical_boundary: str, source_epoch: str, executable: Path,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        required_owner_uid: int = 0,
        clock_synchronized: bool = False,
    ) -> None:
        identities = (host_id, expected_chassis_id, meter_id, physical_boundary, source_epoch)
        if any(not value.strip() for value in identities):
            raise ValueError("host, chassis, meter, boundary, and epoch identities are required")
        self.host_id = host_id
        self.expected_chassis_id = expected_chassis_id
        self.meter_id = meter_id
        self.physical_boundary = physical_boundary
        self.source_epoch = source_epoch
        self.provenance = inspect_pinned_executable(executable, required_owner_uid)
        self._path = Path(self.provenance.resolved_path)
        self._runner = runner
        self._clock = clock
        self._monotonic = monotonic
        self._required_owner_uid = required_owner_uid
        self._clock_synchronized = clock_synchronized
        self._sequence = 0

    def _run_read(self, args: Sequence[str], description: str) -> str:
        if inspect_pinned_executable(self._path, self._required_owner_uid) != self.provenance:
            raise QualificationError("BMC executable provenance changed")
        command = (self.provenance.resolved_path, *args)
        try:
            result = self._runner(command, capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise QualificationError(f"{description} failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise QualificationError(f"{description} failed: {detail}")
        if inspect_pinned_executable(self._path, self._required_owner_uid) != self.provenance:
            raise QualificationError("BMC executable provenance changed during collection")
        return result.stdout

    def collect(self) -> BmcCollection:
        collected_at = self._clock()
        started = self._monotonic()
        fru = self._run_read(("fru", "print", "0"), "BMC chassis identity query")
        readings = self._run_read(("dcmi", "power", "reading"), "BMC DCMI power query")
        finished = self._monotonic()
        ingested_at = self._clock()
        if any(value.tzinfo is None or value.utcoffset() is None for value in (collected_at, ingested_at)):
            raise QualificationError("BMC timestamps must be timezone-aware")
        if ingested_at < collected_at or finished < started:
            raise QualificationError("BMC clock regressed")
        serials = {value.strip() for value in self._SERIAL.findall(fru)}
        if self.expected_chassis_id not in serials:
            raise QualificationError("BMC FRU identity does not match the expected chassis")
        match = self._WATTS.search(readings)
        if match is None:
            raise QualificationError("BMC response contains no instantaneous watts")
        watts = float(match.group(1))
        if not math.isfinite(watts) or watts < 0:
            raise QualificationError("BMC watts are invalid")
        source_id = f"{self.host_id}:{self.meter_id}"
        latency_ms = int(round((finished - started) * 1000.0))
        sample = TelemetrySample(collected_at, self._sequence, source_id, watts, "W",
                                 Quality.GOOD, latency_ms, self.source_epoch)
        snapshot = MeterSnapshot(sample, source_id, self._clock_synchronized, 0.0, None)
        observation = MeterObservation(snapshot, ingested_at, MeterProvenance(
            self.physical_boundary, self.meter_id,
            f"ipmi-dcmi:{self.provenance.sha256}", "live-read-only", self.provenance.resolved_path,
        ))
        self._sequence += 1
        return BmcCollection(observation, self.expected_chassis_id,
            hashlib.sha256(fru.encode("utf-8")).hexdigest(),
            hashlib.sha256(readings.encode("utf-8")).hexdigest(), self.provenance)


@dataclass(frozen=True)
class ReadOnlyQualificationPacket:
    host_id: str
    chassis_id: str
    gpu_uuid: str
    meter_id: str
    nvidia_executable_sha256: str
    bmc_executable_sha256: str
    bmc_evidence: tuple[BmcCollection, ...]
    meter_observations: tuple[ValidatedMeterObservation, ...]
    gpu_observations: tuple[ValidatedGpuObservation, ...]
    alignment: AlignmentReport
    qualified: bool


def qualification_packet_document(packet: ReadOnlyQualificationPacket) -> dict:
    """Return canonical-JSON-safe evidence plus a digest over the complete body."""

    def normalize(value):
        if is_dataclass(value):
            return normalize(asdict(value))
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [normalize(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        return value

    body = normalize(packet)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"schema": "gridrudder-read-only-qualification:v1", "packet": body,
            "packet_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def _to_alignment_gpu(observation: QualifiedGpuPowerObservation, meter_id: str,
                      clock_synchronized: bool) -> GpuPowerObservation:
    return GpuPowerObservation(
        observation.timestamp_utc, observation.ingested_at_utc, observation.watts,
        observation.source_id, observation.quality, observation.host_alias, meter_id,
        observation.source_epoch, observation.monotonic_sequence, clock_synchronized,
        f"nvidia-smi:{observation.executable.sha256}:driver:{observation.driver_version}",
    )


def collect_read_only_qualification(
    *, host_id: str, chassis_id: str, gpu_uuid: str, meter_id: str,
    expected_physical_boundary: str, gpu_observer: NvidiaPowerObserver,
    bmc_observer: BmcPowerObserver, samples: int, overhead_model: HostOverheadModel,
    alignment_policy: AlignmentPolicy = AlignmentPolicy(),
    freshness_policy: FreshnessPolicy = FreshnessPolicy(),
    clock_synchronized: bool = False,
    sleeper: Callable[[float], None] = time.sleep, sample_interval_seconds: float = 1.0,
    trusted_nvidia_owner_uid: int = 0,
) -> ReadOnlyQualificationPacket:
    """Collect and validate a bound packet; never issue a write command."""

    if samples < 3 or not math.isfinite(sample_interval_seconds) or sample_interval_seconds < 0:
        raise ValueError("qualification requires at least three samples and a valid interval")
    if gpu_observer.host_alias != host_id or bmc_observer.host_id != host_id:
        raise QualificationError("collectors are not bound to the requested host")
    if (bmc_observer.expected_chassis_id != chassis_id or bmc_observer.meter_id != meter_id or
            bmc_observer.physical_boundary != expected_physical_boundary):
        raise QualificationError("BMC collector identity does not match qualification scope")
    meters = []
    gpus = []
    bmc_evidence = []
    nvidia_hash: Optional[str] = None
    for index in range(samples):
        bmc = bmc_observer.collect()
        meter = bmc.observation
        gpu_matches = [item for item in gpu_observer.collect() if item.gpu_uuid == gpu_uuid]
        if len(gpu_matches) != 1:
            raise QualificationError("expected GPU UUID is not uniquely observable")
        gpu = gpu_matches[0]
        if (gpu.executable.owner_uid != trusted_nvidia_owner_uid or gpu.executable.is_symlink or
                gpu.executable.mode & 0o022 or
                not Path(gpu.executable.resolved_path).is_absolute()):
            raise QualificationError("NVIDIA executable provenance is not trusted")
        if nvidia_hash is None:
            nvidia_hash = gpu.executable.sha256
        elif nvidia_hash != gpu.executable.sha256:
            raise QualificationError("NVIDIA executable provenance changed across samples")
        meters.append(validate_meter_for_alignment(meter, host_id=host_id,
            expected_physical_boundary=expected_physical_boundary,
            freshness_policy=freshness_policy))
        gpus.append(validate_gpu_for_alignment(_to_alignment_gpu(
            gpu, meter_id, clock_synchronized)))
        bmc_evidence.append(bmc)
        if index + 1 < samples:
            sleeper(sample_interval_seconds)
    report = align_power_signals(meters, gpus, overhead_model, alignment_policy)
    return ReadOnlyQualificationPacket(host_id, chassis_id, gpu_uuid, meter_id,
        nvidia_hash or "", bmc_observer.provenance.sha256, tuple(bmc_evidence),
        tuple(meters), tuple(gpus),
        report, report.accepted)
