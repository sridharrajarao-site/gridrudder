from dataclasses import dataclass, field
from enum import Enum
import math
from typing import List, Optional


def _require_nonempty_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(field_name))


def _require_int(value: object, field_name: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("{} must be an integer >= {}".format(field_name, minimum))


def _require_finite_number(value: object, field_name: str, minimum: float = 0.0) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be numeric".format(field_name))
    if not math.isfinite(float(value)) or float(value) < minimum:
        raise ValueError("{} must be finite and >= {}".format(field_name, minimum))


class Priority(str, Enum):
    CRITICAL = "critical"
    NORMAL = "normal"
    OPPORTUNISTIC = "opportunistic"


@dataclass(frozen=True)
class Flexibility:
    may_defer: bool = False
    may_power_cap: bool = False
    min_power_watts_per_gpu: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.may_defer, bool) or not isinstance(self.may_power_cap, bool):
            raise ValueError("flexibility flags must be boolean")
        if self.min_power_watts_per_gpu is not None:
            _require_finite_number(
                self.min_power_watts_per_gpu, "min_power_watts_per_gpu", minimum=0.0
            )
            if not self.may_power_cap:
                raise ValueError("a minimum power cap requires may_power_cap")
        elif self.may_power_cap:
            raise ValueError("may_power_cap requires min_power_watts_per_gpu")


@dataclass
class Workload:
    workload_id: str
    priority: Priority
    requested_gpus: int
    arrival_second: int
    work_units: float
    watts_per_gpu: float
    flexibility: Flexibility = field(default_factory=Flexibility)
    state: str = "queued"
    progress: float = 0.0
    current_cap_watts: Optional[float] = None

    def __post_init__(self) -> None:
        _require_nonempty_text(self.workload_id, "workload_id")
        if not isinstance(self.priority, Priority):
            raise ValueError("priority must be a Priority")
        _require_int(self.requested_gpus, "requested_gpus", minimum=1)
        _require_int(self.arrival_second, "arrival_second", minimum=0)
        _require_finite_number(self.work_units, "work_units", minimum=0.0)
        if float(self.work_units) == 0.0:
            raise ValueError("work_units must be greater than zero")
        _require_finite_number(self.watts_per_gpu, "watts_per_gpu", minimum=0.0)
        if float(self.watts_per_gpu) == 0.0:
            raise ValueError("watts_per_gpu must be greater than zero")
        if not isinstance(self.flexibility, Flexibility):
            raise ValueError("flexibility must be a Flexibility")
        if self.state not in {"queued", "running", "completed"}:
            raise ValueError("state must be queued, running, or completed")
        _require_finite_number(self.progress, "progress", minimum=0.0)
        if self.current_cap_watts is not None:
            _require_finite_number(self.current_cap_watts, "current_cap_watts", minimum=0.0)
            minimum = self.flexibility.min_power_watts_per_gpu
            if not self.flexibility.may_power_cap or minimum is None:
                raise ValueError("current_cap_watts requires authorized power capping")
            if self.current_cap_watts < minimum or self.current_cap_watts > self.watts_per_gpu:
                raise ValueError("current_cap_watts is outside workload bounds")

    @property
    def protected(self) -> bool:
        return self.priority == Priority.CRITICAL or not (
            self.flexibility.may_defer or self.flexibility.may_power_cap
        )

    def effective_watts_per_gpu(self) -> float:
        return self.watts_per_gpu if self.current_cap_watts is None else self.current_cap_watts

    def power_watts(self) -> float:
        if self.state != "running":
            return 0.0
        return self.requested_gpus * self.effective_watts_per_gpu()

    def advance(self, seconds: int = 1) -> None:
        _require_int(seconds, "seconds", minimum=1)
        if self.state != "running":
            return
        efficiency = self.effective_watts_per_gpu() / self.watts_per_gpu
        self.progress += self.requested_gpus * efficiency * seconds
        if self.progress >= self.work_units:
            self.state = "completed"


@dataclass(frozen=True)
class PowerEnvelope:
    effective_second: int
    max_facility_watts: float

    def __post_init__(self) -> None:
        _require_int(self.effective_second, "effective_second", minimum=0)
        _require_finite_number(self.max_facility_watts, "max_facility_watts", minimum=0.0)


@dataclass(frozen=True)
class Action:
    action_type: str
    workload_id: str
    value: Optional[float]
    reason: str

    def __post_init__(self) -> None:
        _require_nonempty_text(self.action_type, "action_type")
        _require_nonempty_text(self.workload_id, "workload_id")
        _require_nonempty_text(self.reason, "reason")
        if self.value is not None:
            _require_finite_number(self.value, "value", minimum=0.0)


@dataclass
class Snapshot:
    second: int
    envelope_watts: float
    facility_power_watts: float
    workloads: List[Workload]

    def __post_init__(self) -> None:
        _require_int(self.second, "second", minimum=0)
        _require_finite_number(self.envelope_watts, "envelope_watts", minimum=0.0)
        _require_finite_number(self.facility_power_watts, "facility_power_watts", minimum=0.0)
        if not isinstance(self.workloads, list):
            raise ValueError("workloads must be a list")
        identifiers = []
        for workload in self.workloads:
            if not isinstance(workload, Workload):
                raise ValueError("snapshot workloads must be Workload instances")
            identifiers.append(workload.workload_id)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("snapshot contains duplicate workload IDs")
