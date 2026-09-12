import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gridgpu.alignment import AlignmentPolicy, HostOverheadModel
from gridgpu.gpu_observer import ExecutableProvenance, QualifiedGpuPowerObservation
from gridgpu.qualification import (
    BmcPowerObserver, QualificationError, collect_read_only_qualification,
    qualification_packet_document,
)
from gridgpu.telemetry import FreshnessPolicy, Quality


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class Clock:
    def __init__(self): self.index = 0
    def __call__(self):
        value = NOW + timedelta(seconds=self.index)
        self.index += 0.01
        return value


class FakeGpu:
    host_alias = "host-a"
    def __init__(self): self.sequence = 0
    def collect(self):
        at = NOW + timedelta(seconds=self.sequence * 0.02)
        provenance = ExecutableProvenance("/trusted/nvidia-smi", "a"*64, 0, 0, 0o755, False)
        result = QualifiedGpuPowerObservation(at, at + timedelta(milliseconds=10), 125.0,
            "host-a:GPU-a", Quality.GOOD, "host-a", "GPU-a", "gpu-epoch", self.sequence,
            provenance, "550.1", 10.0)
        self.sequence += 1
        return (result,)


class QualificationTests(unittest.TestCase):
    def build_bmc(self, directory, calls):
        executable = Path(directory)/"ipmitool"
        executable.write_text("tool")
        executable.chmod(0o755)
        clock = Clock(); monotonic_values = iter(range(100))
        def runner(command, **kwargs):
            calls.append(tuple(command))
            output = ("Chassis Serial : chassis-a\n" if command[1:] == ("fru", "print", "0")
                      else "Instantaneous power reading: 225 Watts\n")
            return subprocess.CompletedProcess(command, 0, output, "")
        return BmcPowerObserver(host_id="host-a", expected_chassis_id="chassis-a",
            meter_id="bmc-a", physical_boundary="host-psu-input", source_epoch="bmc-epoch",
            executable=executable, runner=runner, clock=clock,
            monotonic=lambda: next(monotonic_values), required_owner_uid=os.getuid(),
            clock_synchronized=True)

    def test_packet_feeds_existing_validation_and_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]; bmc=self.build_bmc(directory, calls)
            packet = collect_read_only_qualification(host_id="host-a", chassis_id="chassis-a",
                gpu_uuid="GPU-a", meter_id="bmc-a", expected_physical_boundary="host-psu-input",
                gpu_observer=FakeGpu(), bmc_observer=bmc, samples=3,
                overhead_model=HostOverheadModel(100, 0, 90, 110, "lab-cal"),
                alignment_policy=AlignmentPolicy(1, 1, 5, 5000),
                freshness_policy=FreshnessPolicy(5, 5000), clock_synchronized=True,
                sleeper=lambda _: None, sample_interval_seconds=0)
            self.assertTrue(packet.qualified)
            self.assertEqual(3, len(packet.alignment.pairs))
            document = qualification_packet_document(packet)
            self.assertEqual(64, len(document["packet_sha256"]))
            json.dumps(document, sort_keys=True, allow_nan=False)
            self.assertTrue(all(command[1:] in (("fru", "print", "0"),
                                                ("dcmi", "power", "reading")) for command in calls))
            self.assertFalse(any("-pl" in command or "-pm" in command for command in calls))

    def test_wrong_chassis_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]; bmc=self.build_bmc(directory, calls)
            bmc.expected_chassis_id = "other"
            with self.assertRaisesRegex(QualificationError, "chassis"):
                bmc.collect()

    def test_bmc_executable_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]; bmc=self.build_bmc(directory, calls)
            Path(bmc.provenance.resolved_path).write_text("changed")
            with self.assertRaisesRegex(QualificationError, "provenance changed"):
                bmc.collect()


if __name__ == "__main__": unittest.main()
