import unittest
import json

from gridgpu.faults import FaultKind
from gridgpu.gates import REQUIRED_SCENARIOS
from gridgpu.integrated_faults import (
    fault_gate_requirements,
    run_all_primary_traces,
    run_primary_trace,
)


class IntegratedPrimaryTraceTests(unittest.TestCase):
    def test_normal_and_all_fault_ids_have_consumed_primary_traces(self):
        results = run_all_primary_traces()
        self.assertEqual(
            [result.scenario_id for result in results],
            ["normal"] + [kind.value for kind in FaultKind],
        )
        self.assertTrue(all(result.trace for result in results))
        self.assertTrue(all(result.injection_consumed for result in results))
        self.assertTrue(all("injection_not_consumed" not in result.evidence for result in results))

    def test_failure_traces_do_not_record_mutation(self):
        mutation_allowed = {"normal", FaultKind.OPTIMIZER_TIMEOUT.value}
        for result in run_all_primary_traces():
            if result.scenario_id not in mutation_allowed:
                self.assertEqual(result.mutation_ledger, (), result.scenario_id)

    def test_fault_ids_exactly_match_gate_requirements(self):
        fault_ids = {kind.value for kind in FaultKind}
        gate_fault_ids = {
            requirement.scenario_id
            for requirement in REQUIRED_SCENARIOS
            if requirement.scenario_id in fault_ids
        }
        self.assertEqual(set(fault_gate_requirements()), fault_ids)
        self.assertEqual(gate_fault_ids, fault_ids)

    def test_results_are_stable_mappings_with_independently_countable_raw_facts(self):
        requirements = fault_gate_requirements()
        for result in run_all_primary_traces()[1:]:
            packet = result.as_mapping()
            self.assertEqual(packet["scenario_id"], result.scenario_id)
            self.assertEqual(packet["kind"], result.kind)
            self.assertEqual(packet["expected_state"], result.expected_state)
            self.assertEqual(packet["observed_state"], result.observed_state)
            self.assertEqual(packet["expected_state"], packet["observed_state"])
            json.dumps(packet, sort_keys=True, allow_nan=False)
            self.assertTrue(all(isinstance(row, dict) for row in packet["primary_trace"]))
            self.assertTrue(all(isinstance(row, dict) for row in packet["injection_ledger"]))
            self.assertTrue(all(isinstance(row, dict) for row in packet["mutation_ledger"]))
            facts = packet["raw_facts"]
            self.assertEqual(facts["declared_injection_count"], 1)
            self.assertEqual(facts["consumed_injection_count"], 1)
            self.assertEqual(facts["pending_injection_count"], 0)
            self.assertEqual(facts["scenario_inputs"]["fault_id"], result.scenario_id)
            self.assertEqual(len(packet["mutation_ledger"]), facts["mutation_count"])
            self.assertEqual(
                sum(1 for row in packet["mutation_ledger"] if row["observed"]),
                facts["observed_mutation_count"],
            )
            requirement = requirements[result.scenario_id]
            self.assertEqual(facts["gate_required_metrics"], list(requirement.required_metrics))
            self.assertEqual(facts["gate_required_invariants"], list(requirement.required_invariants))

    def test_protected_mislabel_trace_proves_critical_workload_unchanged(self):
        result = run_primary_trace(FaultKind.PROTECTED_MISLABEL.value)
        facts = result.raw_facts
        self.assertEqual(facts["workloads_before"]["flex"]["priority"], "critical")
        self.assertEqual(facts["workloads_after"], facts["workloads_before"])
        self.assertEqual(facts["observed_mutation_count"], 0)

    def test_primary_rows_and_ledgers_are_deterministic(self):
        first = [result.as_mapping() for result in run_all_primary_traces()]
        second = [result.as_mapping() for result in run_all_primary_traces()]
        self.assertEqual(first, second)

    def test_representative_faults_show_safe_hold_and_evidence(self):
        expectations = {
            "meter_loss": "authoritative_meter_missing",
            "adapter_rejection": "adapter rejected request",
            "audit_failure": "audit_intent_failed",
            "controller_restart": "operator_resume_required",
            "protected_mislabel_attempt": "validation_rejected",
        }
        for scenario_id, evidence in expectations.items():
            result = run_primary_trace(scenario_id)
            self.assertEqual(result.safe_state, "safe_hold")
            self.assertTrue(any(evidence in item for item in result.evidence), scenario_id)


if __name__ == "__main__":
    unittest.main()
