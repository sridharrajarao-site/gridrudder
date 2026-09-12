import math
import subprocess
import unittest

from gridgpu.controller import HeuristicController, SafetyViolation
from gridgpu.domain import Action, Flexibility, PowerEnvelope, Priority, Snapshot, Workload
from gridgpu.nvml import NvidiaSmiShadowAdapter
from gridgpu.simulator import Simulator
from gridgpu.adapters import AdapterError


def flexible_workload(workload_id="flex", current_cap=None):
    return Workload(
        workload_id,
        Priority.OPPORTUNISTIC,
        2,
        0,
        100,
        300,
        Flexibility(may_defer=True, may_power_cap=True, min_power_watts_per_gpu=150),
        state="running",
        current_cap_watts=current_cap,
    )


class DomainValidationTests(unittest.TestCase):
    def test_rejects_invalid_workload_numbers_and_identity(self):
        valid = dict(
            workload_id="work",
            priority=Priority.NORMAL,
            requested_gpus=1,
            arrival_second=0,
            work_units=10,
            watts_per_gpu=200,
        )
        cases = (
            {"workload_id": " "},
            {"priority": "normal"},
            {"requested_gpus": 0},
            {"requested_gpus": True},
            {"arrival_second": -1},
            {"work_units": 0},
            {"work_units": math.nan},
            {"watts_per_gpu": math.inf},
            {"watts_per_gpu": -1},
            {"state": "mystery"},
        )
        for changes in cases:
            values = dict(valid)
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Workload(**values)

    def test_flexibility_and_current_cap_are_consistent(self):
        with self.assertRaises(ValueError):
            Flexibility(may_power_cap=True)
        with self.assertRaises(ValueError):
            Flexibility(may_power_cap=False, min_power_watts_per_gpu=100)
        with self.assertRaises(ValueError):
            flexible_workload(current_cap=100)
        with self.assertRaises(ValueError):
            Workload("work", Priority.NORMAL, 1, 0, 10, 200, current_cap_watts=150)

    def test_envelope_snapshot_and_action_validate_values(self):
        with self.assertRaises(ValueError):
            PowerEnvelope(-1, 100)
        with self.assertRaises(ValueError):
            PowerEnvelope(0, math.nan)
        with self.assertRaises(ValueError):
            Action("set_power_cap", "work", math.inf, "test")
        with self.assertRaises(ValueError):
            Action("", "work", 100, "test")
        work = flexible_workload()
        with self.assertRaises(ValueError):
            Snapshot(0, 1000, 500, [work, work])

    def test_advance_requires_positive_integer_duration(self):
        work = flexible_workload()
        for seconds in (0, -1, True, 1.5):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                work.advance(seconds)


class ActionPlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.controller = HeuristicController()
        self.workload = flexible_workload(current_cap=200)
        self.workloads = {self.workload.workload_id: self.workload}

    def test_unknown_and_invalid_action_objects_fail_as_safety_violations(self):
        with self.assertRaisesRegex(SafetyViolation, "unknown workload"):
            self.controller.validate(
                [Action("set_power_cap", "missing", 180, "test")], self.workloads
            )
        with self.assertRaisesRegex(SafetyViolation, "invalid action object"):
            self.controller.validate([object()], self.workloads)
        with self.assertRaisesRegex(SafetyViolation, "list or tuple"):
            self.controller.validate(None, self.workloads)

    def test_defensively_rejects_corrupted_action_fields_and_mapping(self):
        corrupted = Action("set_power_cap", "flex", 180, "test")
        object.__setattr__(corrupted, "value", math.nan)
        with self.assertRaisesRegex(SafetyViolation, "finite"):
            self.controller.validate([corrupted], self.workloads)

        bad_identity = Action("set_power_cap", "flex", 180, "test")
        object.__setattr__(bad_identity, "workload_id", [])
        with self.assertRaisesRegex(SafetyViolation, "identity"):
            self.controller.validate([bad_identity], self.workloads)

        with self.assertRaisesRegex(SafetyViolation, "mapping identity mismatch"):
            self.controller.validate(
                [Action("set_power_cap", "flex", 180, "test")],
                {"flex": flexible_workload("different", current_cap=200)},
            )

    def test_duplicate_and_conflicting_actions_are_rejected(self):
        actions = [
            Action("set_power_cap", "flex", 180, "one"),
            Action("set_power_cap", "flex", 190, "two"),
        ]
        with self.assertRaisesRegex(SafetyViolation, "duplicate or conflicting"):
            self.controller.validate(actions, self.workloads)

    def test_unsupported_transition_and_empty_restore_are_rejected(self):
        with self.assertRaisesRegex(SafetyViolation, "unsupported"):
            self.controller.validate([Action("defer", "flex", None, "test")], self.workloads)
        uncapped = flexible_workload()
        with self.assertRaisesRegex(SafetyViolation, "nothing to restore"):
            self.controller.validate(
                [Action("set_power_cap", "flex", None, "test")], {"flex": uncapped}
            )

    def test_controller_parameters_must_be_finite_and_nonnegative(self):
        for value in (-1, math.nan, math.inf, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HeuristicController(reserve_watts=value)


class SimulatorConfigurationTests(unittest.TestCase):
    def make_workload(self, workload_id="work"):
        return Workload(workload_id, Priority.CRITICAL, 1, 0, 100, 200)

    def test_rejects_duplicate_workloads_and_envelope_times(self):
        work = self.make_workload()
        with self.assertRaisesRegex(ValueError, "workload IDs"):
            Simulator([work, self.make_workload()], [PowerEnvelope(0, 1000)], HeuristicController())
        with self.assertRaisesRegex(ValueError, "effective seconds"):
            Simulator([work], [PowerEnvelope(0, 1000), PowerEnvelope(0, 900)], HeuristicController())

    def test_rejects_invalid_simulator_configuration(self):
        work = self.make_workload()
        cases = (
            {"envelopes": []},
            {"envelopes": [PowerEnvelope(1, 1000)]},
            {"fixed_overhead_watts": -1},
            {"fixed_overhead_watts": math.nan},
            {"cooling_ratio": -1},
            {"control_interval_seconds": 0},
            {"audit_actor": " "},
            {"audit_policy": ""},
        )
        for changes in cases:
            arguments = {"workloads": [work], "envelopes": [PowerEnvelope(0, 1000)], "controller": HeuristicController()}
            arguments.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Simulator(**arguments)

    def test_simulator_is_single_use_and_duration_is_valid(self):
        sim = Simulator([self.make_workload()], [PowerEnvelope(0, 1000)], HeuristicController())
        with self.assertRaises(ValueError):
            sim.run(0)
        sim.run(1)
        with self.assertRaises(RuntimeError):
            sim.run(1)


class NvidiaSemanticValidationTests(unittest.TestCase):
    def adapter_for(self, output):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        return NvidiaSmiShadowAdapter(runner=runner, which=lambda _: "/usr/bin/nvidia-smi")

    def test_rejects_nonfinite_negative_and_out_of_range_values(self):
        rows = (
            "0, GPU-a, Test, nan, 10, 250, 100, 300\n",
            "0, GPU-a, Test, -1, 10, 250, 100, 300\n",
            "0, GPU-a, Test, 10, 101, 250, 100, 300\n",
            "0, GPU-a, Test, 10, 10, 250, 300, 100\n",
            "0, GPU-a, Test, 10, 10, 350, 100, 300\n",
            "0, GPU-a, , 10, 10, 250, 100, 300\n",
        )
        for row in rows:
            with self.subTest(row=row), self.assertRaises(AdapterError):
                self.adapter_for(row).list_devices()

    def test_rejects_duplicate_device_identity(self):
        row = "0, GPU-a, Test, 10, 10, 250, 100, 300\n"
        with self.assertRaisesRegex(AdapterError, "duplicate"):
            self.adapter_for(row + row).list_devices()

    def test_rejects_duplicate_index_even_when_uuid_differs(self):
        output = (
            "0, GPU-a, Test, 10, 10, 250, 100, 300\n"
            "0, GPU-b, Test, 10, 10, 250, 100, 300\n"
        )
        with self.assertRaisesRegex(AdapterError, "duplicate NVIDIA device index"):
            self.adapter_for(output).list_devices()

    def test_capabilities_fail_closed_on_semantically_bad_output(self):
        capabilities = self.adapter_for(
            "0, GPU-a, Test, 10, 500, 250, 100, 300\n"
        ).capabilities()
        self.assertFalse(capabilities.telemetry_available)
        self.assertFalse(capabilities.power_limit_writable)
        self.assertIn("utilization", capabilities.detail)


if __name__ == "__main__":
    unittest.main()
