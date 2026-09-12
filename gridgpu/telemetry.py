"""Fail-closed telemetry primitives for supervisory power control.

The point-of-common-coupling (PCC) meter is authoritative for envelope
decisions.  GPU telemetry can explain or predict power, but it must never be
substituted for an unavailable meter reading.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Dict, Generic, Optional, Set, Tuple, TypeVar


class Quality(str, Enum):
    GOOD = "good"
    SUSPECT = "suspect"
    STALE = "stale"
    BAD = "bad"


class TelemetryValidationError(ValueError):
    """Raised when telemetry cannot safely support an automatic decision."""


T = TypeVar("T")


@dataclass(frozen=True)
class TelemetrySample(Generic[T]):
    timestamp_utc: datetime
    monotonic_sequence: int
    source_id: str
    value: T
    unit: str
    quality: Quality
    ingest_latency_ms: int = 0
    source_epoch: str = "initial"


@dataclass(frozen=True)
class FreshnessPolicy:
    """Freshness limits for an authoritative meter stream.

    ``max_future_skew_seconds`` permits small clock/transport differences but
    prevents future-dated samples from extending their own useful lifetime.
    """

    max_age_seconds: float = 5.0
    max_future_skew_seconds: float = 0.25
    max_ingest_latency_ms: int = 5_000

    def __post_init__(self) -> None:
        if self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        if self.max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be non-negative")
        if self.max_ingest_latency_ms < 0:
            raise ValueError("max_ingest_latency_ms must be non-negative")


@dataclass(frozen=True)
class MeterSnapshot:
    """A candidate authoritative PCC active-power observation."""

    active_power: TelemetrySample[float]
    authoritative_source_id: str
    clock_synchronized: bool = True
    minimum_watts: float = 0.0
    maximum_watts: Optional[float] = None

    @property
    def active_power_watts(self) -> float:
        """Canonical active power; bounds and control code always use watts."""

        return normalize_active_power_watts(self.active_power)


@dataclass(frozen=True)
class DecisionEligibility:
    """Result of the fail-closed precondition check."""

    eligible: bool
    reasons: Tuple[str, ...] = ()

    def require(self) -> None:
        if not self.eligible:
            raise TelemetryValidationError("; ".join(self.reasons))


@dataclass(frozen=True)
class SequenceDecision:
    accepted: bool
    reason: str = ""

    def require(self) -> None:
        if not self.accepted:
            raise TelemetryValidationError(self.reason)


@dataclass(frozen=True)
class SequenceCursor:
    source_id: str
    source_epoch: str
    last_sequence: int


class SourceSequenceReconciler:
    """Reject duplicate, regressed, or unannounced restarted meter streams.

    Sequence is scoped to ``(source_id, source_epoch)``.  A source may reset
    its sequence only after ``declare_restart_epoch`` names a new epoch.  Once
    replaced, an epoch is retired and cannot be replayed later.
    """

    def __init__(self) -> None:
        self._cursors: Dict[str, SequenceCursor] = {}
        self._pending_epochs: Dict[str, str] = {}
        self._retired_epochs: Dict[str, Set[str]] = {}

    def cursor(self, source_id: str) -> Optional[SequenceCursor]:
        return self._cursors.get(source_id)

    def declare_restart_epoch(self, source_id: str, restart_epoch: str) -> None:
        if not source_id.strip() or not restart_epoch.strip():
            raise ValueError("source_id and restart_epoch must be non-empty")
        cursor = self._cursors.get(source_id)
        if cursor is None:
            raise TelemetryValidationError("cannot restart an unseen source")
        if restart_epoch == cursor.source_epoch:
            raise TelemetryValidationError("restart epoch must differ from current epoch")
        if restart_epoch in self._retired_epochs.get(source_id, set()):
            raise TelemetryValidationError("restart epoch has already been retired")
        pending = self._pending_epochs.get(source_id)
        if pending is not None and pending != restart_epoch:
            raise TelemetryValidationError("a different restart epoch is already pending")
        self._pending_epochs[source_id] = restart_epoch

    def assess(self, sample: TelemetrySample[object]) -> SequenceDecision:
        if not sample.source_id.strip():
            return SequenceDecision(False, "source_id is empty")
        if not sample.source_epoch.strip():
            return SequenceDecision(False, "source_epoch is empty")
        if sample.monotonic_sequence < 0:
            return SequenceDecision(False, "sequence must be non-negative")

        cursor = self._cursors.get(sample.source_id)
        if cursor is None:
            return SequenceDecision(True)
        if sample.source_epoch == cursor.source_epoch:
            if sample.monotonic_sequence == cursor.last_sequence:
                return SequenceDecision(False, "duplicate sequence")
            if sample.monotonic_sequence < cursor.last_sequence:
                return SequenceDecision(False, "sequence regression")
            return SequenceDecision(True)

        if sample.source_epoch in self._retired_epochs.get(sample.source_id, set()):
            return SequenceDecision(False, "source epoch is retired")
        if self._pending_epochs.get(sample.source_id) != sample.source_epoch:
            return SequenceDecision(False, "source epoch changed without declared restart")
        return SequenceDecision(True)

    def accept(self, sample: TelemetrySample[object]) -> SequenceCursor:
        decision = self.assess(sample)
        decision.require()
        previous = self._cursors.get(sample.source_id)
        if previous is not None and previous.source_epoch != sample.source_epoch:
            self._retired_epochs.setdefault(sample.source_id, set()).add(previous.source_epoch)
            del self._pending_epochs[sample.source_id]
        cursor = SequenceCursor(sample.source_id, sample.source_epoch, sample.monotonic_sequence)
        self._cursors[sample.source_id] = cursor
        return cursor


def normalize_active_power_watts(sample: TelemetrySample[object]) -> float:
    """Convert the supported meter units to finite watts without ambiguity."""

    if isinstance(sample.value, bool) or not isinstance(sample.value, (int, float)):
        raise TelemetryValidationError("active power value must be numeric")
    value = float(sample.value)
    if not math.isfinite(value):
        raise TelemetryValidationError("active power value must be finite")
    if sample.unit == "W":
        watts = value
    elif sample.unit == "kW":
        watts = value * 1_000.0
    else:
        raise TelemetryValidationError("active power unit must be W or kW")
    if not math.isfinite(watts):
        raise TelemetryValidationError("normalized active power must be finite")
    return watts


def _utc_age_seconds(timestamp: datetime, now_utc: datetime) -> float:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TelemetryValidationError("meter timestamp must be timezone-aware")
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return (now_utc.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()


def assess_meter_decision_eligibility(
    snapshot: MeterSnapshot,
    now_utc: datetime,
    policy: FreshnessPolicy = FreshnessPolicy(),
) -> DecisionEligibility:
    """Validate whether ``snapshot`` may drive an automatic control decision.

    The check intentionally accumulates reasons for operators while remaining
    fail-closed: only a fully valid, current, GOOD sample from the configured
    authoritative source is eligible.
    """

    sample = snapshot.active_power
    reasons = []

    if not snapshot.authoritative_source_id.strip():
        reasons.append("authoritative meter source is not configured")
    if sample.source_id != snapshot.authoritative_source_id:
        reasons.append("sample is not from the authoritative meter")
    if sample.quality is not Quality.GOOD:
        reasons.append("meter quality is not GOOD")
    if not snapshot.clock_synchronized:
        reasons.append("meter clock is not synchronized")
    if sample.monotonic_sequence < 0:
        reasons.append("meter sequence must be non-negative")
    if not sample.source_epoch.strip():
        reasons.append("meter source_epoch is empty")
    if not sample.source_id.strip():
        reasons.append("meter source_id is empty")
    if sample.unit not in ("W", "kW"):
        reasons.append("active power unit must be W or kW")
    if sample.ingest_latency_ms < 0:
        reasons.append("ingest latency must be non-negative")
    elif sample.ingest_latency_ms > policy.max_ingest_latency_ms:
        reasons.append("meter ingest latency exceeds policy")

    try:
        watts = normalize_active_power_watts(sample)
    except TelemetryValidationError as exc:
        reasons.append(str(exc))
    else:
        if watts < snapshot.minimum_watts:
            reasons.append("active power is below the configured minimum")
        elif snapshot.maximum_watts is not None and watts > snapshot.maximum_watts:
            reasons.append("active power is above the configured maximum")

    try:
        age = _utc_age_seconds(sample.timestamp_utc, now_utc)
    except TelemetryValidationError as exc:
        reasons.append(str(exc))
    else:
        if age > policy.max_age_seconds:
            reasons.append("meter sample is stale")
        elif age < -policy.max_future_skew_seconds:
            reasons.append("meter sample is too far in the future")

    return DecisionEligibility(not reasons, tuple(reasons))


def validate_authoritative_meter_snapshot(
    snapshot: MeterSnapshot,
    now_utc: datetime,
    policy: FreshnessPolicy = FreshnessPolicy(),
) -> MeterSnapshot:
    """Return a valid authoritative snapshot or raise, never degrade silently."""

    assess_meter_decision_eligibility(snapshot, now_utc, policy).require()
    return snapshot
