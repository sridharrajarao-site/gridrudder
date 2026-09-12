import unittest
import math

from gridgpu.fault_benchmarks import (
    FaultObservation,
    SafeState,
    assess_fault_observation,
    canonical_fault_scenarios,
    run_canonical_fault_matrix,
)
from gridgpu.faults import FaultKind
from gridgpu.gates import REQUIRED_SCENARIOS


class CanonicalFaultMatrixTests(unittest.TestCase):
    def test_matrix_covers_every_required_fault_in_stable_order(self):
        scenarios = canonical_fault_scenarios()
        self.assertEqual(len(scenarios), len(FaultKind))
        self.assertEqual([scenario.kind for scenario in scenarios], list(FaultKind))
        self.assertTrue(all(scenario.required_evidence for scenario in scenarios))

    def test_every_scenario_reaches_named_safe_state_with_evidence(self):
        results = run_canonical_fault_matrix()
        failures = {result.kind.value: result.findings for result in results if not result.passed}
        self.assertEqual(failures, {})
        self.assertTrue(all(result.observed_safe_state is result.expected_safe_state for result in results))

    def test_each_result_exposes_its_gate_metric_and_invariant_names(self):
        requirements = {
            item.scenario_id: item
            for item in REQUIRED_SCENARIOS
            if item.scenario_id in {kind.value for kind in FaultKind}
        }
        results = run_canonical_fault_matrix()
        self.assertEqual(set(requirements), {result.scenario_id for result in results})
        for result in results:
            requirement = requirements[result.scenario_id]
            self.assertEqual(result.scenario_id, result.kind.value)
            self.assertEqual(set(result.metrics), set(requirement.required_metrics))
            self.assertEqual(set(result.invariants), set(requirement.required_invariants))
            self.assertTrue(
                all(
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    for value in result.metrics.values()
                )
            )
            self.assertTrue(all(isinstance(value, bool) for value in result.invariants.values()))

    def test_restart_proves_reconstruction_without_replaying_commands(self):
        result = next(
            item
            for item in run_canonical_fault_matrix()
            if item.kind is FaultKind.CONTROLLER_RESTART
        )
        self.assertTrue(result.invariants["state_reconstructed_from_evidence"])
        self.assertTrue(result.invariants["expired_commands_not_replayed"])
        self.assertTrue(result.invariants["operator_resume_required"])
        self.assertEqual(result.metrics["replayed_expired_commands"], 0.0)

    def test_matrix_is_deterministic(self):
        self.assertEqual(run_canonical_fault_matrix(), run_canonical_fault_matrix())

    def test_missing_evidence_or_wrong_state_fails_assessment(self):
        scenario = canonical_fault_scenarios()[0]
        missing = assess_fault_observation(scenario, FaultObservation(SafeState.SAFE_HOLD, ()))
        wrong = assess_fault_observation(
            scenario, FaultObservation(SafeState.NO_MUTATION, scenario.required_evidence)
        )
        self.assertFalse(missing.passed)
        self.assertIn("missing evidence", missing.findings[0])
        self.assertFalse(wrong.passed)
        self.assertIn("safe state mismatch", wrong.findings)


if __name__ == "__main__":
    unittest.main()
