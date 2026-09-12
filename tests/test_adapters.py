import subprocess
import unittest

from gridgpu.adapters import (
    AcceleratorDevice,
    AdapterError,
    ReadOnlyAdapterError,
    SimulatedAcceleratorAdapter,
)
from gridgpu.nvml import NvidiaSmiShadowAdapter


def device(device_id="gpu-0"):
    return AcceleratorDevice(device_id, "Sim GPU", 200.0, 75.0, 300.0, 150.0, 350.0)


class SimulatedAcceleratorAdapterTests(unittest.TestCase):
    def test_lists_deterministically_and_changes_only_simulated_limit(self):
        adapter = SimulatedAcceleratorAdapter([device("gpu-b"), device("gpu-a")])
        self.assertEqual([item.device_id for item in adapter.list_devices()], ["gpu-a", "gpu-b"])
        adapter.set_power_limit("gpu-a", 225.0)
        self.assertEqual(adapter.list_devices()[0].power_limit_watts, 225.0)
        self.assertTrue(adapter.capabilities().power_limit_writable)

    def test_rejects_out_of_bounds_and_read_only_writes(self):
        with self.assertRaises(AdapterError):
            SimulatedAcceleratorAdapter([device()]).set_power_limit("gpu-0", 100.0)
        with self.assertRaises(ReadOnlyAdapterError):
            SimulatedAcceleratorAdapter([device()], writable=False).set_power_limit("gpu-0", 200.0)


class NvidiaSmiShadowAdapterTests(unittest.TestCase):
    def test_detects_missing_cli_without_hardware_or_pynvml(self):
        adapter = NvidiaSmiShadowAdapter(which=lambda _: None)
        capabilities = adapter.capabilities()
        self.assertFalse(capabilities.telemetry_available)
        self.assertFalse(capabilities.power_limit_writable)
        self.assertIn("not found", capabilities.detail)
        with self.assertRaises(AdapterError):
            adapter.list_devices()

    def test_parses_cli_csv_and_never_advertises_write_support(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            output = (
                "0, GPU-b, NVIDIA H100 PCIe, 250.5, 91, 350, 200, 350\n"
                "1, GPU-a, NVIDIA L4, N/A, 0, 72, [Not Supported], 72\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        adapter = NvidiaSmiShadowAdapter(runner=runner, which=lambda _: "/usr/bin/nvidia-smi")
        capabilities = adapter.capabilities()
        self.assertTrue(capabilities.telemetry_available)
        self.assertTrue(capabilities.power_limit_visible)
        self.assertFalse(capabilities.power_limit_writable)
        devices = adapter.list_devices()
        self.assertEqual([item.device_id for item in devices], ["GPU-a", "GPU-b"])
        self.assertIsNone(devices[0].power_watts)
        self.assertEqual(devices[1].power_watts, 250.5)
        self.assertEqual(calls[0][0][0], "/usr/bin/nvidia-smi")
        self.assertEqual(calls[0][1]["timeout"], 10)

    def test_query_failure_is_reported_as_unavailable_capability(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 9, stdout="", stderr="driver unavailable")

        adapter = NvidiaSmiShadowAdapter(runner=runner, which=lambda _: "/bin/nvidia-smi")
        capabilities = adapter.capabilities()
        self.assertFalse(capabilities.telemetry_available)
        self.assertIn("driver unavailable", capabilities.detail)

    def test_physical_power_limit_write_is_impossible(self):
        adapter = NvidiaSmiShadowAdapter(which=lambda _: "/bin/nvidia-smi")
        with self.assertRaises(ReadOnlyAdapterError):
            adapter.set_power_limit("GPU-any", 200.0)


if __name__ == "__main__":
    unittest.main()
