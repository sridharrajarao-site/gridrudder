import math
from typing import Dict, List

from .domain import Action, Snapshot, Workload


class SafetyViolation(RuntimeError):
    pass


class HeuristicController:
    """Deterministic, explainable reference controller.

    It first blocks flexible queued work, then caps running flexible work. It
    never changes a protected workload and restores caps gradually.
    """

    def __init__(self, reserve_watts: float = 100.0, recovery_step_watts: float = 25.0):
        for name, value in (
            ("reserve_watts", reserve_watts),
            ("recovery_step_watts", recovery_step_watts),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise ValueError("{} must be a finite non-negative number".format(name))
        self.reserve_watts = reserve_watts
        self.recovery_step_watts = recovery_step_watts

    def recommend(self, snapshot: Snapshot) -> List[Action]:
        target = snapshot.envelope_watts - self.reserve_watts
        excess = max(0.0, snapshot.facility_power_watts - target)
        actions: List[Action] = []

        if excess > 0:
            candidates = sorted(
                (w for w in snapshot.workloads if w.state == "running" and w.flexibility.may_power_cap),
                key=lambda w: (w.priority != w.priority.OPPORTUNISTIC, w.workload_id),
            )
            for workload in candidates:
                minimum = workload.flexibility.min_power_watts_per_gpu
                if minimum is None:
                    continue
                current = workload.effective_watts_per_gpu()
                reducible = max(0.0, (current - minimum) * workload.requested_gpus)
                if reducible <= 0:
                    continue
                reduction = min(excess, reducible)
                new_cap = current - reduction / workload.requested_gpus
                actions.append(Action("set_power_cap", workload.workload_id, new_cap, "power_envelope"))
                excess -= reduction
                if excess <= 0:
                    break
        else:
            headroom = target - snapshot.facility_power_watts
            candidates = sorted(
                (w for w in snapshot.workloads if w.state == "running" and w.current_cap_watts),
                key=lambda w: (w.priority == w.priority.OPPORTUNISTIC, w.workload_id),
            )
            for workload in candidates:
                desired_increase = min(
                    self.recovery_step_watts,
                    workload.watts_per_gpu - workload.effective_watts_per_gpu(),
                )
                total_increase = desired_increase * workload.requested_gpus
                if desired_increase > 0 and total_increase <= headroom:
                    new_cap = workload.effective_watts_per_gpu() + desired_increase
                    value = None if new_cap >= workload.watts_per_gpu else new_cap
                    actions.append(Action("set_power_cap", workload.workload_id, value, "rate_limited_recovery"))
                    headroom -= total_increase
        return actions

    def validate(self, actions: List[Action], workloads: Dict[str, Workload]) -> None:
        if not isinstance(actions, (list, tuple)):
            raise SafetyViolation("action plan must be a list or tuple")
        if not isinstance(workloads, dict):
            raise SafetyViolation("workloads must be a dictionary")
        seen_workload_ids = set()
        for action in actions:
            if not isinstance(action, Action):
                raise SafetyViolation("action plan contains an invalid action object")
            if not isinstance(action.workload_id, str) or not action.workload_id.strip():
                raise SafetyViolation("action workload identity is invalid")
            if not isinstance(action.action_type, str) or not action.action_type.strip():
                raise SafetyViolation("action type is invalid")
            if not isinstance(action.reason, str) or not action.reason.strip():
                raise SafetyViolation("action reason is invalid")
            if action.workload_id in seen_workload_ids:
                raise SafetyViolation("action plan contains duplicate or conflicting workload actions")
            seen_workload_ids.add(action.workload_id)
            workload = workloads.get(action.workload_id)
            if not isinstance(workload, Workload):
                raise SafetyViolation("action references an unknown workload")
            if workload.workload_id != action.workload_id:
                raise SafetyViolation("workload mapping identity mismatch")
            if action.action_type != "set_power_cap":
                raise SafetyViolation("unsupported action")
            if workload.protected:
                raise SafetyViolation("controller attempted to modify protected workload")
            if action.value is not None:
                if (
                    isinstance(action.value, bool)
                    or not isinstance(action.value, (int, float))
                    or not math.isfinite(float(action.value))
                ):
                    raise SafetyViolation("power cap must be a finite number or None")
                minimum = workload.flexibility.min_power_watts_per_gpu
                if (
                    not workload.flexibility.may_power_cap
                    or minimum is None
                    or isinstance(minimum, bool)
                    or not isinstance(minimum, (int, float))
                    or not math.isfinite(float(minimum))
                    or isinstance(workload.watts_per_gpu, bool)
                    or not isinstance(workload.watts_per_gpu, (int, float))
                    or not math.isfinite(float(workload.watts_per_gpu))
                ):
                    raise SafetyViolation("power cap not authorized")
                if action.value < minimum or action.value > workload.watts_per_gpu:
                    raise SafetyViolation("power cap outside authorized bounds")
            elif workload.current_cap_watts is None:
                raise SafetyViolation("uncapped workload has nothing to restore")
