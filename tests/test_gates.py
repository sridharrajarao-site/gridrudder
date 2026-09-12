from dataclasses import dataclass
from enum import Enum
import unittest

from gridgpu.gates import REQUIRED_SCENARIOS, evaluate_gate_b


def valid_result(requirement):
    metrics = {name: 0.0 for name in requirement.required_metrics}
    if "fault_count" in metrics:
        metrics["fault_count"] = 1.0
    positive_metrics = {
        "normal_constraint": ("sample_count",),
        "infeasible_constraint": (
            "maximum_exceedance_watts",
            "maximum_explicit_shortfall_watts",
            "shortfall_record_count",
        ),
        "rebound_recovery": ("recovery_sample_count",),
        "stale_meter": ("sample_age_seconds",),
    }
    for positive in positive_metrics.get(requirement.scenario_id, ()):
        if positive in metrics:
            metrics[positive] = 1.0
    trace_digest = "sha256:" + "b" * 64
    facts = {name: True for name in requirement.required_invariants}
    return {
        "scenario_id": requirement.scenario_id,
        "passed": True,
        "findings": [],
        "metrics": metrics,
        "evidence": {
            "artifact_version": "artifact:v1",
            "configuration_digest": "sha256:config",
            "policy_version": "policy:v1",
            "input_digest": "sha256:input",
            "audit_head_hash": "a" * 64,
            "raw_data_reference": "artifact://raw/scenario.jsonl",
            "primary_trace_digest": trace_digest,
            "invariants": dict(facts),
            "trace_verifier": {
                "verifier_id": "gridgpu-trace-verifier",
                "verifier_version": "v1",
                "primary_trace_digest": trace_digest,
                "facts": dict(facts),
            },
        },
    }


class GateBTests(unittest.TestCase):
    def test_complete_passing_evidence_is_go(self):
        decision = evaluate_gate_b([valid_result(item) for item in REQUIRED_SCENARIOS])
        self.assertTrue(decision.go, decision.reasons)
        self.assertEqual(decision.required_scenario_count, len(REQUIRED_SCENARIOS))
        self.assertEqual(decision.missing_scenario_ids, ())

    def test_absent_required_result_is_no_go(self):
        decision = evaluate_gate_b([valid_result(item) for item in REQUIRED_SCENARIOS[:-1]])
        self.assertFalse(decision.go)
        self.assertEqual(decision.missing_scenario_ids, (REQUIRED_SCENARIOS[-1].scenario_id,))
        self.assertTrue(any("required scenario is absent" in reason for reason in decision.reasons))

    def test_duplicate_result_is_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results.append(valid_result(REQUIRED_SCENARIOS[0]))
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertIn(
            "duplicate scenario result: {}".format(REQUIRED_SCENARIOS[0].scenario_id),
            decision.reasons,
        )

    def test_failed_or_nonboolean_pass_claim_is_no_go(self):
        for invalid_passed in (False, 1, "true", None):
            with self.subTest(invalid_passed=invalid_passed):
                results = [valid_result(item) for item in REQUIRED_SCENARIOS]
                results[0]["passed"] = invalid_passed
                self.assertFalse(evaluate_gate_b(results).go)

    def test_unresolved_findings_are_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results[0]["findings"] = ["target tolerance missed"]
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("unresolved findings" in reason for reason in decision.reasons))

    def test_missing_metric_and_invariant_are_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        requirement = REQUIRED_SCENARIOS[0]
        del results[0]["metrics"][requirement.required_metrics[0]]
        results[0]["evidence"]["invariants"][requirement.required_invariants[0]] = False
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("required metric" in reason for reason in decision.reasons))
        self.assertTrue(any("producer invariant" in reason for reason in decision.reasons))

    def test_trace_verifier_is_required_and_must_independently_prove_facts(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        requirement = REQUIRED_SCENARIOS[0]
        results[0]["evidence"]["trace_verifier"]["facts"][requirement.required_invariants[0]] = False
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("did not independently prove" in reason for reason in decision.reasons))

        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results[0]["evidence"]["trace_verifier"]["primary_trace_digest"] = "sha256:" + "c" * 64
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("does not match primary trace" in reason for reason in decision.reasons))

    def test_all_true_claims_cannot_override_contradictory_standard_metrics(self):
        mutations = (
            ("normal_constraint", "maximum_exceedance_watts", 1.0),
            ("infeasible_constraint", "maximum_explicit_shortfall_watts", 2.0),
            ("rebound_recovery", "maximum_rebound_exceedance_watts", 1.0),
            ("stale_meter", "decision_eligible", 1.0),
        )
        for scenario_id, metric, value in mutations:
            with self.subTest(scenario_id=scenario_id):
                results = [valid_result(item) for item in REQUIRED_SCENARIOS]
                item = next(result for result in results if result["scenario_id"] == scenario_id)
                item["metrics"][metric] = value
                decision = evaluate_gate_b(results)
                self.assertFalse(decision.go)
                self.assertTrue(any("metric rule" in reason for reason in decision.reasons))

    def test_all_true_claims_cannot_override_fault_metrics(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        fault = next(result for result in results if result["scenario_id"] == "audit_failure")
        fault["metrics"]["fault_count"] = 0.0
        fault["metrics"]["mutations_after_fault"] = 1.0
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        failures = [reason for reason in decision.reasons if "audit_failure: metric rule" in reason]
        self.assertGreaterEqual(len(failures), 2)

    def test_malformed_metrics_and_evidence_are_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results[0]["metrics"] = {"bad": float("nan")}
        results[1]["evidence"] = None
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("finite number" in reason for reason in decision.reasons))
        self.assertTrue(any("evidence must be a mapping" in reason for reason in decision.reasons))

    def test_bad_hash_and_empty_common_evidence_are_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results[0]["evidence"]["audit_head_hash"] = "not-a-hash"
        results[0]["evidence"]["artifact_version"] = " "
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("not lowercase SHA-256" in reason for reason in decision.reasons))
        self.assertTrue(any("artifact_version" in reason for reason in decision.reasons))

    def test_missing_or_invalid_scenario_identity_is_no_go(self):
        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        results[0].pop("scenario_id")
        decision = evaluate_gate_b(results)
        self.assertFalse(decision.go)
        self.assertTrue(any("scenario ID is missing" in reason for reason in decision.reasons))

    def test_generic_object_and_enum_kind_are_supported(self):
        class Kind(str, Enum):
            EXTRA = "extra_valid_scenario"

        @dataclass
        class ObjectResult:
            kind: Kind
            passed: bool
            findings: tuple
            metrics: dict
            evidence: dict

        results = [valid_result(item) for item in REQUIRED_SCENARIOS]
        evidence = valid_result(REQUIRED_SCENARIOS[0])["evidence"]
        results.append(ObjectResult(Kind.EXTRA, True, (), {"count": 1}, evidence))
        decision = evaluate_gate_b(results)
        self.assertTrue(decision.go, decision.reasons)

    def test_unreadable_results_fail_closed(self):
        decision = evaluate_gate_b(None)
        self.assertFalse(decision.go)
        self.assertEqual(decision.received_scenario_count, 0)


if __name__ == "__main__":
    unittest.main()
