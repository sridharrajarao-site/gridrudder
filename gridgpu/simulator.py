import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .audit import AuditLog
from .controller import HeuristicController
from .domain import Action, PowerEnvelope, Snapshot, Workload


class Simulator:
    def __init__(
        self,
        workloads: Iterable[Workload],
        envelopes: Iterable[PowerEnvelope],
        controller: HeuristicController,
        fixed_overhead_watts: float = 1000.0,
        cooling_ratio: float = 0.10,
        control_interval_seconds: int = 5,
        audit_log: Optional[AuditLog] = None,
        audit_actor: str = "simulator",
        audit_policy: str = "heuristic-controller:v1",
    ):
        workload_list = list(workloads)
        workload_ids = [workload.workload_id for workload in workload_list]
        if len(set(workload_ids)) != len(workload_ids):
            raise ValueError("workload IDs must be unique")
        envelope_list = list(envelopes)
        envelope_times = [envelope.effective_second for envelope in envelope_list]
        if not envelope_list or 0 not in envelope_times:
            raise ValueError("an envelope must be effective at second zero")
        if len(set(envelope_times)) != len(envelope_times):
            raise ValueError("envelope effective seconds must be unique")
        if isinstance(fixed_overhead_watts, bool) or not isinstance(fixed_overhead_watts, (int, float)) or not math.isfinite(fixed_overhead_watts) or fixed_overhead_watts < 0:
            raise ValueError("fixed_overhead_watts must be finite and non-negative")
        if isinstance(cooling_ratio, bool) or not isinstance(cooling_ratio, (int, float)) or not math.isfinite(cooling_ratio) or cooling_ratio < 0:
            raise ValueError("cooling_ratio must be finite and non-negative")
        if isinstance(control_interval_seconds, bool) or not isinstance(control_interval_seconds, int) or control_interval_seconds <= 0:
            raise ValueError("control_interval_seconds must be a positive integer")
        if not isinstance(audit_actor, str) or not audit_actor.strip():
            raise ValueError("audit_actor must be non-empty")
        if not isinstance(audit_policy, str) or not audit_policy.strip():
            raise ValueError("audit_policy must be non-empty")
        self.workloads: Dict[str, Workload] = {w.workload_id: w for w in workload_list}
        self.envelopes = sorted(envelope_list, key=lambda e: e.effective_second)
        self.controller = controller
        self.fixed_overhead_watts = fixed_overhead_watts
        self.cooling_ratio = cooling_ratio
        self.control_interval_seconds = control_interval_seconds
        self.audit: List[dict] = []
        self.audit_log = audit_log
        self.audit_actor = audit_actor
        self.audit_policy = audit_policy
        self._has_run = False

    def _record(self, row: dict) -> None:
        """Record an event in memory and, when configured, durably.

        The existing in-memory shape remains unchanged so deterministic replay
        and callers comparing audit lists are not coupled to wall-clock audit
        metadata or hash-chain sequence numbers.
        """

        if self.audit_log is not None:
            payload = dict(row)
            payload["policy"] = self.audit_policy
            actor = (
                "{}:controller".format(self.audit_actor)
                if row["type"] != "sample"
                else "{}:telemetry".format(self.audit_actor)
            )
            self.audit_log.append(row["type"], payload, actor=actor)
        # Durable evidence is written first. An audit failure therefore stops
        # the control path before the event is treated as accepted in memory.
        self.audit.append(row)

    def envelope_at(self, second: int) -> float:
        applicable = [e for e in self.envelopes if e.effective_second <= second]
        if not applicable:
            raise ValueError("an envelope must be effective at second zero")
        return applicable[-1].max_facility_watts

    def facility_power(self) -> float:
        it_power = sum(w.power_watts() for w in self.workloads.values())
        return self.fixed_overhead_watts + it_power * (1.0 + self.cooling_ratio)

    def _admit(self, second: int, envelope: float) -> None:
        for workload in sorted(self.workloads.values(), key=lambda w: (w.priority.value, w.workload_id)):
            if workload.state != "queued" or workload.arrival_second > second:
                continue
            projected = self.facility_power() + workload.requested_gpus * workload.watts_per_gpu * (1 + self.cooling_ratio)
            if workload.protected or projected <= envelope - self.controller.reserve_watts:
                intent = {
                    "type": "admission_intent",
                    "second": second,
                    "workload_id": workload.workload_id,
                    "prior_state": workload.state,
                    "projected_power_watts": round(projected, 3),
                    "reason": "protected_workload" if workload.protected else "within_power_envelope",
                }
                self._record(intent)
                prior_state = workload.state
                workload.state = "running"
                try:
                    self._record({
                        "type": "admission_outcome",
                        "second": second,
                        "workload_id": workload.workload_id,
                        "prior_state": prior_state,
                        "state": workload.state,
                        "facility_power_watts": round(self.facility_power(), 3),
                    })
                except Exception:
                    workload.state = prior_state
                    raise

    def _apply(self, action: Action) -> None:
        workload = self.workloads[action.workload_id]
        workload.current_cap_watts = action.value

    def _protected_constraints(self) -> List[str]:
        return sorted(
            workload.workload_id
            for workload in self.workloads.values()
            if workload.state == "running" and workload.protected
        )

    def run(self, duration_seconds: int) -> List[dict]:
        if self._has_run:
            raise RuntimeError("Simulator instances are single-use; create a new instance for replay")
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or duration_seconds <= 0:
            raise ValueError("duration_seconds must be a positive integer")
        self._has_run = True
        for second in range(duration_seconds):
            envelope = self.envelope_at(second)
            self._admit(second, envelope)
            if second % self.control_interval_seconds == 0:
                snapshot = Snapshot(second, envelope, self.facility_power(), list(self.workloads.values()))
                actions = self.controller.recommend(snapshot)
                self.controller.validate(actions, self.workloads)
                self._record({
                    "type": "decision",
                    "second": second,
                    "envelope_watts": envelope,
                    "facility_power_watts": round(snapshot.facility_power_watts, 3),
                    "actions": [asdict(action) for action in actions],
                })
                for action in actions:
                    before = self.facility_power()
                    self._record({
                        "type": "action_intent",
                        "second": second,
                        "action": asdict(action),
                        "power_before_watts": round(before, 3),
                    })
                    workload = self.workloads[action.workload_id]
                    prior_cap = workload.current_cap_watts
                    self._apply(action)
                    try:
                        self._record({
                            "type": "action_outcome",
                            "second": second,
                            "action": asdict(action),
                            "status": "applied",
                            "power_before_watts": round(before, 3),
                            "power_after_watts": round(self.facility_power(), 3),
                        })
                    except Exception:
                        workload.current_cap_watts = prior_cap
                        raise
                protected_constraints = self._protected_constraints()
                shortfall_watts = max(0.0, self.facility_power() - envelope)
                if not actions:
                    self._record({
                        "type": "no_action",
                        "second": second,
                        "magnitude_watts": round(shortfall_watts, 3),
                        "reason": (
                            "no_authorized_flexibility"
                            if shortfall_watts > 0
                            else "no_control_action_required"
                        ),
                        "protected_constraints": protected_constraints,
                    })
                if shortfall_watts > 0:
                    self._record({
                        "type": "shortfall",
                        "second": second,
                        "magnitude_watts": round(shortfall_watts, 3),
                        "reason": "protected_or_non_flexible_load_prevents_compliance",
                        "protected_constraints": protected_constraints,
                        "envelope_watts": envelope,
                        "facility_power_watts": round(self.facility_power(), 3),
                    })
            # This sample represents power and workload state during the
            # [second, second + 1) interval. Progress/completion mutates only
            # after its energy has been recorded.
            self._record({
                "type": "sample",
                "second": second,
                "envelope_watts": envelope,
                "facility_power_watts": round(self.facility_power(), 3),
                "workloads": {
                    key: {"state": value.state, "progress": round(value.progress, 4), "cap_watts": value.current_cap_watts}
                    for key, value in sorted(self.workloads.items())
                },
            })
            for workload in self.workloads.values():
                workload.advance()
        return self.audit

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in self.audit))
