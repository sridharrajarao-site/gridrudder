import tempfile
import unittest
from pathlib import Path

from gridgpu.audit import AuditLog
from gridgpu.controller import HeuristicController
from gridgpu.domain import Flexibility, PowerEnvelope, Priority, Workload
from gridgpu.simulator import Simulator


def build_simulator(audit_log=None):
    workloads = [
        Workload(
            "flex",
            Priority.OPPORTUNISTIC,
            2,
            0,
            1_000,
            300,
            Flexibility(True, True, 150),
        )
    ]
    return Simulator(
        workloads,
        [PowerEnvelope(0, 1_400), PowerEnvelope(1, 1_250)],
        HeuristicController(reserve_watts=0),
        fixed_overhead_watts=800,
        cooling_ratio=0,
        control_interval_seconds=1,
        audit_log=audit_log,
        audit_actor="simulation:canonical",
        audit_policy="policy:test-v1",
    )


class SimulatorDurableAuditTests(unittest.TestCase):
    def test_optional_log_persists_every_action_and_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            log = AuditLog(Path(directory) / "simulator.jsonl")
            simulator = build_simulator(log)
            in_memory = simulator.run(3)

            verification = log.verify()
            records = list(log.records())
            self.assertEqual(verification.record_count, len(in_memory))
            self.assertEqual(
                [record["event_type"] for record in records],
                [row["type"] for row in in_memory],
            )
            for record, row in zip(records, in_memory):
                self.assertEqual(record["payload"]["policy"], "policy:test-v1")
                self.assertEqual(
                    {key: value for key, value in record["payload"].items() if key != "policy"},
                    row,
                )
                expected_actor = (
                    "simulation:canonical:telemetry"
                    if row["type"] == "sample"
                    else "simulation:canonical:controller"
                )
                self.assertEqual(record["actor"], expected_actor)

    def test_no_log_preserves_original_in_memory_shape(self):
        audit = build_simulator().run(2)
        self.assertTrue(audit)
        self.assertTrue(all("policy" not in row for row in audit))
        self.assertTrue(all(set(row).isdisjoint({"actor", "record_hash", "sequence"}) for row in audit))

    def test_durable_metadata_does_not_change_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            logged = build_simulator(AuditLog(Path(directory) / "simulator.jsonl")).run(3)
            unlogged = build_simulator().run(3)
        self.assertEqual(logged, unlogged)


if __name__ == "__main__":
    unittest.main()
