import unittest

from gridgpu.integrated_faults import _build, _meter


class SupervisoryHarnessTests(unittest.TestCase):
    def test_normal_flow_records_policy_intent_boundary_outcome_and_mutation(self):
        harness, injector, snapshot, workload = _build()
        harness.run_cycle(step=0, now=_meter().active_power.timestamp_utc, meter=_meter(), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
        phases = [event.phase for event in harness.trace]
        self.assertEqual(phases[:4], ["meter", "authorization", "planner", "validation"])
        self.assertIn("audit", phases)
        self.assertEqual(phases[-1], "outcome")
        self.assertEqual(len(harness.mutations), 1)
        self.assertTrue(harness.mutations[0].scheduler_acknowledged)
        self.assertTrue(harness.mutations[0].adapter_acknowledged)
        self.assertTrue(harness.mutations[0].observed)
        self.assertLess(workload.current_cap_watts, workload.watts_per_gpu)
        injector.require_fully_consumed()

    def test_boundary_rejection_has_durable_intent_but_no_mutation(self):
        from gridgpu.faults import FaultKind
        harness, injector, snapshot, workload = _build(FaultKind.ADAPTER_REJECTION)
        harness.run_cycle(step=0, now=_meter().active_power.timestamp_utc, meter=_meter(), snapshot=snapshot, proposal_id="env-1", execution_id="exec")
        self.assertEqual(harness.mutations, [])
        self.assertIsNone(workload.current_cap_watts)
        self.assertEqual(harness.session.state.value, "safe_hold")
        self.assertEqual([row["event_type"] for row in harness.audit.records], ["action_intent", "action_outcome"])
        injector.require_fully_consumed()


if __name__ == "__main__":
    unittest.main()

