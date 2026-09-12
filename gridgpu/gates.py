"""Executable, transport-neutral release-gate evaluation.

The evaluator intentionally imports no benchmark or fault-scenario module.  A
producer may supply mappings or ordinary objects with the documented fields.
Gate evaluation is strict and fail-closed; it does not infer evidence from a
producer's boolean ``passed`` claim.
"""

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMON_EVIDENCE = (
    "artifact_version",
    "configuration_digest",
    "policy_version",
    "input_digest",
    "audit_head_hash",
    "raw_data_reference",
    "primary_trace_digest",
)


@dataclass(frozen=True)
class MetricPredicate:
    """Independent semantic rule evaluated by the gate, not the producer."""

    rule_id: str
    description: str
    evaluate: Callable[[Mapping[str, float]], bool]


@dataclass(frozen=True)
class ScenarioRequirement:
    scenario_id: str
    description: str
    required_metrics: Tuple[str, ...]
    required_invariants: Tuple[str, ...]
    metric_predicates: Tuple[MetricPredicate, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    go: bool
    reasons: Tuple[str, ...]
    required_scenario_count: int
    received_scenario_count: int
    missing_scenario_ids: Tuple[str, ...]


def _requirement(
    scenario_id: str,
    description: str,
    metrics: Sequence[str],
    invariants: Sequence[str],
    predicates: Sequence[MetricPredicate],
) -> ScenarioRequirement:
    return ScenarioRequirement(
        scenario_id, description, tuple(metrics), tuple(invariants), tuple(predicates)
    )


def _rule(rule_id: str, description: str, evaluate: Callable[[Mapping[str, float]], bool]) -> MetricPredicate:
    return MetricPredicate(rule_id, description, evaluate)


def _equals(name: str, expected: float) -> MetricPredicate:
    return _rule(
        "{}_equals_{}".format(name, expected),
        "{} must equal {}".format(name, expected),
        lambda metrics: float(metrics[name]) == expected,
    )


def _positive(name: str) -> MetricPredicate:
    return _rule(
        "{}_positive".format(name),
        "{} must be greater than zero".format(name),
        lambda metrics: float(metrics[name]) > 0.0,
    )


def _fault_rules(forbidden_metric: str) -> Tuple[MetricPredicate, ...]:
    return (_equals("fault_count", 1.0), _equals(forbidden_metric, 0.0))


REQUIRED_SCENARIOS = (
    _requirement(
        "normal_constraint",
        "Feasible envelope tracking.",
        ("sample_count", "maximum_exceedance_watts", "critical_cap_actions"),
        ("target_met_after_settling", "protected_workloads_unchanged", "policy_bounds_respected"),
        (_positive("sample_count"), _equals("maximum_exceedance_watts", 0.0), _equals("critical_cap_actions", 0.0)),
    ),
    _requirement(
        "infeasible_constraint",
        "Quantified shortfall without unsafe action.",
        ("maximum_exceedance_watts", "maximum_explicit_shortfall_watts", "shortfall_record_count"),
        ("shortfall_explicit", "protected_workloads_unchanged", "no_unsafe_action"),
        (
            _positive("maximum_exceedance_watts"),
            _positive("maximum_explicit_shortfall_watts"),
            _positive("shortfall_record_count"),
            _rule(
                "shortfall_matches_exceedance",
                "maximum explicit shortfall must equal maximum observed exceedance",
                lambda metrics: math.isclose(
                    float(metrics["maximum_explicit_shortfall_watts"]),
                    float(metrics["maximum_exceedance_watts"]),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ),
            ),
        ),
    ),
    _requirement(
        "rebound_recovery",
        "Bounded, staged recovery.",
        ("recovery_sample_count", "maximum_rebound_exceedance_watts", "peak_recovery_watts"),
        ("recovery_ceiling_respected", "recovery_rate_respected", "no_oscillation"),
        (
            _positive("recovery_sample_count"),
            _equals("maximum_rebound_exceedance_watts", 0.0),
            _rule("peak_recovery_nonnegative", "peak recovery power must be non-negative", lambda metrics: float(metrics["peak_recovery_watts"]) >= 0.0),
        ),
    ),
    _requirement(
        "stale_meter",
        "Stale authoritative data inhibits control.",
        ("decision_eligible", "sample_age_seconds"),
        ("new_actuation_inhibited", "safe_hold_entered", "operator_reason_recorded"),
        (_equals("decision_eligible", 0.0), _positive("sample_age_seconds")),
    ),
    _requirement(
        "meter_loss",
        "Loss of the authoritative meter during an event.",
        ("fault_count", "actions_after_fault"),
        ("new_actuation_inhibited", "safe_hold_entered", "operator_alert_recorded"),
        _fault_rules("actions_after_fault"),
    ),
    _requirement(
        "meter_stale",
        "Injected stale authoritative meter sample.",
        ("fault_count", "actions_after_fault"),
        ("new_actuation_inhibited", "safe_hold_entered", "operator_reason_recorded"),
        _fault_rules("actions_after_fault"),
    ),
    _requirement(
        "meter_duplicate",
        "Duplicate meter sequence/replay.",
        ("fault_count", "accepted_fault_count"),
        ("duplicate_rejected", "cursor_not_advanced", "new_actuation_inhibited"),
        _fault_rules("accepted_fault_count"),
    ),
    _requirement(
        "meter_reorder",
        "Regressed or reordered meter sequence.",
        ("fault_count", "accepted_fault_count"),
        ("regression_rejected", "cursor_not_advanced", "new_actuation_inhibited"),
        _fault_rules("accepted_fault_count"),
    ),
    _requirement(
        "clock_jump",
        "Future, backward, or unsynchronized meter clock.",
        ("fault_count", "accepted_fault_count"),
        ("clock_fault_rejected", "new_actuation_inhibited", "operator_reason_recorded"),
        _fault_rules("accepted_fault_count"),
    ),
    _requirement(
        "optimizer_timeout",
        "Planner exceeds its decision deadline.",
        ("fault_count", "actions_from_partial_plan"),
        ("no_partial_plan_executed", "approved_fallback_selected", "timeout_audited"),
        _fault_rules("actions_from_partial_plan"),
    ),
    _requirement(
        "optimizer_invalid_output",
        "Planner returns malformed or unsafe output.",
        ("fault_count", "invalid_actions_applied"),
        ("invalid_plan_rejected", "approved_fallback_selected", "validation_reason_audited"),
        _fault_rules("invalid_actions_applied"),
    ),
    _requirement(
        "scheduler_unavailable",
        "Scheduler is unavailable.",
        ("fault_count", "workload_actions_after_fault"),
        ("workload_mutation_inhibited", "protected_workloads_unchanged", "outage_audited"),
        _fault_rules("workload_actions_after_fault"),
    ),
    _requirement(
        "scheduler_rejection",
        "Scheduler rejects a request.",
        ("fault_count", "workload_actions_after_fault"),
        ("workload_mutation_inhibited", "rejection_not_assumed_success", "failure_audited"),
        _fault_rules("workload_actions_after_fault"),
    ),
    _requirement(
        "adapter_unavailable",
        "Actuator adapter is unavailable.",
        ("fault_count", "commands_assumed_applied"),
        ("command_not_assumed_applied", "no_mutation", "failure_audited"),
        _fault_rules("commands_assumed_applied"),
    ),
    _requirement(
        "adapter_rejection",
        "Actuator adapter rejects a request.",
        ("fault_count", "commands_assumed_applied"),
        ("command_not_assumed_applied", "no_mutation", "failure_audited"),
        _fault_rules("commands_assumed_applied"),
    ),
    _requirement(
        "audit_failure",
        "Audit append fails before intent can be durably recorded.",
        ("fault_count", "mutations_after_fault"),
        ("mutation_prevented", "no_mutation", "failure_surfaced"),
        _fault_rules("mutations_after_fault"),
    ),
    _requirement(
        "controller_restart",
        "Controller restarts with an event in progress.",
        ("fault_count", "replayed_expired_commands"),
        ("state_reconstructed_from_evidence", "expired_commands_not_replayed", "operator_resume_required"),
        _fault_rules("replayed_expired_commands"),
    ),
    _requirement(
        "split_brain",
        "Two controllers attempt to command one site.",
        ("fault_count", "unfenced_command_count"),
        ("single_writer_enforced", "stale_writer_fenced", "conflict_audited"),
        _fault_rules("unfenced_command_count"),
    ),
    _requirement(
        "manual_conflict",
        "Manual/site action conflicts with the controller.",
        ("fault_count", "automatic_overrides_of_manual"),
        ("manual_control_wins", "automatic_event_cancelled", "conflict_audited"),
        _fault_rules("automatic_overrides_of_manual"),
    ),
    _requirement(
        "interrupted_recovery",
        "Recovery is interrupted by a new fault or constraint.",
        ("fault_count", "recovery_increases_after_fault"),
        ("recovery_increase_inhibited", "recovery_hold_entered", "interruption_audited"),
        _fault_rules("recovery_increases_after_fault"),
    ),
    _requirement(
        "protected_mislabel_attempt",
        "A protected workload is maliciously or accidentally marked flexible.",
        ("fault_count", "protected_actions_applied"),
        ("protected_workload_rejected", "protected_workloads_unchanged", "validation_reason_audited"),
        _fault_rules("protected_actions_applied"),
    ),
)


def _field(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _scenario_id(value: Any) -> Optional[str]:
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _valid_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_evidence(
    scenario_id: str, evidence: Any, requirement: Optional[ScenarioRequirement]
) -> Tuple[str, ...]:
    reasons = []
    if not isinstance(evidence, Mapping):
        return ("{}: evidence must be a mapping".format(scenario_id),)
    for field_name in _COMMON_EVIDENCE:
        value = evidence.get(field_name)
        if not _valid_nonempty_string(value):
            reasons.append("{}: evidence.{} is missing or empty".format(scenario_id, field_name))
    audit_hash = evidence.get("audit_head_hash")
    if _valid_nonempty_string(audit_hash) and not _SHA256_PATTERN.fullmatch(audit_hash):
        reasons.append("{}: evidence.audit_head_hash is not lowercase SHA-256".format(scenario_id))
    trace_digest = evidence.get("primary_trace_digest")
    if _valid_nonempty_string(trace_digest) and not _DIGEST_PATTERN.fullmatch(trace_digest):
        reasons.append("{}: evidence.primary_trace_digest is not prefixed SHA-256".format(scenario_id))
    invariants = evidence.get("invariants")
    if not isinstance(invariants, Mapping):
        reasons.append("{}: evidence.invariants must be a mapping".format(scenario_id))
    verifier = evidence.get("trace_verifier")
    verifier_facts = verifier.get("facts") if isinstance(verifier, Mapping) else None
    if not isinstance(verifier, Mapping):
        reasons.append("{}: evidence.trace_verifier must be a mapping".format(scenario_id))
    else:
        if not _valid_nonempty_string(verifier.get("verifier_id")):
            reasons.append("{}: trace verifier identity is missing".format(scenario_id))
        if not _valid_nonempty_string(verifier.get("verifier_version")):
            reasons.append("{}: trace verifier version is missing".format(scenario_id))
        if verifier.get("primary_trace_digest") != trace_digest:
            reasons.append("{}: trace verifier digest does not match primary trace".format(scenario_id))
        if not isinstance(verifier_facts, Mapping):
            reasons.append("{}: trace verifier facts must be a mapping".format(scenario_id))
    if requirement is not None:
        for invariant in requirement.required_invariants:
            if not isinstance(invariants, Mapping) or invariants.get(invariant) is not True:
                reasons.append(
                    "{}: producer invariant {} is absent or not true".format(
                        scenario_id, invariant
                    )
                )
            if not isinstance(verifier_facts, Mapping) or verifier_facts.get(invariant) is not True:
                reasons.append(
                    "{}: trace verifier did not independently prove {}".format(
                        scenario_id, invariant
                    )
                )
    return tuple(reasons)


def _validate_metrics(
    scenario_id: str, metrics: Any, requirement: Optional[ScenarioRequirement]
) -> Tuple[str, ...]:
    if not isinstance(metrics, Mapping):
        return ("{}: metrics must be a mapping".format(scenario_id),)
    reasons = []
    if requirement is not None:
        for metric in requirement.required_metrics:
            if metric not in metrics:
                reasons.append("{}: required metric {} is absent".format(scenario_id, metric))
    for metric, value in metrics.items():
        if not _valid_nonempty_string(metric):
            reasons.append("{}: metric name is invalid".format(scenario_id))
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            reasons.append("{}: metric {} is not a finite number".format(scenario_id, metric))
    return tuple(reasons)


def _validate_metric_predicates(
    scenario_id: str, metrics: Any, requirement: Optional[ScenarioRequirement]
) -> Tuple[str, ...]:
    if requirement is None or not isinstance(metrics, Mapping):
        return ()
    reasons = []
    for predicate in requirement.metric_predicates:
        if not isinstance(predicate, MetricPredicate) or not callable(predicate.evaluate):
            reasons.append("{}: gate metric predicate is malformed".format(scenario_id))
            continue
        try:
            satisfied = predicate.evaluate(metrics)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reasons.append(
                "{}: metric rule {} could not be evaluated: {}".format(
                    scenario_id, predicate.rule_id, exc
                )
            )
            continue
        if satisfied is not True:
            reasons.append(
                "{}: metric rule {} failed: {}".format(
                    scenario_id, predicate.rule_id, predicate.description
                )
            )
    return tuple(reasons)


def evaluate_gate_b(
    results: Iterable[Any],
    requirements: Sequence[ScenarioRequirement] = REQUIRED_SCENARIOS,
) -> GateDecision:
    """Evaluate Gate B coverage and evidence without trusting producer types.

    Additional well-formed results are allowed, but they receive the same common
    evidence validation.  Duplicate IDs are always a NO-GO because choosing one
    would make gate output depend on result order.
    """

    reasons = []
    try:
        supplied = list(results)
    except (TypeError, RuntimeError) as exc:
        return GateDecision(
            False,
            ("results are not a readable iterable: {}".format(exc),),
            len(requirements),
            0,
            tuple(sorted(requirement.scenario_id for requirement in requirements)),
        )

    requirement_by_id = {}
    for requirement in requirements:
        if not isinstance(requirement, ScenarioRequirement):
            reasons.append("gate requirement is malformed")
            continue
        if requirement.scenario_id in requirement_by_id:
            reasons.append("gate requirement ID is duplicated: {}".format(requirement.scenario_id))
        requirement_by_id[requirement.scenario_id] = requirement

    seen = set()
    for index, result in enumerate(supplied):
        scenario_id = _scenario_id(_field(result, "scenario_id"))
        if scenario_id is None:
            scenario_id = _scenario_id(_field(result, "kind"))
        if scenario_id is None:
            reasons.append("result {}: scenario ID is missing or invalid".format(index))
            continue
        if scenario_id in seen:
            reasons.append("duplicate scenario result: {}".format(scenario_id))
            continue
        seen.add(scenario_id)
        requirement = requirement_by_id.get(scenario_id)

        passed = _field(result, "passed")
        if passed is not True:
            reasons.append("{}: result did not pass with boolean true".format(scenario_id))

        findings = _field(result, "findings")
        if not isinstance(findings, (list, tuple)) or any(
            not _valid_nonempty_string(finding) for finding in findings
        ):
            reasons.append("{}: findings must be a list/tuple of non-empty strings".format(scenario_id))
        elif findings:
            reasons.append("{}: result contains unresolved findings".format(scenario_id))

        metrics = _field(result, "metrics")
        reasons.extend(_validate_metrics(scenario_id, metrics, requirement))
        reasons.extend(_validate_metric_predicates(scenario_id, metrics, requirement))
        reasons.extend(_validate_evidence(scenario_id, _field(result, "evidence"), requirement))

    missing = tuple(sorted(set(requirement_by_id) - seen))
    for scenario_id in missing:
        reasons.append("required scenario is absent: {}".format(scenario_id))

    return GateDecision(
        go=not reasons,
        reasons=tuple(reasons),
        required_scenario_count=len(requirement_by_id),
        received_scenario_count=len(seen),
        missing_scenario_ids=missing,
    )
