import unittest

from gridgpu.standard_traces import run_all_standard_primary_traces, run_standard_primary_trace


class StandardPrimaryTraceTests(unittest.TestCase):
    def test_complete_schema_is_stable_and_deterministic(self):
        first = run_all_standard_primary_traces()
        second = run_all_standard_primary_traces()
        self.assertEqual(first, second)
        self.assertEqual(
            [item.scenario_id for item in first],
            ["normal_constraint", "infeasible_constraint", "rebound_recovery", "stale_meter"],
        )
        for item in first:
            self.assertEqual(item.schema_version, 1)
            self.assertTrue(item.inputs)
            self.assertTrue(item.configuration)
            self.assertTrue(item.trace_rows)
            self.assertTrue(item.raw_facts)

    def test_normal_trace_supports_independent_gate_recomputation(self):
        trace = run_standard_primary_trace("normal_constraint")
        start = trace.raw_facts["constrained_start_second"]
        end = trace.raw_facts["constrained_end_second"]
        samples = [row for row in trace.trace_rows if row["type"] == "sample" and start <= row["second"] < end]
        maximum_exceedance = max(max(0.0, row["facility_power_watts"] - row["envelope_watts"]) for row in samples)
        critical_actions = [row for row in trace.mutation_ledger if row["workload_id"] == "critical" and row["mutation_type"] == "action_outcome"]
        cap_actions = [row["record"]["action"] for row in trace.mutation_ledger if row["mutation_type"] == "action_outcome"]
        bounds = trace.raw_facts["authorized_cap_bounds_watts_per_gpu"]
        bounds_respected = all(
            action["workload_id"] in bounds
            and bounds[action["workload_id"]]["minimum"] <= action["value"] <= bounds[action["workload_id"]]["maximum"]
            for action in cap_actions
        )
        self.assertGreater(len(samples), 0)
        self.assertEqual(maximum_exceedance, 0.0)
        self.assertEqual(critical_actions, [])
        self.assertTrue(bounds_respected)

    def test_infeasible_trace_retains_quantified_shortfall_and_no_unsafe_mutation(self):
        trace = run_standard_primary_trace("infeasible_constraint")
        shortfalls = [row for row in trace.trace_rows if row["type"] == "shortfall"]
        no_actions = [row for row in trace.trace_rows if row["type"] == "no_action"]
        action_mutations = [row for row in trace.mutation_ledger if row["mutation_type"] == "action_outcome"]
        self.assertTrue(shortfalls)
        self.assertTrue(all(row["magnitude_watts"] > 0 for row in shortfalls))
        self.assertTrue(no_actions)
        self.assertEqual(action_mutations, [])

    def test_rebound_trace_recomputes_ceiling_rate_and_monotonicity(self):
        trace = run_standard_primary_trace("rebound_recovery")
        start = trace.raw_facts["recovery_start_second"]
        samples = [row for row in trace.trace_rows if row["type"] == "sample" and row["second"] >= start]
        powers = [row["facility_power_watts"] for row in samples]
        positive_steps = [later - earlier for earlier, later in zip(powers, powers[1:]) if later > earlier]
        self.assertTrue(all(row["facility_power_watts"] <= row["envelope_watts"] for row in samples))
        self.assertTrue(all(step <= trace.raw_facts["recovery_maximum_facility_step_watts"] + 1e-9 for step in positive_steps))
        self.assertTrue(all(later + 1e-9 >= earlier for earlier, later in zip(powers, powers[1:])))

    def test_stale_trace_recomputes_eligibility_hold_reason_and_no_mutation(self):
        trace = run_standard_primary_trace("stale_meter")
        observation, decision = trace.trace_rows
        age = trace.inputs["sample_age_seconds"]
        maximum_age = trace.configuration["freshness_policy"]["max_age_seconds"]
        self.assertGreater(age, maximum_age)
        self.assertEqual(observation["quality"], "good")
        self.assertFalse(decision["eligible"])
        self.assertEqual(decision["next_state"], "SAFE_HOLD")
        self.assertIn("meter sample is stale", decision["reasons"])
        self.assertEqual(decision["new_actuation_count"], 0)
        self.assertEqual(trace.mutation_ledger, ())

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            run_standard_primary_trace("unknown")


if __name__ == "__main__":
    unittest.main()
