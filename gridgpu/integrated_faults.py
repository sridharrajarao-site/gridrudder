"""Primary-trace normal and fault scenarios using SupervisoryHarness."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Tuple

from .domain import Action, Flexibility, Priority, Snapshot, Workload
from .faults import FaultInjection, FaultInjector, FaultKind, LeaseFence, manual_precedence
from .gates import REQUIRED_SCENARIOS, ScenarioRequirement
from .policy import AuthorizationContext, FlexibilityPolicyGuard, WorkloadPolicy
from .session import ControlSession, EnvelopeProposal, SessionState
from .supervisor import MemoryAuditSink, MutationRecord, SupervisoryHarness, TraceEvent
from .telemetry import MeterSnapshot, Quality, TelemetrySample


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class PrimaryTraceResult:
    scenario_id: str
    kind: str
    expected_state: str
    observed_state: str
    primary_trace: Tuple[Mapping[str, Any], ...]
    injection_ledger: Tuple[Mapping[str, Any], ...]
    mutation_ledger: Tuple[Mapping[str, Any], ...]
    raw_facts: Mapping[str, Any]
    evidence: Tuple[str, ...]

    @property
    def safe_state(self) -> str:
        return self.observed_state

    @property
    def trace(self) -> Tuple[Mapping[str, Any], ...]:
        return self.primary_trace

    @property
    def injection_consumed(self) -> bool:
        return bool(self.raw_facts["injection_consumed"])

    def as_mapping(self) -> Mapping[str, Any]:
        """Return a canonical-JSON-ready producer-neutral representation."""
        return {
            "scenario_id": self.scenario_id,
            "kind": self.kind,
            "expected_state": self.expected_state,
            "observed_state": self.observed_state,
            "primary_trace": list(self.primary_trace),
            "injection_ledger": list(self.injection_ledger),
            "mutation_ledger": list(self.mutation_ledger),
            "raw_facts": dict(self.raw_facts),
            "evidence": list(self.evidence),
        }


_FAULT_GATE_REQUIREMENTS = {
    requirement.scenario_id: requirement
    for requirement in REQUIRED_SCENARIOS
    if requirement.scenario_id in {kind.value for kind in FaultKind}
}


def fault_gate_requirements() -> Mapping[str, ScenarioRequirement]:
    expected = {kind.value for kind in FaultKind}
    if set(_FAULT_GATE_REQUIREMENTS) != expected:
        missing = sorted(expected - set(_FAULT_GATE_REQUIREMENTS))
        extra = sorted(set(_FAULT_GATE_REQUIREMENTS) - expected)
        raise RuntimeError("fault/gate ID mismatch: missing={} extra={}".format(missing, extra))
    return dict(_FAULT_GATE_REQUIREMENTS)


def _meter(sequence: int = 1, **changes) -> MeterSnapshot:
    values = dict(
        timestamp_utc=NOW,
        monotonic_sequence=sequence,
        source_id="pcc-1",
        value=1_300.0,
        unit="W",
        quality=Quality.GOOD,
        ingest_latency_ms=10,
        source_epoch="epoch-1",
    )
    values.update(changes)
    return MeterSnapshot(TelemetrySample(**values), "pcc-1", maximum_watts=100_000)


def _build(kind=None, audit_failure=False, planner=None):
    injections = () if kind is None else (FaultInjection(0, kind, "primary-trace"),)
    injector = FaultInjector(injections)
    workload = Workload(
        "flex",
        Priority.OPPORTUNISTIC,
        1,
        0,
        1_000,
        300,
        Flexibility(True, True, 150),
        state="running",
    )
    workloads = {workload.workload_id: workload}
    session = ControlSession(frozenset({"operator"}))
    proposal = EnvelopeProposal("env-1", 1_200, NOW, NOW + timedelta(minutes=5), "test", "policy:v1")
    session.propose(proposal, actor="planner", now=NOW)
    session.approve("env-1", approval_id="approval-1", approver="operator", now=NOW)
    policy = WorkloadPolicy("flex", "tenant", ("operator",), True, True, 150, 600, 10)
    harness = SupervisoryHarness(
        session=session,
        policy_guard=FlexibilityPolicyGuard((policy,)),
        authorization=AuthorizationContext("tenant", "operator", "event-1", 60),
        workloads=workloads,
        injector=injector,
        audit=MemoryAuditSink("action_intent" if audit_failure else None),
        planner=planner,
    )
    snapshot = Snapshot(0, 1_200, 1_300, [workload])
    return harness, injector, snapshot, workload


def _json_trace(harness):
    return tuple(
        {"sequence": index, "phase": row.phase, "outcome": row.outcome, "evidence": row.evidence}
        for index, row in enumerate(harness.trace)
    )


def _json_mutations(harness):
    return tuple(
        {
            "sequence": index,
            "action": asdict(row.action),
            "scheduler_acknowledged": row.scheduler_acknowledged,
            "adapter_acknowledged": row.adapter_acknowledged,
            "observed": row.observed,
        }
        for index, row in enumerate(harness.mutations)
    )


def _json_session_events(harness):
    return [
        {
            "sequence": index,
            "event_type": event.event_type,
            "actor": event.actor,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }
        for index, event in enumerate(harness.session.events)
    ]


def _final(scenario_id, harness, injector, evidence, before, scenario_inputs):
    pending = injector.pending
    observed_injections = injector.observed
    requirement = fault_gate_requirements().get(scenario_id)
    expected_state = (
        SessionState.SUPERVISED.value
        if scenario_id in ("normal", FaultKind.OPTIMIZER_TIMEOUT.value)
        else SessionState.SAFE_HOLD.value
    )
    trace = _json_trace(harness)
    mutations = _json_mutations(harness)
    injection_ledger = tuple(
        {
            "sequence": index,
            "step": injection.step,
            "fault_id": injection.kind.value,
            "detail": injection.detail,
            "consumed": True,
        }
        for index, injection in enumerate(observed_injections)
    )
    cursor = harness.reconciler.cursor("pcc-1")
    after = {
        key: {
            "priority": workload.priority.value,
            "state": workload.state,
            "current_cap_watts": workload.current_cap_watts,
        }
        for key, workload in sorted(harness.workloads.items())
    }
    raw_facts = {
        "declared_injection_count": len(observed_injections) + len(pending),
        "consumed_injection_count": len(observed_injections),
        "pending_injection_count": len(pending),
        "injection_consumed": not pending,
        "trace_row_count": len(trace),
        "mutation_count": len(mutations),
        "observed_mutation_count": sum(1 for row in mutations if row["observed"]),
        "scheduler_acknowledged_count": sum(
            1 for row in mutations if row["scheduler_acknowledged"]
        ),
        "adapter_acknowledged_count": sum(
            1 for row in mutations if row["adapter_acknowledged"]
        ),
        "audit_records": list(harness.audit.records),
        "session_events": _json_session_events(harness),
        "workloads_before": before,
        "workloads_after": after,
        "authoritative_cursor": None
        if cursor is None
        else {
            "source_id": cursor.source_id,
            "source_epoch": cursor.source_epoch,
            "last_sequence": cursor.last_sequence,
        },
        "gate_required_metrics": [] if requirement is None else list(requirement.required_metrics),
        "gate_required_invariants": []
        if requirement is None
        else list(requirement.required_invariants),
        "scenario_inputs": dict(scenario_inputs),
    }
    return PrimaryTraceResult(
        scenario_id=scenario_id,
        kind="normal" if scenario_id == "normal" else scenario_id,
        expected_state=expected_state,
        observed_state=harness.session.state.value,
        primary_trace=trace,
        injection_ledger=injection_ledger,
        mutation_ledger=mutations,
        raw_facts=raw_facts,
        evidence=tuple(evidence),
    )


def run_primary_trace(scenario_id: str) -> PrimaryTraceResult:
    kind = None if scenario_id == "normal" else FaultKind(scenario_id)
    harness, injector, snapshot, workload = _build(
        kind if kind in {
            FaultKind.SCHEDULER_UNAVAILABLE,
            FaultKind.SCHEDULER_REJECTION,
            FaultKind.ADAPTER_UNAVAILABLE,
            FaultKind.ADAPTER_REJECTION,
            FaultKind.OPTIMIZER_TIMEOUT,
            FaultKind.OPTIMIZER_INVALID_OUTPUT,
        } else None,
        audit_failure=kind is FaultKind.AUDIT_FAILURE,
    )
    evidence = []
    scenario_inputs = {
        "fault_id": None if kind is None else kind.value,
        "injection_step": None if kind is None else 0,
    }
    if kind is FaultKind.PROTECTED_MISLABEL:
        # The workload is intrinsically critical while its flexibility metadata
        # is maliciously permissive. The independent controller validator must
        # preserve the critical classification and reject the action.
        workload.priority = Priority.CRITICAL
    before = {
        key: {
            "priority": item.priority.value,
            "state": item.state,
            "current_cap_watts": item.current_cap_watts,
        }
        for key, item in sorted(harness.workloads.items())
    }

    if kind is FaultKind.METER_LOSS:
        scenario_inputs["authoritative_meter_present"] = False
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness.run_cycle(step=0, now=NOW, meter=None, snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    elif kind in (FaultKind.METER_DUPLICATE, FaultKind.METER_REORDER):
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness.prime_meter(_meter(10))
        sequence = 10 if kind is FaultKind.METER_DUPLICATE else 9
        scenario_inputs["accepted_sequence_before_fault"] = 10
        scenario_inputs["injected_sequence"] = sequence
        harness.run_cycle(step=0, now=NOW, meter=_meter(sequence), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    elif kind is FaultKind.METER_STALE:
        scenario_inputs["sample_age_seconds"] = 6.0
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness.run_cycle(step=0, now=NOW, meter=_meter(timestamp_utc=NOW - timedelta(seconds=6)), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    elif kind is FaultKind.CLOCK_JUMP:
        scenario_inputs["clock_synchronized"] = False
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        bad = MeterSnapshot(_meter().active_power, "pcc-1", clock_synchronized=False)
        harness.run_cycle(step=0, now=NOW, meter=bad, snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    elif kind is FaultKind.AUDIT_FAILURE:
        scenario_inputs["failing_audit_event_type"] = "action_intent"
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness.run_cycle(step=0, now=NOW, meter=_meter(), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    elif kind is FaultKind.CONTROLLER_RESTART:
        scenario_inputs["restart_after_expiry"] = True
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness.session.authorize_execution(
            "env-1",
            execution_id="expired-before-restart",
            actor="supervisor",
            meter=_meter(),
            now=NOW,
        )
        recovered = ControlSession.reconstruct_for_operator_resume(
            harness.session.events,
            authorized_approvers=frozenset({"operator"}),
            now=NOW + timedelta(minutes=6),
        )
        harness.session = recovered
        harness._trace("restart", "safe_hold", "operator_resume_required")
    elif kind is FaultKind.SPLIT_BRAIN:
        scenario_inputs["contending_controller_count"] = 2
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        fence = LeaseFence(); old = fence.acquire("a"); fence.acquire("b")
        decision = fence.assess("a", old)
        harness._hold(decision.evidence, NOW)
    elif kind is FaultKind.MANUAL_CONFLICT:
        scenario_inputs["manual_limit_watts"] = 1_100
        scenario_inputs["automatic_limit_watts"] = 1_200
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        selected, reason = manual_precedence(1_100, 1_200)
        harness._hold("{}:{}".format(reason, selected), NOW)
    elif kind is FaultKind.INTERRUPTED_RECOVERY:
        scenario_inputs["recovery_interrupted"] = True
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        harness._hold("initial_hold", NOW)
        harness.session.begin_recovery(actor="operator", meter=_meter(), now=NOW)
        harness._hold("recovery_interrupted", NOW)
    elif kind is FaultKind.PROTECTED_MISLABEL:
        injector = FaultInjector((FaultInjection(0, kind, "primary-trace"),))
        injector.trigger(0, kind)
        scenario_inputs["attempted_cap_watts"] = 150
        scenario_inputs["declared_priority"] = Priority.CRITICAL.value
        harness.planner = lambda _snapshot: [Action("set_power_cap", "flex", 150, "attack")]
        harness.run_cycle(step=0, now=NOW, meter=_meter(), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
    else:
        if kind in (FaultKind.OPTIMIZER_TIMEOUT, FaultKind.OPTIMIZER_INVALID_OUTPUT):
            scenario_inputs["planner_fault"] = kind.value
        elif kind is not None:
            scenario_inputs["boundary_fault"] = kind.value
        harness.run_cycle(step=0, now=NOW, meter=_meter(), snapshot=snapshot, proposal_id="env-1", execution_id="exec")

    evidence.extend(event.evidence for event in harness.trace)
    if kind is not None and injector.pending:
        evidence.append("injection_not_consumed")
    return _final(scenario_id, harness, injector, evidence, before, scenario_inputs)


def run_all_primary_traces() -> Tuple[PrimaryTraceResult, ...]:
    ids = ("normal",) + tuple(kind.value for kind in FaultKind)
    return tuple(run_primary_trace(scenario_id) for scenario_id in ids)
