import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gridgpu.qualification_cli import QualificationCliError, load_config, run_local_read_only


class Clock:
    def __init__(self): self.value = 0
    def __call__(self):
        result = datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=self.value)
        self.value += 5
        return result


class QualificationCliTests(unittest.TestCase):
    def setup_files(self, directory):
        root = Path(directory)
        nvidia = root/"nvidia-smi"; ipmi = root/"ipmitool"
        for path in (nvidia, ipmi): path.write_text("fixed"); path.chmod(0o755)
        config = {
            "schema":"gridrudder-read-only-qualification-config:v1",
            "host_id":"host-a", "chassis_id":"chassis-a", "gpu_uuid":"GPU-a",
            "meter_id":"bmc-a", "physical_boundary":"host-psu-input",
            "gpu_source_epoch":"gpu-e1", "bmc_source_epoch":"bmc-e1",
            "nvidia_smi_path":str(nvidia), "ipmitool_path":str(ipmi),
            "clock_synchronized":True, "samples":3, "sample_interval_seconds":0,
            "maximum_skew_seconds":1, "minimum_coverage":1,
            "maximum_observation_age_seconds":5, "maximum_ingest_latency_ms":5000,
            "overhead_fixed_watts":100, "overhead_dynamic_fraction":0,
            "minimum_boundary_delta_watts":90, "maximum_boundary_delta_watts":110,
            "calibration_id":"lab-cal-v1"
        }
        config_path=root/"config.json"; config_path.write_text(json.dumps(config))
        return config, config_path, root/"packet.json"

    @staticmethod
    def runner(command, **kwargs):
        if command[0].endswith("ipmitool"):
            output = ("Chassis Serial : chassis-a\n" if command[1] == "fru"
                      else "Instantaneous power reading: 225 Watts\n")
        elif "driver_version" in command[1]:
            output = "GPU-a, 550.1\n"
        else:
            output = "0, GPU-a, RTX Test, 125, 100, 175, 125, 175\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    def test_local_wrapper_writes_new_canonical_qualified_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config_path, output = self.setup_files(directory)
            ticks=iter(range(100))
            document = run_local_read_only(config_path, output, runner=self.runner,
                clock=Clock(), monotonic=lambda: next(ticks)/1000, sleeper=lambda _: None,
                trusted_owner_uid=os.getuid())
            self.assertTrue(document["packet"]["qualified"])
            self.assertEqual(document, json.loads(output.read_text()))
            self.assertEqual(0o600, output.stat().st_mode & 0o777)

    def test_extra_field_and_false_clock_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config, config_path, _ = self.setup_files(directory)
            config["unexpected"] = True; config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(QualificationCliError, "exactly"):
                load_config(config_path)
            config.pop("unexpected"); config["clock_synchronized"] = False
            config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(QualificationCliError, "explicitly true"):
                load_config(config_path)

    def test_output_refuses_overwrite_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            _, config_path, output = self.setup_files(directory); output.write_text("keep")
            with self.assertRaisesRegex(QualificationCliError, "new absolute"):
                run_local_read_only(config_path, output, runner=lambda *a, **k: self.fail("command ran"),
                    trusted_owner_uid=os.getuid())
            self.assertEqual("keep", output.read_text())

    def test_only_fixed_read_commands_are_possible(self):
        source = Path(__file__).parents[1]/"gridgpu"/"qualification_cli.py"
        text = source.read_text()
        self.assertNotIn('"-pl"', text)
        self.assertNotIn('"-pm"', text)
        self.assertNotIn("ssh", text.lower())


if __name__ == "__main__": unittest.main()
