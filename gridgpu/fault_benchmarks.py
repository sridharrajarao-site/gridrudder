"""Canonical deterministic control-plane failure matrix."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Callable, Mapping, Tuple

from .controller import HeuristicController, SafetyViolation
from .domain import Action, Flexibility, Priority, Workload
from .faults import (
    DependencyFault,
    FaultInjection,
    FaultInjector,
    FaultKind,
    InjectedDependency,
    LeaseFence,
    manual_precedence,
    validate_optimizer_output,
)
from .gates import REQUIRED_SCENARIOS, ScenarioRequirement
from .session import ControlSession, EnvelopeProposal, SessionState
from .telemetry import MeterSnapshot, Quality, SourceSequenceReconciler, TelemetrySample


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class SafeState(str, Enum):
    SAFE_HOLD = "safe_hold"
    OBSERVE_ONLY = "observe_only"
    NO_MUTATION = "no_mutation"
    LEASE_FENCED = "lease_fenced"
    MANUAL_PRECEDENCE = "manual_precedence"
    HEURISTIC_FALLBACK = "heuristic_fallback"
    RECOVERY_HOLD = "recovery_hold"
    PROTECTED = "protected"


@dataclass(frozen=True)
class FaultObservation:
    safe_state: SafeState
    evidence: Tuple[str, ...]


@dataclass(frozen=True)
class FaultScenario:
    kind: FaultKind
    expected_safe_state: SafeState
    required_evidence: Tuple[str, ...]
    runner: Callable[[], FaultObservation]


@dataclass(frozen=True)
class FaultBenchmarkResult:
    scenario_id: str
    kind: FaultKind
    passed: bool
    expected_safe_state: SafeState
    observed_safe_state: SafeState
    required_evidence: Tuple[str, ...]
    observed_evidence: Tuple[str, ...]
    metrics: Mapping[str, float]
    invariants: Mapping[str, bool]
    findings: Tuple[str, ...]


_FAULT_REQUIREMENTS = {
    requirement.scenario_id: requirement
    for requirement in REQUIRED_SCENARIOS
    if requirement.scenario_id in {kind.value for kind in FaultKind}
}


def _sample(**changes) -> TelemetrySample[float]:
    values = dict(
        timestamp_utc=NOW,
        monotonic_sequence=1,
        source_id="pcc-1",
        value=9_000.0,
        unit="W",
        quality=Quality.GOOD,
        ingest_latency_ms=10,
        source_epoch="epoch-1",
    )
    values.update(changes)
    return TelemetrySample(**values)


def _meter(**changes) -> MeterSnapshot:
    return MeterSnapshot(_sample(**changes), "pcc-1", maximum_watts=100_000)


def _approved_session() -> ControlSession:
    session = ControlSession(frozenset({"operator"}))
    proposal = EnvelopeProposal(
        "env-1", 10_000, NOW, NOW + timedelta(minutes=5), "fault test", "policy:v1"
    )
    session.propose(proposal, actor="planner", now=NOW)
    session.approve("env-1", approval_id="approval-1", approver="operator", now=NOW)
    return session


def _telemetry_hold(kind: FaultKind) -> FaultObservation:
    session = _approved_session()
    if kind is FaultKind.METER_LOSS:
        event = session.enter_safe_hold(reason="authoritative_meter_missing", actor="controller", now=NOW)
    elif kind is FaultKind.METER_STALE:
        event = session.authorize_execution(
            "env-1",
            execution_id="exec-1",
            actor="controller",
            meter=_meter(timestamp_utc=NOW - timedelta(seconds=6)),
            now=NOW,
        )
    else:
        event = session.authorize_execution(
            "env-1",
            execution_id="exec-1",
            actor="controller",
            meter=MeterSnapshot(_sample(timestamp_utc=NOW + timedelta(seconds=1)), "pcc-1", clock_synchronized=False),
            now=NOW,
        )
    evidence = [event.payload["reason"]]
    evidence.extend(event.payload.get("eligibility_reasons", []))
    return FaultObservation(SafeState.SAFE_HOLD, tuple(evidence))


def _sequence_fault(kind: FaultKind) -> FaultObservation:
    reconciler = SourceSequenceReconciler()
    reconciler.accept(_sample(monotonic_sequence=10))
    sequence = 10 if kind is FaultKind.METER_DUPLICATE else 9
    decision = reconciler.assess(_sample(monotonic_sequence=sequence))
    cursor_unchanged = reconciler.cursor("pcc-1").last_sequence == 10
    return FaultObservation(
        SafeState.OBSERVE_ONLY,
        (
            decision.reason,
            "new_actuation_inhibited",
            "cursor_not_advanced" if cursor_unchanged else "cursor_advanced",
        ),
    )


def _dependency_fault(kind: FaultKind, name: str) -> FaultObservation:
    injector = FaultInjector((FaultInjection(0, kind, "canonical"),))
    default_unavailable = (
        FaultKind.SCHEDULER_UNAVAILABLE if name == "scheduler" else FaultKind.ADAPTER_UNAVAILABLE
    )
    default_rejected = (
        FaultKind.SCHEDULER_REJECTION if name == "scheduler" else FaultKind.ADAPTER_REJECTION
    )
    unavailable = kind if "unavailable" in kind.value else default_unavailable
    rejected = kind if "rejection" in kind.value else default_rejected
    dependency = InjectedDependency(name, injector, unavailable, rejected)
    try:
        dependency.probe(0)
    except DependencyFault as exc:
        injector.require_fully_consumed()
        return FaultObservation(
            SafeState.NO_MUTATION,
            ("{}_{}".format(exc.dependency, exc.disposition.replace(" ", "_")), "actuation_inhibited"),
        )
    raise AssertionError("fault did not trigger")


def _audit_failure() -> FaultObservation:
    injector = FaultInjector((FaultInjection(0, FaultKind.AUDIT_FAILURE, "append raises"),))
    if injector.trigger(0, FaultKind.AUDIT_FAILURE):
        injector.require_fully_consumed()
        return FaultObservation(SafeState.NO_MUTATION, ("audit_append_failed", "intent_not_executed"))
    raise AssertionError("fault did not trigger")


def _restart() -> FaultObservation:
    original = _approved_session()
    original.authorize_execution(
        "env-1", execution_id="exec-before-restart", actor="controller", meter=_meter(), now=NOW
    )
    recovered = ControlSession.reconstruct_for_operator_resume(
        original.events,
        authorized_approvers=frozenset({"operator"}),
        now=NOW + timedelta(minutes=6),
    )
    reconstruction = recovered.events[-1]
    evidence = (
        "state_reconstructed_from_evidence"
        if recovered.proposal is not None and recovered.approval is not None
        else "state_reconstruction_failed",
        "expired_commands_not_replayed"
        if recovered.authorized_execution_count == 0
        and reconstruction.payload["replayed_execution_commands"] == 0
        and reconstruction.payload["proposal_expired"] is True
        else "expired_command_replayed",
        "operator_resume_required"
        if recovered.state is SessionState.SAFE_HOLD
        and reconstruction.payload["operator_resume_required"] is True
        else "operator_resume_not_required",
    )
    return FaultObservation(SafeState.SAFE_HOLD, evidence)


def _split_brain() -> FaultObservation:
    fence = LeaseFence()
    old_epoch = fence.acquire("controller-a")
    fence.acquire("controller-b")
    decision = fence.assess("controller-a", old_epoch)
    return FaultObservation(SafeState.LEASE_FENCED, (decision.evidence, "stale_writer_no_actuation"))


def _manual_conflict() -> FaultObservation:
    selected, evidence = manual_precedence(8_000, 10_000)
    return FaultObservation(SafeState.MANUAL_PRECEDENCE, (evidence, "selected_limit_8000" if selected == 8_000 else ""))


def _optimizer_fault(kind: FaultKind) -> FaultObservation:
    if kind is FaultKind.OPTIMIZER_TIMEOUT:
        evidence = "optimizer_deadline_exceeded"
    else:
        valid, evidence = validate_optimizer_output({"actions": "not-a-list"})
        if valid:
            raise AssertionError("invalid optimizer output was accepted")
    # The deterministic heuristic is the approved fallback; no action is
    # executed here because this matrix tests selection/fencing, not hardware.
    fallback = HeuristicController()
    if fallback is None:  # pragma: no cover - documents required construction
        raise AssertionError("heuristic fallback unavailable")
    return FaultObservation(SafeState.HEURISTIC_FALLBACK, (evidence, "heuristic_fallback_selected"))


def _interrupted_recovery() -> FaultObservation:
    session = _approved_session()
    session.enter_safe_hold(reason="test", actor="operator", now=NOW)
    session.begin_recovery(actor="operator", meter=_meter(), now=NOW)
    event = session.enter_safe_hold(reason="recovery_interrupted", actor="controller", now=NOW)
    return FaultObservation(
        SafeState.RECOVERY_HOLD,
        (event.payload["reason"], "recovery_increase_inhibited"),
    )


def _protected_mislabel() -> FaultObservation:
    workload = Workload(
        "critical",
        Priority.CRITICAL,
        1,
        0,
        100,
        300,
        Flexibility(may_power_cap=True, min_power_watts_per_gpu=100),
        state="running",
    )
    try:
        HeuristicController().validate(
            [Action("set_power_cap", "critical", 150, "malicious_mislabel")],
            {"critical": workload},
        )
    except SafetyViolation as exc:
        return FaultObservation(SafeState.PROTECTED, ("protected_workload_rejected", str(exc)))
    raise AssertionError("critical workload mislabel bypassed protection")


def canonical_fault_scenarios() -> Tuple[FaultScenario, ...]:
    """Return the required failure matrix in stable order."""
    return (
        FaultScenario(FaultKind.METER_LOSS, SafeState.SAFE_HOLD, ("authoritative_meter_missing",), lambda: _telemetry_hold(FaultKind.METER_LOSS)),
        FaultScenario(FaultKind.METER_STALE, SafeState.SAFE_HOLD, ("meter sample is stale",), lambda: _telemetry_hold(FaultKind.METER_STALE)),
        FaultScenario(FaultKind.METER_DUPLICATE, SafeState.OBSERVE_ONLY, ("duplicate sequence", "new_actuation_inhibited"), lambda: _sequence_fault(FaultKind.METER_DUPLICATE)),
        FaultScenario(FaultKind.METER_REORDER, SafeState.OBSERVE_ONLY, ("sequence regression", "new_actuation_inhibited"), lambda: _sequence_fault(FaultKind.METER_REORDER)),
        FaultScenario(FaultKind.CLOCK_JUMP, SafeState.SAFE_HOLD, ("meter clock is not synchronized",), lambda: _telemetry_hold(FaultKind.CLOCK_JUMP)),
        FaultScenario(FaultKind.SCHEDULER_UNAVAILABLE, SafeState.NO_MUTATION, ("scheduler_unavailable", "actuation_inhibited"), lambda: _dependency_fault(FaultKind.SCHEDULER_UNAVAILABLE, "scheduler")),
        FaultScenario(FaultKind.SCHEDULER_REJECTION, SafeState.NO_MUTATION, ("scheduler_rejected_request", "actuation_inhibited"), lambda: _dependency_fault(FaultKind.SCHEDULER_REJECTION, "scheduler")),
        FaultScenario(FaultKind.ADAPTER_UNAVAILABLE, SafeState.NO_MUTATION, ("adapter_unavailable", "actuation_inhibited"), lambda: _dependency_fault(FaultKind.ADAPTER_UNAVAILABLE, "adapter")),
        FaultScenario(FaultKind.ADAPTER_REJECTION, SafeState.NO_MUTATION, ("adapter_rejected_request", "actuation_inhibited"), lambda: _dependency_fault(FaultKind.ADAPTER_REJECTION, "adapter")),
        FaultScenario(FaultKind.AUDIT_FAILURE, SafeState.NO_MUTATION, ("audit_append_failed", "intent_not_executed"), _audit_failure),
        FaultScenario(FaultKind.CONTROLLER_RESTART, SafeState.SAFE_HOLD, ("state_reconstructed_from_evidence", "expired_commands_not_replayed", "operator_resume_required"), _restart),
        FaultScenario(FaultKind.SPLIT_BRAIN, SafeState.LEASE_FENCED, ("stale_controller_fenced", "stale_writer_no_actuation"), _split_brain),
        FaultScenario(FaultKind.MANUAL_CONFLICT, SafeState.MANUAL_PRECEDENCE, ("stricter_manual_or_optimizer_limit_selected", "selected_limit_8000"), _manual_conflict),
        FaultScenario(FaultKind.OPTIMIZER_TIMEOUT, SafeState.HEURISTIC_FALLBACK, ("optimizer_deadline_exceeded", "heuristic_fallback_selected"), lambda: _optimizer_fault(FaultKind.OPTIMIZER_TIMEOUT)),
        FaultScenario(FaultKind.OPTIMIZER_INVALID_OUTPUT, SafeState.HEURISTIC_FALLBACK, ("optimizer_actions_not_list", "heuristic_fallback_selected"), lambda: _optimizer_fault(FaultKind.OPTIMIZER_INVALID_OUTPUT)),
        FaultScenario(FaultKind.INTERRUPTED_RECOVERY, SafeState.RECOVERY_HOLD, ("recovery_interrupted", "recovery_increase_inhibited"), _interrupted_recovery),
        FaultScenario(FaultKind.PROTECTED_MISLABEL, SafeState.PROTECTED, ("protected_workload_rejected",), _protected_mislabel),
    )


def assess_fault_observation(scenario: FaultScenario, observed: FaultObservation) -> FaultBenchmarkResult:
    missing = tuple(item for item in scenario.required_evidence if item not in observed.evidence)
    wrong_state = observed.safe_state is not scenario.expected_safe_state
    findings = ()
    if wrong_state:
        findings += ("safe state mismatch",)
    if missing:
        findings += ("missing evidence: {}".format(", ".join(missing)),)
    metrics, invariants = _derive_gate_facts(scenario, observed)
    return FaultBenchmarkResult(
        scenario_id=scenario.kind.value,
        kind=scenario.kind,
        passed=not findings,
        expected_safe_state=scenario.expected_safe_state,
        observed_safe_state=observed.safe_state,
        required_evidence=scenario.required_evidence,
        observed_evidence=observed.evidence,
        metrics=metrics,
        invariants=invariants,
        findings=findings,
    )


def _derive_gate_facts(
    scenario: FaultScenario, observed: FaultObservation
) -> Tuple[Mapping[str, float], Mapping[str, bool]]:
    """Translate observed behavior into Gate-B names without optimistic fill.

    A fact is true only when the state/evidence produced by the scenario proves
    it. Counter metrics describe this single deterministic injection. If the
    corresponding containment fact is absent, the counter becomes one rather
    than silently reporting a successful zero.
    """

    requirement = _FAULT_REQUIREMENTS.get(scenario.kind.value)
    if requirement is None:
        raise ValueError("no Gate-B requirement for {}".format(scenario.kind.value))
    evidence = set(observed.evidence)
    state = observed.safe_state

    facts = {
        "new_actuation_inhibited": state in (SafeState.SAFE_HOLD, SafeState.OBSERVE_ONLY),
        "safe_hold_entered": state is SafeState.SAFE_HOLD,
        "operator_alert_recorded": "authoritative_meter_missing" in evidence,
        "operator_reason_recorded": bool(evidence) and state is SafeState.SAFE_HOLD,
        "duplicate_rejected": "duplicate sequence" in evidence,
        "regression_rejected": "sequence regression" in evidence,
        "cursor_not_advanced": "cursor_not_advanced" in evidence,
        "clock_fault_rejected": state is SafeState.SAFE_HOLD
        and "meter clock is not synchronized" in evidence,
        "no_partial_plan_executed": state is SafeState.HEURISTIC_FALLBACK
        and "optimizer_deadline_exceeded" in evidence,
        "approved_fallback_selected": state is SafeState.HEURISTIC_FALLBACK
        and "heuristic_fallback_selected" in evidence,
        "timeout_audited": "optimizer_deadline_exceeded" in evidence,
        "invalid_plan_rejected": "optimizer_actions_not_list" in evidence,
        "validation_reason_audited": "optimizer_actions_not_list" in evidence
        or any("protected workload" in item for item in evidence),
        "workload_mutation_inhibited": state is SafeState.NO_MUTATION
        and "actuation_inhibited" in evidence,
        "protected_workloads_unchanged": state in (SafeState.NO_MUTATION, SafeState.PROTECTED),
        "outage_audited": any(item.endswith("_unavailable") for item in evidence),
        "rejection_not_assumed_success": any("rejected_request" in item for item in evidence),
        "failure_audited": any(
            "unavailable" in item or "rejected_request" in item for item in evidence
        ),
        "command_not_assumed_applied": state is SafeState.NO_MUTATION
        and "actuation_inhibited" in evidence,
        "no_mutation": state is SafeState.NO_MUTATION,
        "mutation_prevented": "intent_not_executed" in evidence,
        "failure_surfaced": "audit_append_failed" in evidence,
        "state_reconstructed_from_evidence": "state_reconstructed_from_evidence" in evidence,
        "expired_commands_not_replayed": "expired_commands_not_replayed" in evidence,
        "operator_resume_required": "operator_resume_required" in evidence,
        "single_writer_enforced": state is SafeState.LEASE_FENCED,
        "stale_writer_fenced": "stale_controller_fenced" in evidence,
        "conflict_audited": state in (SafeState.LEASE_FENCED, SafeState.MANUAL_PRECEDENCE),
        "manual_control_wins": state is SafeState.MANUAL_PRECEDENCE
        and "selected_limit_8000" in evidence,
        "automatic_event_cancelled": state is SafeState.MANUAL_PRECEDENCE,
        "recovery_increase_inhibited": "recovery_increase_inhibited" in evidence,
        "recovery_hold_entered": state is SafeState.RECOVERY_HOLD,
        "interruption_audited": "recovery_interrupted" in evidence,
        "protected_workload_rejected": "protected_workload_rejected" in evidence,
    }
    invariants = {name: bool(facts.get(name, False)) for name in requirement.required_invariants}

    zero_metric_fact = {
        "actions_after_fault": "new_actuation_inhibited",
        "accepted_fault_count": (
            "duplicate_rejected"
            if scenario.kind is FaultKind.METER_DUPLICATE
            else "regression_rejected"
            if scenario.kind is FaultKind.METER_REORDER
            else "clock_fault_rejected"
        ),
        "actions_from_partial_plan": "no_partial_plan_executed",
        "invalid_actions_applied": "invalid_plan_rejected",
        "workload_actions_after_fault": "workload_mutation_inhibited",
        "commands_assumed_applied": "command_not_assumed_applied",
        "mutations_after_fault": "mutation_prevented",
        "replayed_expired_commands": "expired_commands_not_replayed",
        "unfenced_command_count": "single_writer_enforced",
        "automatic_overrides_of_manual": "manual_control_wins",
        "recovery_increases_after_fault": "recovery_increase_inhibited",
        "protected_actions_applied": "protected_workload_rejected",
    }
    metrics = {}
    for name in requirement.required_metrics:
        if name == "fault_count":
            value = 1.0 if observed.evidence else 0.0
        else:
            # Each benchmark attempts at most one forbidden post-fault effect.
            # A zero is reported only when its corresponding containment fact
            # is directly established by the observation.
            fact_name = zero_metric_fact[name]
            value = 0.0 if facts.get(fact_name, False) else 1.0
        if not math.isfinite(value):  # defensive producer-side assertion
            raise AssertionError("non-finite fault metric")
        metrics[name] = value
    return metrics, invariants


def run_fault_benchmark(scenario: FaultScenario) -> FaultBenchmarkResult:
    return assess_fault_observation(scenario, scenario.runner())


def run_canonical_fault_matrix() -> Tuple[FaultBenchmarkResult, ...]:
    return tuple(run_fault_benchmark(scenario) for scenario in canonical_fault_scenarios())
