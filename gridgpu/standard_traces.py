"""Primary trace producers for the four canonical standard scenarios."""

import copy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Tuple

from .benchmarks import ScenarioKind, canonical_scenarios
from .controller import HeuristicController
from .domain import Workload
from .simulator import Simulator
from .telemetry import FreshnessPolicy, MeterSnapshot, Quality, TelemetrySample, assess_meter_decision_eligibility


TRACE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StandardPrimaryTrace:
    schema_version: int
    scenario_id: str
    inputs: Mapping[str, Any]
    configuration: Mapping[str, Any]
    trace_rows: Tuple[Mapping[str, Any], ...]
    mutation_ledger: Tuple[Mapping[str, Any], ...]
    raw_facts: Mapping[str, Any]


def _workload_input(workload: Workload) -> Mapping[str, Any]:
    return {
        "workload_id": workload.workload_id,
        "priority": workload.priority.value,
        "requested_gpus": workload.requested_gpus,
        "arrival_second": workload.arrival_second,
        "work_units": workload.work_units,
        "watts_per_gpu": workload.watts_per_gpu,
        "flexibility": asdict(workload.flexibility),
        "initial_state": workload.state,
        "initial_cap_watts": workload.current_cap_watts,
        "protected": workload.protected,
    }


def _simulator_trace(scenario_id: str) -> StandardPrimaryTrace:
    scenario = next(item for item in canonical_scenarios() if item.kind.value == scenario_id)
    controller = HeuristicController(reserve_watts=100.0, recovery_step_watts=25.0)
    workloads = copy.deepcopy(scenario.workloads)
    simulator = Simulator(workloads, scenario.envelopes, controller)
    records = simulator.run(scenario.duration_seconds)
    retained_types = {
        "admission_intent", "admission_outcome", "decision", "action_intent",
        "action_outcome", "no_action", "shortfall", "sample",
    }
    trace_rows = tuple(copy.deepcopy(row) for row in records if row.get("type") in retained_types)
    mutation_ledger = tuple(
        {
            "sequence": index,
            "second": row["second"],
            "mutation_type": row["type"],
            "workload_id": row.get("workload_id", row.get("action", {}).get("workload_id")),
            "status": row.get("status", "applied"),
            "record": copy.deepcopy(row),
        }
        for index, row in enumerate(
            (item for item in records if item.get("type") in ("admission_outcome", "action_outcome")),
            1,
        )
    )
    inputs = {
        "duration_seconds": scenario.duration_seconds,
        "workloads": [_workload_input(item) for item in scenario.workloads],
        "envelopes": [asdict(item) for item in scenario.envelopes],
    }
    configuration = {
        "controller": {
            "type": type(controller).__name__,
            "reserve_watts": controller.reserve_watts,
            "recovery_step_watts": controller.recovery_step_watts,
        },
        "simulator": {
            "fixed_overhead_watts": simulator.fixed_overhead_watts,
            "cooling_ratio": simulator.cooling_ratio,
            "control_interval_seconds": simulator.control_interval_seconds,
        },
    }
    raw_facts = {
        "constrained_start_second": scenario.constrained_start_second,
        "constrained_end_second": scenario.constrained_end_second,
        "recovery_start_second": scenario.recovery_start_second,
        "settling_seconds": 5,
        "protected_workload_ids": sorted(item.workload_id for item in scenario.workloads if item.protected),
        "authorized_cap_bounds_watts_per_gpu": {
            item.workload_id: {
                "minimum": item.flexibility.min_power_watts_per_gpu,
                "maximum": item.watts_per_gpu,
            }
            for item in scenario.workloads
            if item.flexibility.may_power_cap
        },
        "recovery_maximum_facility_step_watts": 8.0 * 25.0 * 1.10,
    }
    return StandardPrimaryTrace(
        TRACE_SCHEMA_VERSION, scenario_id, inputs, configuration, trace_rows, mutation_ledger, raw_facts
    )


def _stale_meter_trace() -> StandardPrimaryTrace:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    policy = FreshnessPolicy(max_age_seconds=5.0)
    sample = TelemetrySample(
        timestamp_utc=now - timedelta(seconds=5.001),
        monotonic_sequence=1,
        source_id="pcc-meter-1",
        value=4_000.0,
        unit="W",
        quality=Quality.GOOD,
        ingest_latency_ms=50,
        source_epoch="epoch-1",
    )
    snapshot = MeterSnapshot(sample, "pcc-meter-1", maximum_watts=100_000.0)
    eligibility = assess_meter_decision_eligibility(snapshot, now, policy)
    operating_state = "SAFE_HOLD" if not eligibility.eligible else "AUTOMATIC"
    trace_rows = (
        {
            "type": "meter_observation",
            "timestamp_utc": sample.timestamp_utc.isoformat(),
            "evaluated_at_utc": now.isoformat(),
            "source_id": sample.source_id,
            "source_epoch": sample.source_epoch,
            "sequence": sample.monotonic_sequence,
            "value": sample.value,
            "unit": sample.unit,
            "quality": sample.quality.value,
            "ingest_latency_ms": sample.ingest_latency_ms,
            "clock_synchronized": snapshot.clock_synchronized,
        },
        {
            "type": "eligibility_decision",
            "eligible": eligibility.eligible,
            "reasons": list(eligibility.reasons),
            "next_state": operating_state,
            "new_actuation_count": 0 if not eligibility.eligible else 1,
        },
    )
    return StandardPrimaryTrace(
        TRACE_SCHEMA_VERSION,
        ScenarioKind.STALE_METER.value,
        {
            "authoritative_source_id": snapshot.authoritative_source_id,
            "maximum_watts": snapshot.maximum_watts,
            "sample_age_seconds": (now - sample.timestamp_utc).total_seconds(),
        },
        {
            "freshness_policy": {
                "max_age_seconds": policy.max_age_seconds,
                "max_future_skew_seconds": policy.max_future_skew_seconds,
                "max_ingest_latency_ms": policy.max_ingest_latency_ms,
            }
        },
        trace_rows,
        (),
        {
            "eligibility_reason_required": "meter sample is stale",
            "ineligible_state": "SAFE_HOLD",
        },
    )


def run_standard_primary_trace(scenario_id: str) -> StandardPrimaryTrace:
    supported = {kind.value for kind in ScenarioKind}
    if scenario_id not in supported:
        raise ValueError("unknown standard scenario: {}".format(scenario_id))
    if scenario_id == ScenarioKind.STALE_METER.value:
        return _stale_meter_trace()
    return _simulator_trace(scenario_id)


def run_all_standard_primary_traces() -> Tuple[StandardPrimaryTrace, ...]:
    return tuple(run_standard_primary_trace(kind.value) for kind in ScenarioKind)

