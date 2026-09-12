import copy
import unittest

from gridgpu.gates import REQUIRED_SCENARIOS
from gridgpu.integrated_faults import run_all_primary_traces
from gridgpu.standard_traces import run_all_standard_primary_traces
from gridgpu.trace_verifier import TraceVerificationError, verify_primary_trace


class PrimaryTraceVerifierTests(unittest.TestCase):
    def test_all_21_scenarios_recompute_exact_gate_contract(self):
        packets = list(run_all_standard_primary_traces()) + list(run_all_primary_traces()[1:])
        self.assertEqual(len(packets), 21)
        requirements = {item.scenario_id: item for item in REQUIRED_SCENARIOS}
        for packet in packets:
            with self.subTest(scenario_id=packet.scenario_id):
                verified = verify_primary_trace(packet, packet.scenario_id)
                self.assertEqual(set(verified.metrics), set(requirements[packet.scenario_id].required_metrics))
                self.assertEqual(set(verified.facts), set(requirements[packet.scenario_id].required_invariants))
                self.assertTrue(all(verified.facts.values()), verified)
                self.assertRegex(verified.primary_trace_digest, r"^sha256:[0-9a-f]{64}$")

    def test_standard_sample_and_mutation_tampering_fail_closed(self):
        packet = copy.deepcopy(run_all_standard_primary_traces()[0])
        packet = packet.__class__(packet.schema_version, packet.scenario_id, packet.inputs, packet.configuration, packet.trace_rows[:-1], packet.mutation_ledger, packet.raw_facts)
        with self.assertRaisesRegex(TraceVerificationError, "sample rows"):
            verify_primary_trace(packet)
        packet = copy.deepcopy(run_all_standard_primary_traces()[0])
        rows = list(packet.mutation_ledger)
        rows[0]["record"] = {"tampered": True}
        packet = packet.__class__(packet.schema_version, packet.scenario_id, packet.inputs, packet.configuration, packet.trace_rows, tuple(rows), packet.raw_facts)
        with self.assertRaisesRegex(TraceVerificationError, "mutation[_ ]ledger"):
            verify_primary_trace(packet)

    def test_stale_meter_and_schema_tampering_fail_closed(self):
        packet = copy.deepcopy(run_all_standard_primary_traces()[-1])
        rows = list(packet.trace_rows) + [dict(packet.trace_rows[-1])]
        packet = packet.__class__(packet.schema_version, packet.scenario_id, packet.inputs, packet.configuration, tuple(rows), packet.mutation_ledger, packet.raw_facts)
        with self.assertRaisesRegex(TraceVerificationError, "missing or extra"):
            verify_primary_trace(packet)
        packet = copy.deepcopy(run_all_standard_primary_traces()[0])
        packet = packet.__class__(99, packet.scenario_id, packet.inputs, packet.configuration, packet.trace_rows, packet.mutation_ledger, packet.raw_facts)
        with self.assertRaisesRegex(TraceVerificationError, "schema version"):
            verify_primary_trace(packet)

    def test_telemetry_fault_injection_and_cursor_tampering_fail_closed(self):
        packet = copy.deepcopy(run_all_primary_traces()[3].as_mapping())
        packet["injection_ledger"].append(dict(packet["injection_ledger"][0]))
        with self.assertRaisesRegex(TraceVerificationError, "injection"):
            verify_primary_trace(packet)
        packet = copy.deepcopy(run_all_primary_traces()[3].as_mapping())
        packet["raw_facts"]["authoritative_cursor"]["last_sequence"] = 11
        self.assertFalse(verify_primary_trace(packet).facts["cursor_not_advanced"])

    def test_dependency_and_optimizer_mutation_tampering_fail_closed(self):
        dependency = copy.deepcopy(next(x for x in run_all_primary_traces() if x.scenario_id == "adapter_rejection").as_mapping())
        dependency["mutation_ledger"].append({"sequence": 0, "action": {}, "scheduler_acknowledged": True, "adapter_acknowledged": True, "observed": True})
        dependency["raw_facts"]["mutation_count"] = 1
        dependency["raw_facts"]["observed_mutation_count"] = 1
        with self.assertRaisesRegex(TraceVerificationError, "unexplained mutation"):
            verify_primary_trace(dependency)
        optimizer = copy.deepcopy(next(x for x in run_all_primary_traces() if x.scenario_id == "optimizer_timeout").as_mapping())
        optimizer["primary_trace"][2]["outcome"] = "complete"
        with self.assertRaisesRegex(TraceVerificationError, "trace rows"):
            verify_primary_trace(optimizer)

    def test_extra_fault_row_and_contradictory_state_fail_closed(self):
        packet = copy.deepcopy(run_all_primary_traces()[1].as_mapping())
        packet["primary_trace"].append({"sequence": 1, "phase": "safe_hold", "outcome": "entered", "evidence": "authoritative_meter_missing"})
        packet["raw_facts"]["trace_row_count"] = 2
        with self.assertRaisesRegex(TraceVerificationError, "missing, extra"):
            verify_primary_trace(packet)
        packet = copy.deepcopy(run_all_primary_traces()[1].as_mapping())
        packet["observed_state"] = "supervised"
        with self.assertRaisesRegex(TraceVerificationError, "state contradicts"):
            verify_primary_trace(packet)

    def test_restart_conflict_recovery_and_protection_tampering(self):
        ids_and_fact = (("controller_restart", "expired_commands_not_replayed"), ("manual_conflict", "manual_control_wins"), ("interrupted_recovery", "recovery_hold_entered"), ("protected_mislabel_attempt", "protected_workloads_unchanged"))
        for scenario_id, fact in ids_and_fact:
            with self.subTest(scenario_id=scenario_id):
                packet = copy.deepcopy(next(x for x in run_all_primary_traces() if x.scenario_id == scenario_id).as_mapping())
                if scenario_id == "controller_restart": packet["raw_facts"]["session_events"][-1]["payload"]["replayed_execution_commands"] = 1
                elif scenario_id == "manual_conflict": packet["raw_facts"]["scenario_inputs"]["manual_limit_watts"] = 1300
                elif scenario_id == "interrupted_recovery": packet["raw_facts"]["session_events"] = packet["raw_facts"]["session_events"][:3]
                else: packet["raw_facts"]["workloads_after"]["flex"]["current_cap_watts"] = 150
                self.assertFalse(verify_primary_trace(packet).facts[fact])

    def test_id_nonfinite_and_extra_schema_fields_fail_closed(self):
        packet = copy.deepcopy(run_all_primary_traces()[1].as_mapping())
        with self.assertRaisesRegex(TraceVerificationError, "ID mismatch"):
            verify_primary_trace(packet, "meter_stale")
        packet["extra"] = True
        with self.assertRaisesRegex(TraceVerificationError, "schema"):
            verify_primary_trace(packet)
        standard = copy.deepcopy(run_all_standard_primary_traces()[0])
        standard.trace_rows[0]["second"] = float("nan")
        with self.assertRaisesRegex(TraceVerificationError, "canonical JSON"):
            verify_primary_trace(standard)


if __name__ == "__main__":
    unittest.main()
