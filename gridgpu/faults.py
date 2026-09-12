"""Deterministic fault-injection primitives for control-plane tests.

Faults are addressed by logical step rather than wall time, making a run fully
replayable.  This module contains no scheduler or hardware write path.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


class FaultKind(str, Enum):
    METER_LOSS = "meter_loss"
    METER_STALE = "meter_stale"
    METER_DUPLICATE = "meter_duplicate"
    METER_REORDER = "meter_reorder"
    CLOCK_JUMP = "clock_jump"
    SCHEDULER_UNAVAILABLE = "scheduler_unavailable"
    SCHEDULER_REJECTION = "scheduler_rejection"
    ADAPTER_UNAVAILABLE = "adapter_unavailable"
    ADAPTER_REJECTION = "adapter_rejection"
    AUDIT_FAILURE = "audit_failure"
    CONTROLLER_RESTART = "controller_restart"
    SPLIT_BRAIN = "split_brain"
    MANUAL_CONFLICT = "manual_conflict"
    OPTIMIZER_TIMEOUT = "optimizer_timeout"
    OPTIMIZER_INVALID_OUTPUT = "optimizer_invalid_output"
    INTERRUPTED_RECOVERY = "interrupted_recovery"
    PROTECTED_MISLABEL = "protected_mislabel_attempt"


@dataclass(frozen=True)
class FaultInjection:
    step: int
    kind: FaultKind
    detail: str

    def __post_init__(self) -> None:
        if self.step < 0:
            raise ValueError("fault step must be non-negative")
        if not self.detail.strip():
            raise ValueError("fault detail must be non-empty")


class FaultInjector:
    """Consume a declared fault plan exactly once in deterministic order."""

    def __init__(self, injections: Iterable[FaultInjection]):
        ordered = tuple(sorted(injections, key=lambda item: (item.step, item.kind.value, item.detail)))
        keys = [(item.step, item.kind) for item in ordered]
        if len(keys) != len(set(keys)):
            raise ValueError("only one fault of each kind may occur at a step")
        self._pending: Dict[Tuple[int, FaultKind], FaultInjection] = {
            (item.step, item.kind): item for item in ordered
        }
        self._observed: List[FaultInjection] = []

    def trigger(self, step: int, kind: FaultKind) -> Optional[FaultInjection]:
        injection = self._pending.pop((step, kind), None)
        if injection is not None:
            self._observed.append(injection)
        return injection

    @property
    def observed(self) -> Tuple[FaultInjection, ...]:
        return tuple(self._observed)

    @property
    def pending(self) -> Tuple[FaultInjection, ...]:
        return tuple(sorted(self._pending.values(), key=lambda item: (item.step, item.kind.value)))

    def require_fully_consumed(self) -> None:
        if self._pending:
            names = ["{}@{}".format(item.kind.value, item.step) for item in self.pending]
            raise AssertionError("fault plan was not fully consumed: {}".format(", ".join(names)))


class DependencyFault(RuntimeError):
    def __init__(self, dependency: str, disposition: str):
        super().__init__("{} {}".format(dependency, disposition))
        self.dependency = dependency
        self.disposition = disposition


class InjectedDependency:
    """Read-only dependency probe that deterministically fails when injected."""

    def __init__(self, name: str, injector: FaultInjector, unavailable: FaultKind, rejected: FaultKind):
        self.name = name
        self.injector = injector
        self.unavailable = unavailable
        self.rejected = rejected
        self.call_count = 0

    def probe(self, step: int) -> str:
        self.call_count += 1
        if self.injector.trigger(step, self.unavailable):
            raise DependencyFault(self.name, "unavailable")
        if self.injector.trigger(step, self.rejected):
            raise DependencyFault(self.name, "rejected request")
        return "available"


@dataclass(frozen=True)
class LeaseDecision:
    authorized: bool
    evidence: str


class LeaseFence:
    """Minimal epoch fence used to prove that a stale controller cannot act."""

    def __init__(self) -> None:
        self._epoch = 0
        self._holder: Optional[str] = None

    def acquire(self, controller_id: str) -> int:
        if not controller_id.strip():
            raise ValueError("controller_id must be non-empty")
        self._epoch += 1
        self._holder = controller_id
        return self._epoch

    def assess(self, controller_id: str, epoch: int) -> LeaseDecision:
        if controller_id != self._holder or epoch != self._epoch:
            return LeaseDecision(False, "stale_controller_fenced")
        return LeaseDecision(True, "active_lease_verified")


def manual_precedence(manual_limit_watts: float, optimizer_limit_watts: float) -> Tuple[float, str]:
    if manual_limit_watts <= 0 or optimizer_limit_watts <= 0:
        raise ValueError("limits must be positive")
    return min(manual_limit_watts, optimizer_limit_watts), "stricter_manual_or_optimizer_limit_selected"


def validate_optimizer_output(output: object) -> Tuple[bool, str]:
    """Fail closed on malformed output; real action validation remains separate."""
    if not isinstance(output, Mapping):
        return False, "optimizer_output_not_mapping"
    actions = output.get("actions")
    if not isinstance(actions, list):
        return False, "optimizer_actions_not_list"
    if any(not isinstance(action, dict) for action in actions):
        return False, "optimizer_action_invalid"
    return True, "optimizer_output_structurally_valid"
