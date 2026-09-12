"""Independent verification of retained Gate-B primary traces.

This module deliberately does not consume producer ``passed``, ``findings``,
``metrics`` or ``invariants`` fields.  Its output is derived from the retained
rows and ledgers and can be bound into release evidence.
"""

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Any, Dict, Mapping, Sequence, Tuple

from .gates import REQUIRED_SCENARIOS


VERIFIER_ID = "gridgpu-independent-primary-trace"
VERIFIER_VERSION = "1"
TRACE_SCHEMA_VERSION = 1
_STANDARD_IDS = frozenset(("normal_constraint", "infeasible_constraint", "rebound_recovery", "stale_meter"))
_FAULT_REQUIREMENTS = {
    item.scenario_id: item for item in REQUIRED_SCENARIOS if item.scenario_id not in _STANDARD_IDS
}
_FAULT_TRACE_SIGNATURES = {
    "meter_loss": (("safe_hold", "entered", "authoritative_meter_missing"),),
    "meter_stale": (("safe_hold", "entered", "meter sample is stale"),),
    "meter_duplicate": (("meter", "primed", "authoritative_sequence_accepted"), ("safe_hold", "entered", "duplicate sequence")),
    "meter_reorder": (("meter", "primed", "authoritative_sequence_accepted"), ("safe_hold", "entered", "sequence regression")),
    "clock_jump": (("safe_hold", "entered", "meter clock is not synchronized"),),
    "scheduler_unavailable": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("audit", "intent_durable", "flex"), ("safe_hold", "entered", "scheduler unavailable")),
    "scheduler_rejection": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("audit", "intent_durable", "flex"), ("safe_hold", "entered", "scheduler rejected request")),
    "adapter_unavailable": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("audit", "intent_durable", "flex"), ("safe_hold", "entered", "adapter unavailable")),
    "adapter_rejection": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("audit", "intent_durable", "flex"), ("safe_hold", "entered", "adapter rejected request")),
    "audit_failure": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("safe_hold", "entered", "audit_intent_failed: injected audit failure")),
    "controller_restart": (("restart", "safe_hold", "operator_resume_required"),),
    "split_brain": (("safe_hold", "entered", "stale_controller_fenced"),),
    "manual_conflict": (("safe_hold", "entered", "stricter_manual_or_optimizer_limit_selected:1100"),),
    "optimizer_timeout": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "fallback", "optimizer_deadline_exceeded"), ("planner", "complete", "deterministic_plan_created"), ("validation", "accepted", "independent_policy_guard_passed"), ("audit", "intent_durable", "flex"), ("outcome", "observed", "mutation_observed")),
    "optimizer_invalid_output": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("safe_hold", "entered", "optimizer_output_invalid")),
    "interrupted_recovery": (("safe_hold", "entered", "initial_hold"), ("safe_hold", "entered", "recovery_interrupted")),
    "protected_mislabel_attempt": (("meter", "accepted", "authoritative_meter_reconciled"), ("authorization", "approved", "explicit_operator_approval_verified"), ("planner", "complete", "deterministic_plan_created"), ("safe_hold", "entered", "validation_rejected: controller attempted to modify protected workload")),
}


class TraceVerificationError(ValueError):
    """The retained trace cannot independently prove its claims."""


@dataclass(frozen=True)
class TraceVerification:
    verifier_id: str
    verifier_version: str
    primary_trace_digest: str
    scenario_id: str
    metrics: Mapping[str, float]
    facts: Mapping[str, bool]

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "primary_trace_digest": self.primary_trace_digest,
            "scenario_id": self.scenario_id,
            "metrics": dict(self.metrics),
            "facts": dict(self.facts),
        }


def _mapping(value: Any) -> Dict[str, Any]:
    if is_dataclass(value):
        value = asdict(value)
    elif hasattr(value, "as_mapping") and callable(value.as_mapping):
        value = value.as_mapping()
    if not isinstance(value, Mapping):
        raise TraceVerificationError("primary trace packet must be a mapping")
    return dict(value)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TraceVerificationError("trace is not canonical JSON: {}".format(exc))


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise TraceVerificationError("{} must be a finite number".format(path))
    return float(value)


def _rows(value: Any, path: str, nonempty: bool = True) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or (nonempty and not value):
        raise TraceVerificationError("{} must be {}list/tuple".format(path, "a non-empty " if nonempty else "a "))
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise TraceVerificationError("{}[{}] must be a mapping".format(path, index))
        result.append(dict(row))
    return tuple(result)


def _contiguous(rows: Sequence[Mapping[str, Any]], path: str, start: int = 0) -> None:
    for index, row in enumerate(rows):
        if row.get("sequence") != index + start:
            raise TraceVerificationError("{} sequence is missing, duplicated, or reordered at {}".format(path, index))


def _digest(packet: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(packet)).hexdigest()


def verify_primary_trace(value: Any, expected_scenario_id: str = None) -> TraceVerification:
    packet = _mapping(value)
    scenario_id = packet.get("scenario_id")
    if not isinstance(scenario_id, str) or scenario_id not in _STANDARD_IDS | frozenset(_FAULT_REQUIREMENTS):
        raise TraceVerificationError("unknown or missing scenario_id")
    if expected_scenario_id is not None and scenario_id != expected_scenario_id:
        raise TraceVerificationError("scenario ID mismatch")
    _canonical(packet)  # reject NaN and non-JSON values before interpretation
    if scenario_id in _STANDARD_IDS:
        metrics, facts = _verify_standard(packet, scenario_id)
    else:
        metrics, facts = _verify_fault(packet, scenario_id)
    requirement = next(item for item in REQUIRED_SCENARIOS if item.scenario_id == scenario_id)
    if set(metrics) != set(requirement.required_metrics):
        raise TraceVerificationError("verifier metric contract mismatch")
    if set(facts) != set(requirement.required_invariants):
        raise TraceVerificationError("verifier invariant contract mismatch")
    for name, metric in metrics.items():
        _finite(metric, "derived metric {}".format(name))
    return TraceVerification(
        VERIFIER_ID, VERIFIER_VERSION, _digest(packet), scenario_id, metrics, facts
    )


def _verify_standard(packet: Mapping[str, Any], scenario_id: str):
    if packet.get("schema_version") != TRACE_SCHEMA_VERSION:
        raise TraceVerificationError("unsupported standard trace schema version")
    if set(("inputs", "configuration", "trace_rows", "mutation_ledger", "raw_facts")) - set(packet):
        raise TraceVerificationError("standard trace schema is incomplete")
    inputs = _mapping(packet["inputs"])
    raw = _mapping(packet["raw_facts"])
    rows = _rows(packet["trace_rows"], "trace_rows")
    ledger = _rows(packet["mutation_ledger"], "mutation_ledger", nonempty=False)
    _validate_standard_rows(rows, ledger, inputs, scenario_id)
    if scenario_id == "stale_meter":
        return _verify_stale(rows, inputs, packet["configuration"], raw)
    samples = [row for row in rows if row.get("type") == "sample"]
    start = int(_finite(raw.get("constrained_start_second"), "constrained_start_second"))
    end = int(_finite(raw.get("constrained_end_second"), "constrained_end_second"))
    constrained = [row for row in samples if start <= row["second"] < end]
    protected_ids = raw.get("protected_workload_ids")
    if not isinstance(protected_ids, list) or len(protected_ids) != len(set(protected_ids)):
        raise TraceVerificationError("protected workload identities are malformed")
    actions = [row for row in rows if row.get("type") == "action_outcome" and row.get("status", "applied") == "applied"]
    protected_actions = [row for row in actions if row.get("action", {}).get("workload_id") in protected_ids]
    protected_unchanged = not protected_actions and all(
        all(row.get("workloads", {}).get(item, {}).get("cap_watts") is None for item in protected_ids)
        for row in samples
    )
    if scenario_id == "normal_constraint":
        exceed = max((max(0.0, _finite(row.get("facility_power_watts"), "facility power") - _finite(row.get("envelope_watts"), "envelope")) for row in constrained), default=0.0)
        bounds = _mapping(raw.get("authorized_cap_bounds_watts_per_gpu"))
        bounds_ok = True
        for row in actions:
            action = _mapping(row.get("action"))
            ident = action.get("workload_id")
            if ident not in bounds or action.get("action_type") != "set_power_cap":
                bounds_ok = False; continue
            value = _finite(action.get("value"), "action value")
            bound = _mapping(bounds[ident])
            bounds_ok = bounds_ok and _finite(bound.get("minimum"), "minimum") <= value <= _finite(bound.get("maximum"), "maximum")
        return ({"sample_count": float(len(constrained)), "maximum_exceedance_watts": exceed, "critical_cap_actions": float(len(protected_actions))},
                {"target_met_after_settling": bool(constrained) and exceed == 0.0, "protected_workloads_unchanged": protected_unchanged, "policy_bounds_respected": bounds_ok})
    if scenario_id == "infeasible_constraint":
        shortfalls = [row for row in rows if row.get("type") == "shortfall"]
        no_actions = [row for row in rows if row.get("type") == "no_action"]
        maximum = max((max(0.0, _finite(row.get("facility_power_watts"), "facility power") - _finite(row.get("envelope_watts"), "envelope")) for row in constrained), default=0.0)
        explicit = max((_finite(row.get("magnitude_watts"), "shortfall magnitude") for row in shortfalls), default=0.0)
        explicit_ok = bool(shortfalls) and bool(no_actions) and all(
            _finite(row.get("magnitude_watts"), "shortfall magnitude") > 0
            and row.get("reason") == "protected_or_non_flexible_load_prevents_compliance"
            and set(row.get("protected_constraints", ())) >= set(protected_ids) for row in shortfalls
        )
        return ({"maximum_exceedance_watts": maximum, "maximum_explicit_shortfall_watts": explicit, "shortfall_record_count": float(len(shortfalls))},
                {"shortfall_explicit": explicit_ok and math.isclose(maximum, explicit, abs_tol=1e-9), "protected_workloads_unchanged": protected_unchanged, "no_unsafe_action": not actions})
    recovery_start = int(_finite(raw.get("recovery_start_second"), "recovery_start_second"))
    recovery = [row for row in samples if recovery_start <= row["second"] < int(inputs["duration_seconds"])]
    powers = [_finite(row.get("facility_power_watts"), "facility power") for row in recovery]
    rebound = max((max(0.0, power - _finite(row.get("envelope_watts"), "envelope")) for power, row in zip(powers, recovery)), default=0.0)
    step = _finite(raw.get("recovery_maximum_facility_step_watts"), "recovery step")
    increases = [b - a for a, b in zip(powers, powers[1:])]
    return ({"recovery_sample_count": float(len(recovery)), "maximum_rebound_exceedance_watts": rebound, "peak_recovery_watts": max(powers, default=0.0)},
            {"recovery_ceiling_respected": bool(recovery) and rebound == 0.0, "recovery_rate_respected": bool(recovery) and all(value <= step + 1e-9 for value in increases), "no_oscillation": bool(recovery) and all(value >= -1e-9 for value in increases)})


def _validate_standard_rows(rows, ledger, inputs, scenario_id):
    if scenario_id == "stale_meter":
        if ledger:
            raise TraceVerificationError("stale-meter trace cannot contain mutations")
        return
    allowed = {"admission_intent", "admission_outcome", "decision", "action_intent", "action_outcome", "no_action", "shortfall", "sample"}
    if any(row.get("type") not in allowed for row in rows):
        raise TraceVerificationError("unexpected standard trace row type")
    duration = int(_finite(inputs.get("duration_seconds"), "duration_seconds"))
    if duration < 0:
        raise TraceVerificationError("negative duration")
    if scenario_id != "stale_meter":
        seconds = [row.get("second") for row in rows if row.get("type") == "sample"]
        if seconds != list(range(duration)):
            raise TraceVerificationError("sample rows are missing, extra, duplicated, or reordered")
    mutating = [row for row in rows if row.get("type") in ("admission_outcome", "action_outcome")]
    _contiguous(ledger, "mutation_ledger", start=1)
    if len(mutating) != len(ledger):
        raise TraceVerificationError("mutation ledger does not explain every mutation")
    for event, entry in zip(mutating, ledger):
        if entry.get("record") != event or entry.get("mutation_type") != event.get("type") or entry.get("second") != event.get("second"):
            raise TraceVerificationError("mutation ledger contradicts trace rows")


def _verify_stale(rows, inputs, configuration, raw):
    if len(rows) != 2 or [row.get("type") for row in rows] != ["meter_observation", "eligibility_decision"]:
        raise TraceVerificationError("stale-meter trace rows are missing or extra")
    observation, decision = rows
    observed_at = datetime.fromisoformat(observation.get("evaluated_at_utc"))
    sampled_at = datetime.fromisoformat(observation.get("timestamp_utc"))
    if observed_at.tzinfo is None or sampled_at.tzinfo is None:
        raise TraceVerificationError("meter timestamps must be timezone-aware")
    age = (observed_at - sampled_at).total_seconds()
    claimed_age = _finite(inputs.get("sample_age_seconds"), "sample_age_seconds")
    policy = _mapping(_mapping(configuration).get("freshness_policy"))
    stale = age > _finite(policy.get("max_age_seconds"), "max_age_seconds")
    reason = raw.get("eligibility_reason_required")
    reasons = decision.get("reasons")
    if not isinstance(reasons, list):
        raise TraceVerificationError("eligibility reasons must be a list")
    eligible = decision.get("eligible") is True
    inhibited = decision.get("new_actuation_count") == 0
    return ({"decision_eligible": 1.0 if eligible else 0.0, "sample_age_seconds": age},
            {"new_actuation_inhibited": stale and not eligible and inhibited, "safe_hold_entered": decision.get("next_state") == raw.get("ineligible_state") == "SAFE_HOLD", "operator_reason_recorded": reason in reasons and math.isclose(age, claimed_age, abs_tol=1e-9)})


def _verify_fault(packet: Mapping[str, Any], scenario_id: str):
    required = {"scenario_id", "kind", "expected_state", "observed_state", "primary_trace", "injection_ledger", "mutation_ledger", "raw_facts", "evidence"}
    if set(packet) != required:
        raise TraceVerificationError("unsupported integrated-fault schema/version")
    if packet.get("kind") != scenario_id:
        raise TraceVerificationError("fault kind/ID mismatch")
    trace = _rows(packet["primary_trace"], "primary_trace")
    injections = _rows(packet["injection_ledger"], "injection_ledger")
    mutations = _rows(packet["mutation_ledger"], "mutation_ledger", nonempty=False)
    raw = _mapping(packet["raw_facts"])
    _contiguous(trace, "primary_trace"); _contiguous(injections, "injection_ledger"); _contiguous(mutations, "mutation_ledger")
    signature = tuple((row.get("phase"), row.get("outcome"), row.get("evidence")) for row in trace)
    if signature != _FAULT_TRACE_SIGNATURES[scenario_id]:
        raise TraceVerificationError("fault trace rows are missing, extra, reordered, or contradictory")
    if len(injections) != 1 or injections[0].get("fault_id") != scenario_id or injections[0].get("consumed") is not True:
        raise TraceVerificationError("fault injection is missing, duplicated, unused, or mismatched")
    inputs = _mapping(raw.get("scenario_inputs"))
    if inputs.get("fault_id") != scenario_id or injections[0].get("step") != inputs.get("injection_step"):
        raise TraceVerificationError("injection ledger contradicts scenario inputs")
    counts = (raw.get("declared_injection_count"), raw.get("consumed_injection_count"), raw.get("pending_injection_count"))
    if counts != (1, 1, 0) or raw.get("injection_consumed") is not True:
        raise TraceVerificationError("raw injection counts contradict ledger")
    if raw.get("trace_row_count") != len(trace) or raw.get("mutation_count") != len(mutations):
        raise TraceVerificationError("raw row counts contradict ledgers")
    for row in mutations:
        if not isinstance(row.get("action"), Mapping) or any(row.get(name) not in (True, False) for name in ("scheduler_acknowledged", "adapter_acknowledged", "observed")):
            raise TraceVerificationError("malformed mutation ledger row")
    observed = sum(row["observed"] is True for row in mutations)
    if raw.get("observed_mutation_count") != observed:
        raise TraceVerificationError("unexplained observed mutation")
    allowed_mutations = 1 if scenario_id == "optimizer_timeout" else 0
    if len(mutations) != allowed_mutations:
        raise TraceVerificationError("unexplained mutation after fault")
    evidence = [row.get("evidence") for row in trace]
    if any(not isinstance(item, str) or not item for item in evidence):
        raise TraceVerificationError("trace evidence is malformed")
    session = raw.get("session_events")
    session = _rows(session, "session_events", nonempty=False)
    _contiguous(session, "session_events")
    after = raw.get("workloads_after"); before = raw.get("workloads_before")
    unchanged = isinstance(after, Mapping) and after == before
    safe_hold = bool(trace) and trace[-1].get("phase") in ("safe_hold", "restart") and trace[-1].get("outcome") in ("entered", "safe_hold")
    derived_state = "safe_hold" if safe_hold else "supervised"
    expected_state = "supervised" if scenario_id == "optimizer_timeout" else "safe_hold"
    if packet.get("expected_state") != expected_state or packet.get("observed_state") != derived_state:
        raise TraceVerificationError("declared state contradicts primary trace")
    contains = lambda text: any(text in item for item in evidence)
    facts = _fault_facts(scenario_id, contains, safe_hold, unchanged, inputs, raw, trace, session, mutations)
    requirement = _FAULT_REQUIREMENTS[scenario_id]
    facts = {name: bool(facts.get(name, False)) for name in requirement.required_invariants}
    forbidden = requirement.required_metrics[1]
    metrics = {"fault_count": 1.0, forbidden: 0.0 if all(facts.values()) else 1.0}
    return metrics, facts


def _fault_facts(sid, contains, safe_hold, unchanged, inputs, raw, trace, session, mutations):
    no_mutation = not mutations and unchanged
    common_hold = safe_hold and no_mutation
    if sid == "meter_loss": return {"new_actuation_inhibited": common_hold, "safe_hold_entered": safe_hold, "operator_alert_recorded": contains("authoritative_meter_missing") and inputs.get("authoritative_meter_present") is False}
    if sid == "meter_stale": return {"new_actuation_inhibited": common_hold, "safe_hold_entered": safe_hold, "operator_reason_recorded": contains("meter sample is stale") and _finite(inputs.get("sample_age_seconds"), "sample age") > 5}
    if sid in ("meter_duplicate", "meter_reorder"):
        before = inputs.get("accepted_sequence_before_fault"); injected = inputs.get("injected_sequence"); cursor = raw.get("authoritative_cursor")
        rejected = before == injected if sid == "meter_duplicate" else isinstance(before, int) and isinstance(injected, int) and injected < before
        key = "duplicate_rejected" if sid == "meter_duplicate" else "regression_rejected"
        return {key: rejected and contains("duplicate sequence" if sid == "meter_duplicate" else "sequence regression"), "cursor_not_advanced": isinstance(cursor, Mapping) and cursor.get("last_sequence") == before, "new_actuation_inhibited": common_hold}
    if sid == "clock_jump": return {"clock_fault_rejected": inputs.get("clock_synchronized") is False and contains("clock is not synchronized"), "new_actuation_inhibited": common_hold, "operator_reason_recorded": contains("clock is not synchronized")}
    if sid == "optimizer_timeout":
        fallback = any(row.get("phase") == "planner" and row.get("outcome") == "fallback" and row.get("evidence") == "optimizer_deadline_exceeded" for row in trace)
        return {"no_partial_plan_executed": fallback and len(mutations) == 1 and mutations[0].get("action", {}).get("reason") == "power_envelope", "approved_fallback_selected": fallback and contains("deterministic_plan_created"), "timeout_audited": fallback}
    if sid == "optimizer_invalid_output": return {"invalid_plan_rejected": common_hold and contains("optimizer_output_invalid"), "approved_fallback_selected": common_hold, "validation_reason_audited": contains("optimizer_output_invalid")}
    if sid.startswith("scheduler_"):
        unavailable = sid.endswith("unavailable"); marker = "scheduler unavailable" if unavailable else "scheduler rejected request"
        return {"workload_mutation_inhibited": common_hold, "protected_workloads_unchanged": unchanged, ("outage_audited" if unavailable else "rejection_not_assumed_success"): contains(marker), **({} if unavailable else {"failure_audited": contains(marker)})}
    if sid.startswith("adapter_"):
        marker = "adapter unavailable" if sid.endswith("unavailable") else "adapter rejected request"
        return {"command_not_assumed_applied": common_hold and contains(marker), "no_mutation": no_mutation, "failure_audited": contains(marker)}
    if sid == "audit_failure": return {"mutation_prevented": common_hold and contains("audit_intent_failed"), "no_mutation": no_mutation, "failure_surfaced": contains("audit_intent_failed")}
    if sid == "controller_restart":
        rebuilt = [row for row in session if row.get("event_type") == "session_reconstructed"]
        payload = rebuilt[-1].get("payload", {}) if rebuilt else {}
        return {"state_reconstructed_from_evidence": bool(rebuilt) and payload.get("proposal_id") == "env-1", "expired_commands_not_replayed": payload.get("proposal_expired") is True and payload.get("replayed_execution_commands") == 0, "operator_resume_required": safe_hold and payload.get("operator_resume_required") is True}
    if sid == "split_brain": return {"single_writer_enforced": common_hold and inputs.get("contending_controller_count") == 2, "stale_writer_fenced": contains("stale_controller_fenced"), "conflict_audited": contains("stale_controller_fenced")}
    if sid == "manual_conflict":
        manual = _finite(inputs.get("manual_limit_watts"), "manual limit"); automatic = _finite(inputs.get("automatic_limit_watts"), "automatic limit")
        return {"manual_control_wins": common_hold and manual < automatic and contains(":" + str(int(manual))), "automatic_event_cancelled": safe_hold, "conflict_audited": contains("stricter_manual_or_optimizer_limit_selected")}
    if sid == "interrupted_recovery":
        recovery = any(row.get("event_type") == "recovery_started" for row in session)
        return {"recovery_increase_inhibited": no_mutation and recovery, "recovery_hold_entered": safe_hold and recovery, "interruption_audited": contains("recovery_interrupted")}
    if sid == "protected_mislabel_attempt":
        critical = inputs.get("declared_priority") == "critical"
        return {"protected_workload_rejected": common_hold and critical and contains("protected workload"), "protected_workloads_unchanged": unchanged, "validation_reason_audited": contains("validation_rejected")}
    raise TraceVerificationError("unimplemented fault verifier")
