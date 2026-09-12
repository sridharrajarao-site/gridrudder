import unittest

from gridgpu.benchmarks import (
    ScenarioKind,
    canonical_scenarios,
    run_benchmark,
    run_canonical_benchmarks,
)
from gridgpu.gates import REQUIRED_SCENARIOS


class CanonicalBenchmarkTests(unittest.TestCase):
    def test_definitions_cover_required_scenarios_in_stable_order(self):
        self.assertEqual(
            [scenario.kind for scenario in canonical_scenarios()],
            [
                ScenarioKind.NORMAL_CONSTRAINT,
                ScenarioKind.INFEASIBLE_CONSTRAINT,
                ScenarioKind.REBOUND_RECOVERY,
                ScenarioKind.STALE_METER,
            ],
        )

    def test_normal_constraint_is_compliant_and_protects_critical_work(self):
        result = run_benchmark(canonical_scenarios()[0])
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.metrics["maximum_exceedance_watts"], 0.0)
        self.assertEqual(result.metrics["critical_cap_actions"], 0.0)
        self.assertTrue(all(result.invariants.values()))

    def test_infeasible_constraint_is_exposed_without_unsafe_action(self):
        result = run_benchmark(canonical_scenarios()[1])
        self.assertTrue(result.passed, result.findings)
        self.assertGreater(result.metrics["maximum_exceedance_watts"], 0.0)
        self.assertGreater(result.metrics["energy_over_limit_wh"], 0.0)
        self.assertEqual(result.metrics["critical_action_count"], 0.0)
        self.assertGreater(result.metrics["shortfall_record_count"], 0.0)
        self.assertGreater(result.metrics["maximum_explicit_shortfall_watts"], 0.0)
        self.assertGreater(result.metrics["no_action_record_count"], 0.0)

    def test_recovery_has_no_rebound_envelope_violation(self):
        result = run_benchmark(canonical_scenarios()[2])
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.metrics["maximum_rebound_exceedance_watts"], 0.0)
        self.assertGreater(result.metrics["recovery_sample_count"], 0.0)

    def test_stale_meter_is_not_decision_eligible(self):
        result = run_benchmark(canonical_scenarios()[3])
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.metrics["decision_eligible"], 0.0)

    def test_complete_runner_is_deterministic(self):
        first = run_canonical_benchmarks()
        second = run_canonical_benchmarks()
        self.assertEqual(first, second)
        self.assertTrue(all(result.passed for result in first))

    def test_same_stateful_scenario_definition_can_be_replayed(self):
        scenario = canonical_scenarios()[0]
        self.assertEqual(run_benchmark(scenario), run_benchmark(scenario))

    def test_standard_results_match_exact_gate_metric_and_invariant_contracts(self):
        requirements = {item.scenario_id: item for item in REQUIRED_SCENARIOS}
        results = run_canonical_benchmarks()
        self.assertEqual(
            {result.scenario_id for result in results},
            {
                "normal_constraint",
                "infeasible_constraint",
                "rebound_recovery",
                "stale_meter",
            },
        )
        for result in results:
            with self.subTest(scenario_id=result.scenario_id):
                requirement = requirements[result.scenario_id]
                self.assertTrue(result.passed, result.findings)
                self.assertEqual(
                    set(requirement.required_metrics).difference(result.metrics), set()
                )
                self.assertEqual(
                    set(result.invariants), set(requirement.required_invariants)
                )
                self.assertTrue(all(result.invariants.values()))
                self.assertEqual(result.evidence, {"invariants": result.invariants})

    def test_invariants_are_derived_as_expected_for_each_standard_scenario(self):
        results = {item.scenario_id: item for item in run_canonical_benchmarks()}
        self.assertEqual(
            results["normal_constraint"].invariants,
            {
                "target_met_after_settling": True,
                "protected_workloads_unchanged": True,
                "policy_bounds_respected": True,
            },
        )
        self.assertEqual(
            results["infeasible_constraint"].invariants,
            {
                "shortfall_explicit": True,
                "protected_workloads_unchanged": True,
                "no_unsafe_action": True,
            },
        )
        self.assertEqual(
            results["rebound_recovery"].invariants,
            {
                "recovery_ceiling_respected": True,
                "recovery_rate_respected": True,
                "no_oscillation": True,
            },
        )
        self.assertEqual(
            results["stale_meter"].invariants,
            {
                "new_actuation_inhibited": True,
                "safe_hold_entered": True,
                "operator_reason_recorded": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
