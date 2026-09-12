"""Approval-gated supervisory control-session state machine.

This module authorizes and records intent; it has no hardware or scheduler
adapter and therefore cannot actuate a device.  Its emitted events are shaped
for direct use as hash-chained audit-log inputs.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from .telemetry import (
    FreshnessPolicy,
    MeterSnapshot,
    assess_meter_decision_eligibility,
)


class SessionState(str, Enum):
    OBSERVE = "observe"
    SUPERVISED = "supervised"
    SAFE_HOLD = "safe_hold"
    RECOVERY = "recovery"


class SessionError(RuntimeError):
    pass


class AuthorizationError(SessionError):
    pass


class ApprovalRequired(SessionError):
    pass


class ExpiredProposal(SessionError):
    pass


class IdempotencyConflict(SessionError):
    pass


class HistoryReplayError(SessionError):
    pass


@dataclass(frozen=True)
class EnvelopeProposal:
    proposal_id: str
    max_facility_watts: float
    effective_at: datetime
    expires_at: datetime
    reason: str
    policy_id: str

    def __post_init__(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("proposal_id must be non-empty")
        if self.max_facility_watts <= 0:
            raise ValueError("max_facility_watts must be positive")
        if not self.reason.strip() or not self.policy_id.strip():
            raise ValueError("reason and policy_id must be non-empty")
        _require_aware(self.effective_at, "effective_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be after effective_at")


@dataclass(frozen=True)
class Approval:
    approval_id: str
    proposal_id: str
    approver: str
    approved_at: datetime


@dataclass(frozen=True)
class SessionEvent:
    event_type: str
    actor: str
    timestamp: str
    payload: dict

    def audit_arguments(self) -> Tuple[str, dict, str, str]:
        """Return ``event_type, payload, actor, timestamp`` for AuditLog.append."""
        return self.event_type, self.payload, self.actor, self.timestamp


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(field))


def _timestamp(value: datetime) -> str:
    _require_aware(value, "timestamp")
    return value.isoformat()


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HistoryReplayError("{} must be a non-empty string".format(field))
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
        _require_aware(parsed, field)
    except ValueError as exc:
        raise HistoryReplayError("{} is invalid: {}".format(field, exc)) from exc
    return parsed


def _required_string(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HistoryReplayError("{} must be a non-empty string".format(field))
    return value


def _required_number(mapping: Mapping[str, object], field: str) -> float:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HistoryReplayError("{} must be numeric".format(field))
    normalized = float(value)
    if not math.isfinite(normalized):
        raise HistoryReplayError("{} must be finite".format(field))
    return normalized


class ControlSession:
    """Pure state machine for a single supervised envelope at a time."""

    def __init__(
        self,
        authorized_approvers: FrozenSet[str],
        freshness_policy: FreshnessPolicy = FreshnessPolicy(),
    ) -> None:
        if not authorized_approvers or any(not identity.strip() for identity in authorized_approvers):
            raise ValueError("at least one non-empty authorized approver is required")
        self.authorized_approvers = authorized_approvers
        self.freshness_policy = freshness_policy
        self.state = SessionState.OBSERVE
        self.proposal: Optional[EnvelopeProposal] = None
        self.approval: Optional[Approval] = None
        self.events: List[SessionEvent] = []
        self._proposals: Dict[str, EnvelopeProposal] = {}
        self._approvals: Dict[str, Approval] = {}
        self._executions: Dict[str, Tuple[str, SessionEvent]] = {}

    @property
    def authorized_execution_count(self) -> int:
        return len(self._executions)

    @classmethod
    def reconstruct_for_operator_resume(
        cls,
        events: Iterable[SessionEvent],
        *,
        authorized_approvers: FrozenSet[str],
        now: datetime,
        freshness_policy: FreshnessPolicy = FreshnessPolicy(),
        actor: str = "system:session-recovery",
    ) -> "ControlSession":
        """Rebuild proposal/approval evidence, but never replay execution."""

        _require_aware(now, "now")
        retained = tuple(events)
        if not retained:
            raise HistoryReplayError("session history is empty")
        session = cls(authorized_approvers, freshness_policy)
        previous_time: Optional[datetime] = None
        proposal: Optional[EnvelopeProposal] = None
        approval: Optional[Approval] = None
        execution_ids = set()

        for index, event in enumerate(retained):
            if not isinstance(event, SessionEvent):
                raise HistoryReplayError("history item {} is not a SessionEvent".format(index))
            if not event.event_type.strip() or not event.actor.strip():
                raise HistoryReplayError("history item {} has invalid type or actor".format(index))
            if not isinstance(event.payload, Mapping):
                raise HistoryReplayError("history item {} payload is not a mapping".format(index))
            event_time = _parse_timestamp(event.timestamp, "history item {} timestamp".format(index))
            if event_time > now:
                raise HistoryReplayError("history contains a future event")
            if previous_time is not None and event_time < previous_time:
                raise HistoryReplayError("history timestamps are out of order")
            previous_time = event_time

            if event.event_type == "envelope_proposed":
                if index != 0 or proposal is not None:
                    raise HistoryReplayError("proposal is duplicated or out of order")
                raw = event.payload.get("proposal")
                if not isinstance(raw, Mapping):
                    raise HistoryReplayError("proposal payload is missing")
                try:
                    proposal = EnvelopeProposal(
                        _required_string(raw, "proposal_id"),
                        _required_number(raw, "max_facility_watts"),
                        _parse_timestamp(_required_string(raw, "effective_at"), "proposal effective_at"),
                        _parse_timestamp(_required_string(raw, "expires_at"), "proposal expires_at"),
                        _required_string(raw, "reason"),
                        _required_string(raw, "policy_id"),
                    )
                except (TypeError, ValueError) as exc:
                    raise HistoryReplayError("invalid proposal: {}".format(exc)) from exc
                if event_time >= proposal.expires_at:
                    raise HistoryReplayError("proposal event occurred after proposal expiry")
                if event.payload.get("previous_state") != SessionState.OBSERVE.value:
                    raise HistoryReplayError("proposal previous state is invalid")
                if event.payload.get("state") != SessionState.SUPERVISED.value:
                    raise HistoryReplayError("proposal state is invalid")
            elif event.event_type == "envelope_approved":
                if proposal is None or approval is not None:
                    raise HistoryReplayError("approval is duplicated or out of order")
                if event.actor not in authorized_approvers:
                    raise HistoryReplayError("approval actor is not authorized")
                proposal_id = _required_string(event.payload, "proposal_id")
                if proposal_id != proposal.proposal_id:
                    raise HistoryReplayError("approval references a conflicting proposal")
                if event.payload.get("policy_id") != proposal.policy_id:
                    raise HistoryReplayError("approval policy conflicts with proposal")
                if event_time >= proposal.expires_at:
                    raise HistoryReplayError("approval occurred after proposal expiry")
                approval = Approval(
                    _required_string(event.payload, "approval_id"), proposal_id, event.actor, event_time
                )
            elif event.event_type == "execution_authorized":
                if proposal is None or approval is None:
                    raise HistoryReplayError("execution authorization precedes approval")
                execution_id = _required_string(event.payload, "execution_id")
                if execution_id in execution_ids:
                    raise HistoryReplayError("execution authorization is duplicated")
                execution_ids.add(execution_id)
                if event.payload.get("proposal_id") != proposal.proposal_id:
                    raise HistoryReplayError("execution references a conflicting proposal")
                if event.payload.get("approval_id") != approval.approval_id:
                    raise HistoryReplayError("execution references a conflicting approval")
                if event.payload.get("approved_by") != approval.approver:
                    raise HistoryReplayError("execution approver conflicts with approval")
                if event.payload.get("policy_id") != proposal.policy_id:
                    raise HistoryReplayError("execution policy conflicts with proposal")
                if _required_number(event.payload, "max_facility_watts") != proposal.max_facility_watts:
                    raise HistoryReplayError("execution envelope conflicts with proposal")
                if event.payload.get("intent_only") is not True:
                    raise HistoryReplayError("execution record is not intent-only")
                if event_time < proposal.effective_at or event_time >= proposal.expires_at:
                    raise HistoryReplayError("execution authorization is outside proposal lifetime")
            else:
                raise HistoryReplayError("unsupported session history event: {}".format(event.event_type))

        if proposal is None or approval is None:
            raise HistoryReplayError("history is incomplete: proposal and approval are required")
        session.proposal = proposal
        session.approval = approval
        session._proposals[proposal.proposal_id] = proposal
        session._approvals[approval.approval_id] = approval
        session.events = list(retained)
        session.state = SessionState.SAFE_HOLD
        session._emit(
            "session_reconstructed",
            actor,
            now,
            {
                "proposal_id": proposal.proposal_id,
                "approval_id": approval.approval_id,
                "retained_execution_authorizations": len(execution_ids),
                "replayed_execution_commands": 0,
                "operator_resume_required": True,
                "proposal_expired": now >= proposal.expires_at,
                "state": session.state.value,
            },
        )
        return session

    def _emit(self, event_type: str, actor: str, now: datetime, payload: dict) -> SessionEvent:
        if not actor.strip():
            raise ValueError("actor must be non-empty")
        event = SessionEvent(event_type, actor, _timestamp(now), payload)
        self.events.append(event)
        return event

    def propose(self, proposal: EnvelopeProposal, *, actor: str, now: datetime) -> SessionEvent:
        _require_aware(now, "now")
        existing = self._proposals.get(proposal.proposal_id)
        if existing is not None:
            if existing != proposal:
                raise IdempotencyConflict("proposal_id was reused with different content")
            return self._emit(
                "envelope_proposal_duplicate",
                actor,
                now,
                {"proposal_id": proposal.proposal_id, "state": self.state.value},
            )
        if now >= proposal.expires_at:
            raise ExpiredProposal("proposal is already expired")
        if self.state is not SessionState.OBSERVE:
            raise SessionError("new proposal requires OBSERVE state")
        self._proposals[proposal.proposal_id] = proposal
        self.proposal = proposal
        self.approval = None
        previous = self.state
        self.state = SessionState.SUPERVISED
        return self._emit(
            "envelope_proposed",
            actor,
            now,
            {
                "proposal": {
                    **asdict(proposal),
                    "effective_at": _timestamp(proposal.effective_at),
                    "expires_at": _timestamp(proposal.expires_at),
                },
                "previous_state": previous.value,
                "state": self.state.value,
            },
        )

    def approve(
        self,
        proposal_id: str,
        *,
        approval_id: str,
        approver: str,
        now: datetime,
    ) -> SessionEvent:
        _require_aware(now, "now")
        if approver not in self.authorized_approvers:
            raise AuthorizationError("approver is not authorized")
        if not approval_id.strip():
            raise ValueError("approval_id must be non-empty")
        approval = Approval(approval_id, proposal_id, approver, now)
        existing = self._approvals.get(approval_id)
        if existing is not None:
            # Retry time is transport metadata, not part of the idempotent
            # approval intent. The original approval time remains authoritative.
            if existing.proposal_id != proposal_id or existing.approver != approver:
                raise IdempotencyConflict("approval_id was reused with different content")
            return self._emit(
                "approval_duplicate",
                approver,
                now,
                {"approval_id": approval_id, "proposal_id": proposal_id},
            )
        proposal = self._require_current(proposal_id)
        if now >= proposal.expires_at:
            self._safe_hold("proposal_expired_before_approval", approver, now)
            raise ExpiredProposal("proposal expired before approval")
        if self.state is not SessionState.SUPERVISED:
            raise SessionError("approval requires SUPERVISED state")
        self._approvals[approval_id] = approval
        self.approval = approval
        return self._emit(
            "envelope_approved",
            approver,
            now,
            {
                "approval_id": approval_id,
                "proposal_id": proposal_id,
                "policy_id": proposal.policy_id,
                "state": self.state.value,
            },
        )

    def authorize_execution(
        self,
        proposal_id: str,
        *,
        execution_id: str,
        actor: str,
        meter: MeterSnapshot,
        now: datetime,
    ) -> SessionEvent:
        _require_aware(now, "now")
        if not execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        existing = self._executions.get(execution_id)
        if existing is not None:
            existing_proposal_id, event = existing
            if existing_proposal_id != proposal_id:
                raise IdempotencyConflict("execution_id was reused for another proposal")
            return event
        proposal = self._require_current(proposal_id)
        if self.state is not SessionState.SUPERVISED:
            raise SessionError("execution authorization requires SUPERVISED state")
        if self.approval is None or self.approval.proposal_id != proposal_id:
            raise ApprovalRequired("explicit authorized approval is required")
        if now < proposal.effective_at:
            raise SessionError("proposal is not yet effective")
        if now >= proposal.expires_at:
            self._safe_hold("proposal_expired_before_execution", actor, now)
            raise ExpiredProposal("proposal expired before execution")
        eligibility = assess_meter_decision_eligibility(meter, now, self.freshness_policy)
        if not eligibility.eligible:
            return self._safe_hold(
                "authoritative_telemetry_ineligible",
                actor,
                now,
                reasons=eligibility.reasons,
            )
        event = self._emit(
            "execution_authorized",
            actor,
            now,
            {
                "execution_id": execution_id,
                "proposal_id": proposal_id,
                "approval_id": self.approval.approval_id,
                "approved_by": self.approval.approver,
                "policy_id": proposal.policy_id,
                "max_facility_watts": proposal.max_facility_watts,
                "authoritative_meter_source": meter.authoritative_source_id,
                "meter_sequence": meter.active_power.monotonic_sequence,
                "state": self.state.value,
                "intent_only": True,
            },
        )
        self._executions[execution_id] = (proposal_id, event)
        return event

    def enter_safe_hold(self, *, reason: str, actor: str, now: datetime) -> SessionEvent:
        if not reason.strip():
            raise ValueError("reason must be non-empty")
        return self._safe_hold(reason, actor, now)

    def _safe_hold(
        self,
        reason: str,
        actor: str,
        now: datetime,
        reasons: Tuple[str, ...] = (),
    ) -> SessionEvent:
        previous = self.state
        self.state = SessionState.SAFE_HOLD
        return self._emit(
            "safe_hold_entered",
            actor,
            now,
            {
                "reason": reason,
                "eligibility_reasons": list(reasons),
                "proposal_id": self.proposal.proposal_id if self.proposal else None,
                "previous_state": previous.value,
                "state": self.state.value,
            },
        )

    def begin_recovery(
        self,
        *,
        actor: str,
        meter: MeterSnapshot,
        now: datetime,
    ) -> SessionEvent:
        if actor not in self.authorized_approvers:
            raise AuthorizationError("recovery actor is not authorized")
        if self.state is not SessionState.SAFE_HOLD:
            raise SessionError("recovery requires SAFE_HOLD state")
        eligibility = assess_meter_decision_eligibility(meter, now, self.freshness_policy)
        if not eligibility.eligible:
            return self._safe_hold("recovery_telemetry_ineligible", actor, now, eligibility.reasons)
        previous = self.state
        self.state = SessionState.RECOVERY
        return self._emit(
            "recovery_started",
            actor,
            now,
            {"previous_state": previous.value, "state": self.state.value, "rate_limited": True},
        )

    def complete_recovery(self, *, actor: str, now: datetime) -> SessionEvent:
        if actor not in self.authorized_approvers:
            raise AuthorizationError("recovery actor is not authorized")
        if self.state is not SessionState.RECOVERY:
            raise SessionError("completion requires RECOVERY state")
        previous = self.state
        prior_proposal = self.proposal.proposal_id if self.proposal else None
        self.state = SessionState.OBSERVE
        self.proposal = None
        self.approval = None
        return self._emit(
            "recovery_completed",
            actor,
            now,
            {
                "proposal_id": prior_proposal,
                "previous_state": previous.value,
                "state": self.state.value,
            },
        )

    def _require_current(self, proposal_id: str) -> EnvelopeProposal:
        if self.proposal is None or self.proposal.proposal_id != proposal_id:
            raise SessionError("proposal is not the current session proposal")
        return self.proposal
