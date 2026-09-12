import unittest

from gridgpu.controller import HeuristicController
from gridgpu.domain import Flexibility, PowerEnvelope, Priority, Workload
from gridgpu.simulator import Simulator


class FailingAuditLog:
    def __init__(self, fail_on_call):
        self.fail_on_call = fail_on_call
        self.calls = 0

    def append(self, event_type, payload, *, actor):
        del event_type, payload, actor
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise OSError("audit unavailable")


class SimulatorAssuranceTests(unittest.TestCase):
    def test_interval_power_is_sampled_before_completion_mutation(self):
        workload = Workload("one-tick", Priority.CRITICAL, 1, 0, 1, 300)
        simulator = Simulator(
            [workload],
            [PowerEnvelope(0, 2_000)],
            HeuristicController(reserve_watts=0),
            fixed_overhead_watts=100,
            cooling_ratio=0,
            control_interval_seconds=1,
        )
        records = simulator.run(1)
        sample = next(row for row in records if row["type"] == "sample")
        self.assertEqual(sample["facility_power_watts"], 400)
        self.assertEqual(sample["workloads"]["one-tick"]["state"], "running")
        self.assertEqual(workload.state, "completed")

    def test_action_intent_precedes_mutation_and_outcome_follows(self):
        workload = Workload(
            "flex", Priority.OPPORTUNISTIC, 2, 0, 100, 300, Flexibility(True, True, 150)
        )
        simulator = Simulator(
            [workload],
            [PowerEnvelope(0, 1_500), PowerEnvelope(1, 1_000)],
            HeuristicController(reserve_watts=0),
            fixed_overhead_watts=800,
            cooling_ratio=0,
            control_interval_seconds=1,
        )
        records = simulator.run(2)
        intent_index = next(i for i, row in enumerate(records) if row["type"] == "action_intent")
        outcome_index = next(i for i, row in enumerate(records) if row["type"] == "action_outcome")
        self.assertLess(intent_index, outcome_index)
        self.assertGreater(
            records[outcome_index]["power_before_watts"], records[outcome_index]["power_after_watts"]
        )

    def test_audit_intent_failure_prevents_admission_mutation(self):
        workload = Workload("critical", Priority.CRITICAL, 1, 0, 100, 300)
        simulator = Simulator(
            [workload],
            [PowerEnvelope(0, 1_000)],
            HeuristicController(),
            audit_log=FailingAuditLog(fail_on_call=1),
        )
        with self.assertRaises(OSError):
            simulator.run(1)
        self.assertEqual(workload.state, "queued")
        self.assertEqual(simulator.audit, [])

    def test_audit_outcome_failure_rolls_back_action_mutation(self):
        workload = Workload(
            "flex",
            Priority.OPPORTUNISTIC,
            1,
            0,
            100,
            300,
            Flexibility(True, True, 150),
            state="running",
        )
        # decision succeeds, action intent succeeds, action outcome fails.
        simulator = Simulator(
            [workload],
            [PowerEnvelope(0, 1_200)],
            HeuristicController(reserve_watts=0),
            fixed_overhead_watts=1_000,
            cooling_ratio=0,
            control_interval_seconds=1,
            audit_log=FailingAuditLog(fail_on_call=3),
        )
        with self.assertRaises(OSError):
            simulator.run(1)
        self.assertIsNone(workload.current_cap_watts)
        self.assertEqual([row["type"] for row in simulator.audit], ["decision", "action_intent"])

    def test_infeasible_control_emits_quantified_shortfall_and_no_action(self):
        workload = Workload("critical", Priority.CRITICAL, 1, 0, 100, 300)
        records = Simulator(
            [workload],
            [PowerEnvelope(0, 1_200)],
            HeuristicController(reserve_watts=0),
            fixed_overhead_watts=1_000,
            cooling_ratio=0,
            control_interval_seconds=1,
        ).run(1)
        no_action = next(row for row in records if row["type"] == "no_action")
        shortfall = next(row for row in records if row["type"] == "shortfall")
        self.assertEqual(no_action["magnitude_watts"], 100)
        self.assertEqual(shortfall["magnitude_watts"], 100)
        self.assertEqual(shortfall["protected_constraints"], ["critical"])
        self.assertIn("prevents_compliance", shortfall["reason"])


if __name__ == "__main__":
    unittest.main()
