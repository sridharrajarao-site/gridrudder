import json
from pathlib import Path
import tempfile
import unittest

from gridgpu.manifest import build_artifact_manifest, file_sha256, verify_manifest_files, write_new_manifest


class ArtifactManifestTests(unittest.TestCase):
    def test_snapshots_real_source_tests_specs_runtime_and_configuration(self):
        project = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory).resolve()
            manifest = build_artifact_manifest(
                project,
                packet,
                scenario_definitions=[{"scenario_id": "one"}],
                controller_parameters={"reserve_watts": 100},
                gate_requirements=[{"scenario_id": "one"}],
                test_command=["python3", "-m", "unittest"],
            )
            path = write_new_manifest(packet, manifest)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(verify_manifest_files(packet, loaded))
            self.assertTrue(any(item["project_path"].startswith("gridgpu/") for item in loaded["files"]))
            self.assertTrue(any(item["project_path"].startswith("tests/") for item in loaded["files"]))
            self.assertTrue(any(item["project_path"] == "docs/gate-b-spec.md" for item in loaded["files"]))
            self.assertTrue(loaded["runtime"]["python_version"])
            self.assertEqual(loaded["controller_parameters"]["reserve_watts"], 100)
            self.assertEqual(len(file_sha256(path)), 64)

    def test_verifier_detects_snapshot_tampering_and_manifest_refuses_overwrite(self):
        project = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory).resolve()
            manifest = build_artifact_manifest(
                project, packet,
                scenario_definitions=[{"scenario_id": "one"}],
                controller_parameters={"reserve_watts": 100},
                gate_requirements=[{"scenario_id": "one"}],
                test_command=["python3", "-m", "unittest"],
            )
            write_new_manifest(packet, manifest)
            with self.assertRaises(Exception):
                write_new_manifest(packet, manifest)
            target = packet / manifest["files"][0]["path"]
            target.write_bytes(target.read_bytes() + b"tamper")
            self.assertTrue(verify_manifest_files(packet, manifest))


if __name__ == "__main__":
    unittest.main()
