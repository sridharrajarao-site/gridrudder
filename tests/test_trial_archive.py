import json
from pathlib import Path
import tempfile
import unittest

from gridgpu.trial_archive import ArchiveError, verify_trial_archive, write_trial_archive


class TrialArchiveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        self.path = self.directory / "evidence.json"

    def write(self, **overrides):
        args = dict(evidence_kind="simulated", config={"trial": "fixture"},
            outcome={"status": "failed", "error": "fixture failure"}, measurements=[],
            command_evidence=[], recovery_state=None,
            runtime={"python": "fixture"}, qualification={"status": "not_qualified"})
        args.update(overrides)
        return write_trial_archive(self.path, **args)

    def test_roundtrip_private_failed_trial(self):
        self.assertEqual(len(self.write()), 64)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(verify_trial_archive(self.path)["outcome"]["status"], "failed")

    def test_no_overwrite(self):
        self.write()
        with self.assertRaises(FileExistsError):
            self.write()

    def test_corruption(self):
        self.write()
        document = json.loads(self.path.read_text())
        document["payload"]["outcome"] = {"status": "passed"}
        self.path.write_text(json.dumps(document) + "\n")
        with self.assertRaisesRegex(ArchiveError, "digest"):
            verify_trial_archive(self.path)

    def test_fail_closed_before_write(self):
        for override in ({"evidence_kind": "physical_qualified"}, {"runtime": {}},
                         {"measurements": [float("nan")]}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.write(**override)
            self.assertFalse(self.path.exists())

    def test_shared_directory_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaises(ArchiveError):
            self.write()
