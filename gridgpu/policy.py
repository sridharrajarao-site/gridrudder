"""Workload flexibility authorization independent of controller logic.

Unknown workloads are protected.  A controller recommendation is executable
only when both the workload's local flexibility declaration and a scoped,
explicit policy authorize it.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .domain import Action, Workload


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkloadPolicy:
    workload_id: str
    tenant_id: str
    allowed_operator_ids: Tuple[str, ...]
    may_defer: bool = False
    may_power_cap: bool = False
    minimum_power_watts_per_gpu: Optional[float] = None
    maximum_event_duration_seconds: int = 0
    maximum_actions_per_event: int = 0

    def __post_init__(self) -> None:
        if not self.workload_id.strip() or not self.tenant_id.strip():
            raise ValueError("workload_id and tenant_id must be non-empty")
        if not self.allowed_operator_ids or any(not value.strip() for value in self.allowed_operator_ids):
            raise ValueError("at least one non-empty operator_id is required")
        if len(set(self.allowed_operator_ids)) != len(self.allowed_operator_ids):
            raise ValueError("allowed_operator_ids must be unique")
        if self.minimum_power_watts_per_gpu is not None and self.minimum_power_watts_per_gpu < 0:
            raise ValueError("minimum power must be non-negative")
        if self.maximum_event_duration_seconds < 0 or self.maximum_actions_per_event < 0:
            raise ValueError("duration and action budget must be non-negative")
        if self.may_power_cap and self.minimum_power_watts_per_gpu is None:
            raise ValueError("power-cap authorization requires a minimum power floor")


@dataclass(frozen=True)
class AuthorizationContext:
    tenant_id: str
    operator_id: str
    event_id: str
    event_duration_seconds: int
    actions_already_used: int = 0
    recovery: bool = False

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.operator_id.strip() or not self.event_id.strip():
            raise ValueError("tenant_id, operator_id, and event_id must be non-empty")
        if self.event_duration_seconds < 0 or self.actions_already_used < 0:
            raise ValueError("duration and used action count must be non-negative")


@dataclass(frozen=True)
class AuthorizationDecision:
    authorized: bool
    reasons: Tuple[str, ...] = ()

    def require(self) -> None:
        if not self.authorized:
            raise PolicyViolation("; ".join(self.reasons))


class FlexibilityPolicyGuard:
    """Fail-closed policy lookup and action validation."""

    def __init__(self, policies: Iterable[WorkloadPolicy] = ()):
        by_workload: Dict[str, WorkloadPolicy] = {}
        for policy in policies:
            if policy.workload_id in by_workload:
                raise ValueError("duplicate workload policy")
            by_workload[policy.workload_id] = policy
        self._policies: Mapping[str, WorkloadPolicy] = by_workload

    def assess(
        self,
        action: Action,
        workload: Workload,
        context: AuthorizationContext,
        batch_action_offset: int = 0,
    ) -> AuthorizationDecision:
        reasons = []
        policy = self._policies.get(workload.workload_id)

        if action.workload_id != workload.workload_id:
            reasons.append("action and workload identifiers do not match")
        if policy is None:
            reasons.append("unknown workload is protected")
            return AuthorizationDecision(False, tuple(reasons))
        if context.tenant_id != policy.tenant_id:
            reasons.append("tenant is not authorized for workload")
        if context.operator_id not in policy.allowed_operator_ids:
            reasons.append("operator is not authorized for workload")
        if context.event_duration_seconds > policy.maximum_event_duration_seconds:
            reasons.append("event exceeds authorized duration")
        if context.actions_already_used + batch_action_offset + 1 > policy.maximum_actions_per_event:
            reasons.append("event action budget exhausted")

        if action.action_type == "defer":
            self._assess_deferral(action, workload, policy, context, reasons)
        elif action.action_type == "set_power_cap":
            self._assess_power_cap(action, workload, policy, context, reasons)
        else:
            reasons.append("action type is not authorized")

        return AuthorizationDecision(not reasons, tuple(reasons))

    @staticmethod
    def _assess_deferral(
        action: Action,
        workload: Workload,
        policy: WorkloadPolicy,
        context: AuthorizationContext,
        reasons: list,
    ) -> None:
        if context.recovery:
            reasons.append("deferral is forbidden during recovery")
        if not policy.may_defer or not workload.flexibility.may_defer:
            reasons.append("deferral is not authorized")
        if workload.state != "queued":
            reasons.append("only queued work may be deferred")
        if action.value is not None:
            reasons.append("deferral action must not carry a value")

    @staticmethod
    def _assess_power_cap(
        action: Action,
        workload: Workload,
        policy: WorkloadPolicy,
        context: AuthorizationContext,
        reasons: list,
    ) -> None:
        if not policy.may_power_cap or not workload.flexibility.may_power_cap:
            reasons.append("power capping is not authorized")

        declared_floor = workload.flexibility.min_power_watts_per_gpu
        policy_floor = policy.minimum_power_watts_per_gpu
        if declared_floor is None or policy_floor is None:
            reasons.append("power cap floor is not configured")
            return
        effective_floor = max(declared_floor, policy_floor)

        current = workload.effective_watts_per_gpu()
        if context.recovery:
            if workload.current_cap_watts is None:
                reasons.append("uncapped workload has nothing to recover")
            if action.value is not None:
                if action.value < current:
                    reasons.append("recovery may not lower a power cap")
                if action.value > workload.watts_per_gpu:
                    reasons.append("recovery cap exceeds nominal workload power")
                if action.value < effective_floor:
                    reasons.append("power cap is below authorized floor")
            # None restores nominal power and is valid only in recovery.
        else:
            if action.value is None:
                reasons.append("cap removal is permitted only during recovery")
            else:
                if action.value < effective_floor:
                    reasons.append("power cap is below authorized floor")
                if action.value >= current:
                    reasons.append("constraint action must reduce current power")

    def validate_action(
        self, action: Action, workload: Workload, context: AuthorizationContext
    ) -> None:
        self.assess(action, workload, context).require()

    def validate_actions(
        self,
        actions: Iterable[Action],
        workloads: Mapping[str, Workload],
        context: AuthorizationContext,
    ) -> None:
        """Validate a proposed batch atomically; execute only after success."""

        proposed = tuple(actions)
        decisions = []
        for offset, action in enumerate(proposed):
            workload = workloads.get(action.workload_id)
            if workload is None:
                decisions.append(AuthorizationDecision(False, ("unknown workload is protected",)))
                continue
            decisions.append(self.assess(action, workload, context, offset))

        failures = [
            "action {}: {}".format(index, "; ".join(decision.reasons))
            for index, decision in enumerate(decisions)
            if not decision.authorized
        ]
        if failures:
            raise PolicyViolation(" | ".join(failures))

