"""Deterministic, side-effect-free supervisory integration harness."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from .controller import HeuristicController
from .domain import Action, Snapshot, Workload
from .faults import DependencyFault, FaultInjector, FaultKind, InjectedDependency
from .policy import AuthorizationContext, FlexibilityPolicyGuard, PolicyViolation
from .session import ControlSession, SessionState
from .telemetry import (
    MeterSnapshot,
    SourceSequenceReconciler,
    TelemetryValidationError,
    assess_meter_decision_eligibility,
)


@dataclass(frozen=True)
class TraceEvent:
    phase: str
    outcome: str
    evidence: str


@dataclass(frozen=True)
class MutationRecord:
    action: Action
    scheduler_acknowledged: bool
    adapter_acknowledged: bool
    observed: bool


class MemoryAuditSink:
    def __init__(self, fail_event_type: Optional[str] = None):
        self.fail_event_type = fail_event_type
        self.records: List[dict] = []

    def append(self, event_type: str, payload: dict) -> None:
        if event_type == self.fail_event_type:
            raise OSError("injected audit failure")
        self.records.append({"event_type": event_type, "payload": dict(payload)})


class BoundaryPair:
    """Injected scheduler/adapter probes; neither performs a physical write."""

    def __init__(self, injector: FaultInjector):
        self.scheduler = InjectedDependency(
            "scheduler",
            injector,
            FaultKind.SCHEDULER_UNAVAILABLE,
            FaultKind.SCHEDULER_REJECTION,
        )
        self.adapter = InjectedDependency(
            "adapter", injector, FaultKind.ADAPTER_UNAVAILABLE, FaultKind.ADAPTER_REJECTION
        )

    def execute(self, step: int, action: Action) -> Tuple[bool, bool]:
        self.scheduler.probe(step)
        scheduler_ack = True
        adapter_ack = False
        if action.action_type == "set_power_cap":
            self.adapter.probe(step)
            adapter_ack = True
        return scheduler_ack, adapter_ack


class SupervisoryHarness:
    """One deterministic path from authoritative input to observed outcome."""

    def __init__(
        self,
        *,
        session: ControlSession,
        policy_guard: FlexibilityPolicyGuard,
        authorization: AuthorizationContext,
        workloads: Dict[str, Workload],
        injector: FaultInjector,
        audit: Optional[MemoryAuditSink] = None,
        planner: Optional[Callable[[Snapshot], List[Action]]] = None,
    ) -> None:
        self.session = session
        self.policy_guard = policy_guard
        self.authorization = authorization
        self.workloads = workloads
        self.injector = injector
        self.audit = audit or MemoryAuditSink()
        self.controller = HeuristicController(reserve_watts=0)
        self.planner = planner or self.controller.recommend
        self.reconciler = SourceSequenceReconciler()
        self.boundaries = BoundaryPair(injector)
        self.trace: List[TraceEvent] = []
        self.mutations: List[MutationRecord] = []

    def _trace(self, phase: str, outcome: str, evidence: str) -> None:
        self.trace.append(TraceEvent(phase, outcome, evidence))

    def _hold(self, reason: str, now: datetime) -> None:
        self.session.enter_safe_hold(reason=reason, actor="supervisor", now=now)
        self._trace("safe_hold", "entered", reason)

    def prime_meter(self, meter: MeterSnapshot) -> None:
        self.reconciler.accept(meter.active_power)
        self._trace("meter", "primed", "authoritative_sequence_accepted")

    def run_cycle(
        self,
        *,
        step: int,
        now: datetime,
        meter: Optional[MeterSnapshot],
        snapshot: Snapshot,
        proposal_id: str,
        execution_id: str,
    ) -> None:
        """Run one supervised decision. Any fault fails closed before mutation."""

        if meter is None:
            self._hold("authoritative_meter_missing", now)
            return
        sequence = self.reconciler.assess(meter.active_power)
        if not sequence.accepted:
            self._hold(sequence.reason, now)
            return
        eligibility = assess_meter_decision_eligibility(meter, now, self.session.freshness_policy)
        if not eligibility.eligible:
            self._hold("; ".join(eligibility.reasons), now)
            return
        self.reconciler.accept(meter.active_power)
        self._trace("meter", "accepted", "authoritative_meter_reconciled")

        authorization = self.session.authorize_execution(
            proposal_id,
            execution_id=execution_id,
            actor="supervisor",
            meter=meter,
            now=now,
        )
        if authorization.event_type != "execution_authorized":
            self._trace("authorization", "inhibited", authorization.payload["reason"])
            return
        self._trace("authorization", "approved", "explicit_operator_approval_verified")

        if self.injector.trigger(step, FaultKind.OPTIMIZER_TIMEOUT):
            self._trace("planner", "fallback", "optimizer_deadline_exceeded")
            actions = self.controller.recommend(snapshot)
        elif self.injector.trigger(step, FaultKind.OPTIMIZER_INVALID_OUTPUT):
            self._hold("optimizer_output_invalid", now)
            return
        else:
            actions = self.planner(snapshot)
        if not isinstance(actions, list) or any(not isinstance(action, Action) for action in actions):
            self._hold("optimizer_output_invalid", now)
            return
        self._trace("planner", "complete", "deterministic_plan_created")

        try:
            self.controller.validate(actions, self.workloads)
            self.policy_guard.validate_actions(actions, self.workloads, self.authorization)
        except (PolicyViolation, RuntimeError) as exc:
            self._hold("validation_rejected: {}".format(exc), now)
            return
        self._trace("validation", "accepted", "independent_policy_guard_passed")

        if not actions:
            self.audit.append("no_action", {"execution_id": execution_id})
            self._trace("outcome", "observed", "no_action")
            return

        for action in actions:
            try:
                self.audit.append(
                    "action_intent", {"execution_id": execution_id, "action": asdict(action)}
                )
            except OSError as exc:
                self._hold("audit_intent_failed: {}".format(exc), now)
                return
            self._trace("audit", "intent_durable", action.workload_id)
            try:
                scheduler_ack, adapter_ack = self.boundaries.execute(step, action)
            except DependencyFault as exc:
                self.audit.append(
                    "action_outcome",
                    {"execution_id": execution_id, "status": "rejected", "reason": str(exc)},
                )
                self._hold(str(exc), now)
                return
            workload = self.workloads[action.workload_id]
            if action.action_type == "set_power_cap":
                workload.current_cap_watts = action.value
            self.mutations.append(MutationRecord(action, scheduler_ack, adapter_ack, True))
            self.audit.append(
                "action_outcome", {"execution_id": execution_id, "status": "observed"}
            )
            self._trace("outcome", "observed", "mutation_observed")

