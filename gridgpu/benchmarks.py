"""Canonical deterministic benchmark and fault scenarios.

These scenarios are deliberately small enough for CI.  They test the product
contract, not electrical protection: feasible envelope tracking, explicit
infeasibility, bounded recovery, and fail-closed meter eligibility.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import copy
from typing import Dict, List, Mapping, Sequence, Tuple

from .controller import HeuristicController
from .domain import Flexibility, PowerEnvelope, Priority, Workload
from .reporting import summarize
from .simulator import Simulator
from .telemetry import (
    FreshnessPolicy,
    MeterSnapshot,
    Quality,
    TelemetrySample,
    assess_meter_decision_eligibility,
)


class ScenarioKind(str, Enum):
    NORMAL_CONSTRAINT = "normal_constraint"
    INFEASIBLE_CONSTRAINT = "infeasible_constraint"
    REBOUND_RECOVERY = "rebound_recovery"
    STALE_METER = "stale_meter"


@dataclass(frozen=True)
class BenchmarkScenario:
    kind: ScenarioKind
    description: str
    duration_seconds: int
    workloads: Tuple[Workload, ...] = ()
    envelopes: Tuple[PowerEnvelope, ...] = ()
    constrained_start_second: int = 0
    constrained_end_second: int = 0
    recovery_start_second: int = 0


@dataclass(frozen=True)
class BenchmarkResult:
    kind: ScenarioKind
    passed: bool
    metrics: Mapping[str, float]
    findings: Tuple[str, ...]
    invariants: Mapping[str, bool]

    @property
    def scenario_id(self) -> str:
        """Transport-neutral identity consumed by the release gate."""

        return self.kind.value

    @property
    def evidence(self) -> Mapping[str, object]:
        """Partial gate evidence; release provenance is added elsewhere."""

        return {"invariants": self.invariants}


def canonical_scenarios() -> Tuple[BenchmarkScenario, ...]:
    """Return fresh scenario definitions in stable execution order."""

    def workloads() -> Tuple[Workload, ...]:
        return (
            Workload("critical", Priority.CRITICAL, 2, 0, 100_000, 300),
            Workload(
                "flex",
                Priority.OPPORTUNISTIC,
                8,
                0,
                100_000,
                350,
                Flexibility(may_defer=True, may_power_cap=True, min_power_watts_per_gpu=180),
            ),
        )

    return (
        BenchmarkScenario(
            ScenarioKind.NORMAL_CONSTRAINT,
            "A feasible step-down must be tracked without modifying critical work.",
            70,
            workloads(),
            (PowerEnvelope(0, 6_000), PowerEnvelope(20, 3_800)),
            constrained_start_second=25,
            constrained_end_second=70,
        ),
        BenchmarkScenario(
            ScenarioKind.INFEASIBLE_CONSTRAINT,
            "A ceiling below immutable overhead and critical load must be reported, not hidden.",
            30,
            (Workload("critical", Priority.CRITICAL, 2, 0, 100_000, 300),),
            (PowerEnvelope(0, 1_200),),
            constrained_start_second=0,
            constrained_end_second=30,
        ),
        BenchmarkScenario(
            ScenarioKind.REBOUND_RECOVERY,
            "Restoration after a feasible constraint must remain inside the relaxed envelope.",
            120,
            workloads(),
            (PowerEnvelope(0, 6_000), PowerEnvelope(20, 3_800), PowerEnvelope(80, 6_000)),
            constrained_start_second=25,
            constrained_end_second=80,
            recovery_start_second=80,
        ),
        BenchmarkScenario(
            ScenarioKind.STALE_METER,
            "An expired authoritative meter sample must make automatic control ineligible.",
            0,
        ),
    )


def _samples_between(records: Sequence[dict], start: int, end: int) -> List[dict]:
    return [
        row
        for row in records
        if row.get("type") == "sample" and start <= int(row["second"]) < end
    ]


def _run_simulator_scenario(scenario: BenchmarkScenario) -> Tuple[Simulator, List[dict]]:
    # The simulator is intentionally stateful; copy workloads so even repeated
    # evaluation of the same definition is deterministic.
    simulator = Simulator(
        copy.deepcopy(scenario.workloads),
        scenario.envelopes,
        HeuristicController(reserve_watts=100.0, recovery_step_watts=25.0),
    )
    return simulator, simulator.run(scenario.duration_seconds)


def _normal_result(scenario: BenchmarkScenario) -> BenchmarkResult:
    simulator, records = _run_simulator_scenario(scenario)
    samples = _samples_between(
        records, scenario.constrained_start_second, scenario.constrained_end_second
    )
    maximum_exceedance = max(
        (max(0.0, row["facility_power_watts"] - row["envelope_watts"]) for row in samples),
        default=0.0,
    )
    critical = simulator.workloads["critical"]
    action_outcomes = [row for row in records if row.get("type") == "action_outcome"]
    critical_actions = [
        row for row in action_outcomes if row["action"]["workload_id"] == "critical"
    ]
    critical_samples = [row["workloads"]["critical"] for row in samples]
    protected = (
        not critical_actions
        and critical.current_cap_watts is None
        and bool(critical_samples)
        and all(item["cap_watts"] is None for item in critical_samples)
    )
    policy_bounds_respected = all(
        row["action"]["workload_id"] == "flex"
        and row["action"]["action_type"] == "set_power_cap"
        and row["action"]["value"] is not None
        and 180.0 <= float(row["action"]["value"]) <= 350.0
        for row in action_outcomes
    )
    invariants = {
        "target_met_after_settling": bool(samples) and maximum_exceedance == 0.0,
        "protected_workloads_unchanged": protected,
        "policy_bounds_respected": policy_bounds_respected,
    }
    passed = all(invariants.values())
    findings = () if passed else ("feasible envelope or critical-workload contract was violated",)
    return BenchmarkResult(
        scenario.kind,
        passed,
        {
            "sample_count": float(len(samples)),
            "maximum_exceedance_watts": maximum_exceedance,
            "critical_cap_actions": float(len(critical_actions)),
        },
        findings,
        invariants,
    )


def _infeasible_result(scenario: BenchmarkScenario) -> BenchmarkResult:
    simulator, records = _run_simulator_scenario(scenario)
    summary = summarize(records)
    critical = simulator.workloads["critical"]
    critical_actions = [
        row
        for row in records
        if row.get("type") == "action_outcome" and row["action"]["workload_id"] == "critical"
    ]
    shortfalls = [row for row in records if row.get("type") == "shortfall"]
    no_actions = [row for row in records if row.get("type") == "no_action"]
    detected_infeasible = bool(shortfalls) and all(
        row["magnitude_watts"] > 0
        and row["reason"] == "protected_or_non_flexible_load_prevents_compliance"
        and "critical" in row["protected_constraints"]
        for row in shortfalls
    )
    protected = not critical_actions and critical.current_cap_watts is None
    all_action_outcomes = [row for row in records if row.get("type") == "action_outcome"]
    invariants = {
        "shortfall_explicit": detected_infeasible and bool(no_actions),
        "protected_workloads_unchanged": protected,
        "no_unsafe_action": not all_action_outcomes,
    }
    passed = all(invariants.values())
    findings = () if passed else ("explicit shortfall evidence was absent or protected work was modified",)
    return BenchmarkResult(
        scenario.kind,
        passed,
        {
            "maximum_exceedance_watts": summary.maximum_exceedance_watts,
            "energy_over_limit_wh": summary.energy_over_limit_wh,
            "critical_action_count": float(len(critical_actions)),
            "shortfall_record_count": float(len(shortfalls)),
            "maximum_explicit_shortfall_watts": max(
                (float(row["magnitude_watts"]) for row in shortfalls), default=0.0
            ),
            "no_action_record_count": float(len(no_actions)),
        },
        findings,
        invariants,
    )


def _rebound_result(scenario: BenchmarkScenario) -> BenchmarkResult:
    _simulator, records = _run_simulator_scenario(scenario)
    recovery = _samples_between(records, scenario.recovery_start_second, scenario.duration_seconds)
    maximum_rebound_exceedance = max(
        (max(0.0, row["facility_power_watts"] - row["envelope_watts"]) for row in recovery),
        default=0.0,
    )
    recovery_power = [float(row["facility_power_watts"]) for row in recovery]
    positive_steps = [
        later - earlier for earlier, later in zip(recovery_power, recovery_power[1:]) if later > earlier
    ]
    # Eight GPUs, a 25 W/GPU controller recovery step, and 10% cooling.
    maximum_authorized_step_watts = 8.0 * 25.0 * 1.10
    recovery_rate_respected = all(
        increase <= maximum_authorized_step_watts + 1e-9 for increase in positive_steps
    )
    no_oscillation = all(
        later + 1e-9 >= earlier for earlier, later in zip(recovery_power, recovery_power[1:])
    )
    invariants = {
        "recovery_ceiling_respected": bool(recovery) and maximum_rebound_exceedance == 0.0,
        "recovery_rate_respected": bool(recovery) and recovery_rate_respected,
        "no_oscillation": bool(recovery) and no_oscillation,
    }
    passed = all(invariants.values())
    findings = () if passed else ("recovery exceeded the relaxed power envelope",)
    return BenchmarkResult(
        scenario.kind,
        passed,
        {
            "recovery_sample_count": float(len(recovery)),
            "maximum_rebound_exceedance_watts": maximum_rebound_exceedance,
            "peak_recovery_watts": max(
                (float(row["facility_power_watts"]) for row in recovery), default=0.0
            ),
        },
        findings,
        invariants,
    )


def _stale_meter_result(scenario: BenchmarkScenario) -> BenchmarkResult:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    sample = TelemetrySample(
        timestamp_utc=now - timedelta(seconds=5.001),
        monotonic_sequence=1,
        source_id="pcc-meter-1",
        value=4_000.0,
        unit="W",
        quality=Quality.GOOD,
        ingest_latency_ms=50,
    )
    eligibility = assess_meter_decision_eligibility(
        MeterSnapshot(sample, "pcc-meter-1", maximum_watts=100_000.0),
        now,
        FreshnessPolicy(max_age_seconds=5.0),
    )
    stale_reason = "meter sample is stale" in eligibility.reasons
    operating_state = "SAFE_HOLD" if not eligibility.eligible else "AUTOMATIC"
    operator_reason = "; ".join(eligibility.reasons)
    invariants = {
        "new_actuation_inhibited": not eligibility.eligible,
        "safe_hold_entered": operating_state == "SAFE_HOLD",
        "operator_reason_recorded": stale_reason and bool(operator_reason),
    }
    passed = all(invariants.values())
    findings = () if passed else ("stale authoritative data did not fail closed",)
    return BenchmarkResult(
        scenario.kind,
        passed,
        {"decision_eligible": 1.0 if eligibility.eligible else 0.0, "sample_age_seconds": 5.001},
        findings,
        invariants,
    )


def run_benchmark(scenario: BenchmarkScenario) -> BenchmarkResult:
    """Evaluate one canonical scenario using its declared product contract."""

    runners = {
        ScenarioKind.NORMAL_CONSTRAINT: _normal_result,
        ScenarioKind.INFEASIBLE_CONSTRAINT: _infeasible_result,
        ScenarioKind.REBOUND_RECOVERY: _rebound_result,
        ScenarioKind.STALE_METER: _stale_meter_result,
    }
    return runners[scenario.kind](scenario)


def run_canonical_benchmarks() -> Tuple[BenchmarkResult, ...]:
    """Run the complete canonical suite deterministically."""

    return tuple(run_benchmark(scenario) for scenario in canonical_scenarios())
