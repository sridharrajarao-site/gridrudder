"""Validated physical-boundary alignment of meter and accelerator power."""

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable, Tuple

from .meter import MeterObservation
from .telemetry import FreshnessPolicy, Quality, validate_authoritative_meter_snapshot


@dataclass(frozen=True)
class GpuPowerObservation:
    timestamp_utc: datetime
    ingested_at_utc: datetime
    watts: float
    source_id: str
    quality: Quality
    host_id: str
    bound_meter_id: str
    source_epoch: str
    monotonic_sequence: int
    clock_synchronized: bool
    provenance: str


@dataclass(frozen=True)
class AlignmentValidationToken:
    signal_type: str
    host_id: str
    meter_id: str
    source_id: str
    source_epoch: str
    physical_boundary: str
    validator_id: str = "gridgpu-alignment-validator:v1"


@dataclass(frozen=True)
class ValidatedMeterObservation:
    observation: MeterObservation
    token: AlignmentValidationToken


@dataclass(frozen=True)
class ValidatedGpuObservation:
    observation: GpuPowerObservation
    token: AlignmentValidationToken


def _aware(timestamp: datetime) -> bool:
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def validate_meter_for_alignment(
    observation: MeterObservation,
    *,
    host_id: str,
    expected_physical_boundary: str,
    freshness_policy: FreshnessPolicy = FreshnessPolicy(),
) -> ValidatedMeterObservation:
    if not host_id.strip() or not expected_physical_boundary.strip():
        raise ValueError("host and expected physical boundary are required")
    if observation.provenance.physical_boundary != expected_physical_boundary:
        raise ValueError("meter physical boundary does not match expected boundary")
    validate_authoritative_meter_snapshot(
        observation.snapshot, observation.ingested_at_utc, freshness_policy
    )
    sample = observation.snapshot.active_power
    token = AlignmentValidationToken(
        "meter", host_id, observation.provenance.meter_id, sample.source_id,
        sample.source_epoch, observation.provenance.physical_boundary,
    )
    return ValidatedMeterObservation(observation, token)


def validate_gpu_for_alignment(observation: GpuPowerObservation) -> ValidatedGpuObservation:
    if any(not value.strip() for value in (
        observation.source_id, observation.host_id, observation.bound_meter_id,
        observation.source_epoch, observation.provenance,
    )):
        raise ValueError("GPU identity, binding, epoch, and provenance are required")
    if not _aware(observation.timestamp_utc) or not _aware(observation.ingested_at_utc):
        raise ValueError("GPU timestamps must be timezone-aware")
    if observation.quality is not Quality.GOOD or not observation.clock_synchronized:
        raise ValueError("GPU source quality and clock must be validated")
    if observation.monotonic_sequence < 0:
        raise ValueError("GPU sequence must be non-negative")
    if not math.isfinite(observation.watts) or observation.watts < 0:
        raise ValueError("GPU power must be finite and non-negative")
    token = AlignmentValidationToken(
        "gpu", observation.host_id, observation.bound_meter_id,
        observation.source_id, observation.source_epoch, "gpu-board-sum",
    )
    return ValidatedGpuObservation(observation, token)


@dataclass(frozen=True)
class HostOverheadModel:
    fixed_watts: float
    dynamic_fraction_of_gpu_power: float
    minimum_boundary_delta_watts: float
    maximum_boundary_delta_watts: float
    calibration_id: str

    def __post_init__(self) -> None:
        values = (
            self.fixed_watts, self.dynamic_fraction_of_gpu_power,
            self.minimum_boundary_delta_watts, self.maximum_boundary_delta_watts,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("overhead calibration values must be finite")
        if self.fixed_watts < 0 or self.dynamic_fraction_of_gpu_power < 0:
            raise ValueError("expected overhead must be non-negative")
        if self.minimum_boundary_delta_watts > self.maximum_boundary_delta_watts:
            raise ValueError("overhead calibration bounds are reversed")
        if not self.calibration_id.strip():
            raise ValueError("calibration identity is required")

    def expected_watts(self, gpu_watts: float) -> float:
        return self.fixed_watts + self.dynamic_fraction_of_gpu_power * gpu_watts


@dataclass(frozen=True)
class AlignmentPolicy:
    maximum_skew_seconds: float = 1.0
    minimum_coverage: float = 0.90
    maximum_observation_age_seconds: float = 5.0
    maximum_ingest_latency_ms: float = 5_000.0

    def __post_init__(self) -> None:
        values = (
            self.maximum_skew_seconds,
            self.minimum_coverage,
            self.maximum_observation_age_seconds,
            self.maximum_ingest_latency_ms,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("alignment policy values must be finite numbers")
        if self.maximum_skew_seconds <= 0:
            raise ValueError("maximum_skew_seconds must be positive")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError("minimum_coverage must be in [0, 1]")
        if self.maximum_observation_age_seconds < 0 or self.maximum_ingest_latency_ms < 0:
            raise ValueError("age and latency limits must be non-negative")


@dataclass(frozen=True)
class AlignedObservation:
    meter_timestamp_utc: datetime
    gpu_timestamp_utc: datetime
    meter_watts: float
    gpu_watts: float
    boundary_delta_watts: float
    expected_host_overhead_watts: float
    overhead_deviation_watts: float
    overhead_within_calibration_bounds: bool
    skew_seconds: float
    meter_ingest_latency_ms: float
    gpu_ingest_latency_ms: float


@dataclass(frozen=True)
class AlignmentReport:
    accepted: bool
    reasons: Tuple[str, ...]
    pairs: Tuple[AlignedObservation, ...]
    meter_count: int
    gpu_count: int
    coverage: float
    mean_latency_ms: float
    maximum_skew_seconds: float
    mean_boundary_delta_watts: float
    mean_expected_host_overhead_watts: float
    mean_absolute_overhead_deviation_watts: float
    temporal_confidence: float
    data_quality_confidence: float


def _ordered_stream_valid(tokens, sequences) -> bool:
    return (
        len({token.source_id for token in tokens}) == 1
        and len({token.source_epoch for token in tokens}) == 1
        and all(later > earlier for earlier, later in zip(sequences, sequences[1:]))
    )


def align_power_signals(
    meter_observations: Iterable[ValidatedMeterObservation],
    gpu_observations: Iterable[ValidatedGpuObservation],
    overhead_model: HostOverheadModel,
    policy: AlignmentPolicy = AlignmentPolicy(),
) -> AlignmentReport:
    meters = tuple(meter_observations)
    gpus = tuple(gpu_observations)
    reasons = []
    if any(not isinstance(item, ValidatedMeterObservation) for item in meters) or any(
        not isinstance(item, ValidatedGpuObservation) for item in gpus
    ):
        reasons.append("only explicitly validated observations are accepted")
        return _empty_report(reasons, len(meters), len(gpus))
    if not meters or not gpus:
        reasons.append("both validated meter and GPU evidence are required")
        return _empty_report(reasons, len(meters), len(gpus))

    meter_hosts = {item.token.host_id for item in meters}
    gpu_hosts = {item.token.host_id for item in gpus}
    meter_ids = {item.token.meter_id for item in meters}
    gpu_meter_ids = {item.token.meter_id for item in gpus}
    if len(meter_hosts) != 1 or meter_hosts != gpu_hosts:
        reasons.append("GPU and meter observations are not bound to the same host")
    if len(meter_ids) != 1 or meter_ids != gpu_meter_ids:
        reasons.append("GPU observations are not bound to the authoritative meter")
    if any(item.token.meter_id != item.observation.provenance.meter_id for item in meters):
        reasons.append("meter token contradicts provenance")
    for item in meters:
        sample = item.observation.snapshot.active_power
        if (
            item.token.signal_type != "meter"
            or item.token.validator_id != "gridgpu-alignment-validator:v1"
            or item.token.source_id != sample.source_id
            or item.token.source_epoch != sample.source_epoch
            or item.token.physical_boundary != item.observation.provenance.physical_boundary
        ):
            reasons.append("meter validation token contradicts observation")
        try:
            validate_authoritative_meter_snapshot(
                item.observation.snapshot,
                item.observation.ingested_at_utc,
                FreshnessPolicy(
                    max_age_seconds=policy.maximum_observation_age_seconds,
                    max_ingest_latency_ms=int(policy.maximum_ingest_latency_ms),
                ),
            )
        except (ValueError, RuntimeError):
            reasons.append("meter observation no longer passes authoritative validation")
    for item in gpus:
        observation = item.observation
        if (
            item.token.signal_type != "gpu"
            or item.token.validator_id != "gridgpu-alignment-validator:v1"
            or item.token.source_id != observation.source_id
            or item.token.source_epoch != observation.source_epoch
            or item.token.host_id != observation.host_id
            or item.token.meter_id != observation.bound_meter_id
        ):
            reasons.append("GPU validation token contradicts observation")

    meters = tuple(sorted(meters, key=lambda item: item.observation.timestamp_utc))
    gpus = tuple(sorted(gpus, key=lambda item: item.observation.timestamp_utc))
    if not _ordered_stream_valid(
        [item.token for item in meters],
        [item.observation.snapshot.active_power.monotonic_sequence for item in meters],
    ):
        reasons.append("meter source/epoch/sequence stream is invalid")
    if not _ordered_stream_valid(
        [item.token for item in gpus], [item.observation.monotonic_sequence for item in gpus]
    ):
        reasons.append("GPU source/epoch/sequence stream is invalid")

    stale = False
    for item in meters:
        observation = item.observation
        age = (observation.ingested_at_utc - observation.timestamp_utc).total_seconds()
        sample = observation.snapshot.active_power
        stale |= sample.quality is not Quality.GOOD or not observation.snapshot.clock_synchronized or age < 0 or age > policy.maximum_observation_age_seconds
    for item in gpus:
        observation = item.observation
        age = (observation.ingested_at_utc - observation.timestamp_utc).total_seconds()
        stale |= observation.quality is not Quality.GOOD or not observation.clock_synchronized or age < 0 or age > policy.maximum_observation_age_seconds
    if stale:
        reasons.append("stale, unsynchronized, or non-GOOD evidence is present")

    unused = set(range(len(gpus)))
    pairs = []
    for meter_item in meters:
        if not unused:
            break
        meter = meter_item.observation
        candidate = min(unused, key=lambda index: (
            abs((gpus[index].observation.timestamp_utc - meter.timestamp_utc).total_seconds()), index
        ))
        gpu = gpus[candidate].observation
        skew = abs((gpu.timestamp_utc - meter.timestamp_utc).total_seconds())
        if skew > policy.maximum_skew_seconds:
            continue
        unused.remove(candidate)
        boundary_delta = meter.watts - gpu.watts
        expected = overhead_model.expected_watts(gpu.watts)
        pairs.append(AlignedObservation(
            meter.timestamp_utc, gpu.timestamp_utc, meter.watts, gpu.watts,
            boundary_delta, expected, boundary_delta - expected,
            overhead_model.minimum_boundary_delta_watts <= boundary_delta <= overhead_model.maximum_boundary_delta_watts,
            skew,
            (meter.ingested_at_utc - meter.timestamp_utc).total_seconds() * 1000.0,
            (gpu.ingested_at_utc - gpu.timestamp_utc).total_seconds() * 1000.0,
        ))

    coverage = len(pairs) / max(len(meters), len(gpus), 1)
    if coverage < policy.minimum_coverage:
        reasons.append("aligned coverage is insufficient")
    if not pairs:
        reasons.append("signals are temporally misaligned")
    latencies = [value for pair in pairs for value in (pair.meter_ingest_latency_ms, pair.gpu_ingest_latency_ms)]
    if any(value > policy.maximum_ingest_latency_ms for value in latencies):
        reasons.append("ingest latency exceeds policy")
    if any(not pair.overhead_within_calibration_bounds for pair in pairs):
        reasons.append("host boundary delta is outside calibrated overhead bounds")

    maximum_skew = max((pair.skew_seconds for pair in pairs), default=0.0)
    temporal_confidence = coverage * max(0.0, 1.0 - maximum_skew / policy.maximum_skew_seconds)
    data_quality_confidence = 0.0 if stale or reasons and not pairs else (1.0 if pairs else 0.0)
    deltas = [pair.boundary_delta_watts for pair in pairs]
    expected = [pair.expected_host_overhead_watts for pair in pairs]
    deviations = [abs(pair.overhead_deviation_watts) for pair in pairs]
    return AlignmentReport(
        not reasons, tuple(dict.fromkeys(reasons)), tuple(pairs), len(meters), len(gpus), coverage,
        sum(latencies) / len(latencies) if latencies else 0.0, maximum_skew,
        sum(deltas) / len(deltas) if deltas else 0.0,
        sum(expected) / len(expected) if expected else 0.0,
        sum(deviations) / len(deviations) if deviations else 0.0,
        temporal_confidence, data_quality_confidence,
    )


def _empty_report(reasons, meter_count, gpu_count):
    return AlignmentReport(False, tuple(reasons), (), meter_count, gpu_count, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
