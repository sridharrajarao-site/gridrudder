import copy
import unittest

from gridgpu.controller import HeuristicController, SafetyViolation
from gridgpu.domain import Action, Flexibility, PowerEnvelope, Priority, Workload
from gridgpu.simulator import Simulator


def scenario():
    workloads = [
        Workload("critical", Priority.CRITICAL, 2, 0, 20_000, 300),
        Workload("flex", Priority.OPPORTUNISTIC, 8, 0, 20_000, 350, Flexibility(True, True, 180)),
    ]
    envelopes = [PowerEnvelope(0, 6_000), PowerEnvelope(20, 3_800), PowerEnvelope(80, 6_000)]
    return workloads, envelopes


class SimulatorTests(unittest.TestCase):
    def test_follows_feasible_envelope_and_protects_critical_work(self):
        workloads, envelopes = scenario()
        sim = Simulator(workloads, envelopes, HeuristicController())
        audit = sim.run(120)
        constrained = [r for r in audit if r["type"] == "sample" and 25 <= r["second"] < 80]
        self.assertTrue(all(r["facility_power_watts"] <= r["envelope_watts"] for r in constrained))
        critical = sim.workloads["critical"]
        self.assertEqual(critical.state, "running")
        self.assertIsNone(critical.current_cap_watts)

    def test_recovery_does_not_rebound_over_envelope(self):
        workloads, envelopes = scenario()
        sim = Simulator(workloads, envelopes, HeuristicController(recovery_step_watts=25))
        audit = sim.run(120)
        recovery = [r for r in audit if r["type"] == "sample" and r["second"] >= 80]
        self.assertTrue(all(r["facility_power_watts"] <= r["envelope_watts"] for r in recovery))

    def test_deterministic_replay(self):
        workloads, envelopes = scenario()
        sim1 = Simulator(copy.deepcopy(workloads), envelopes, HeuristicController())
        sim2 = Simulator(copy.deepcopy(workloads), envelopes, HeuristicController())
        self.assertEqual(sim1.run(60), sim2.run(60))

    def test_validator_rejects_protected_workload_action(self):
        workload = Workload("protected", Priority.CRITICAL, 1, 0, 100, 300)
        controller = HeuristicController()
        with self.assertRaises(SafetyViolation):
            controller.validate([Action("set_power_cap", "protected", 200, "bad")], {"protected": workload})


if __name__ == "__main__":
    unittest.main()
