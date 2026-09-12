import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[1] / "tools" / "check_dco.py"


class DcoCheckTests(unittest.TestCase):
    def repository(self, directory):
        root = Path(directory)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test Contributor"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "contributor" + "@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "base"], cwd=root, check=True)
        return root, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    @staticmethod
    def commit(root, message):
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", message], cwd=root, check=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    @staticmethod
    def check(root, base, head):
        return subprocess.run(
            [sys.executable, str(CHECKER), base, head], cwd=root,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def test_accepts_author_matching_signoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory)
            head = self.commit(root, "safe change\n\nSigned-off-by: Test Contributor <contributor" + "@example.invalid>")
            result = self.check(root, base, head)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("passed for 1 commit", result.stdout)

    def test_rejects_missing_signoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory)
            head = self.commit(root, "unsigned change")
            result = self.check(root, base, head)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(head[:12], result.stderr)

    def test_rejects_different_signer(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory)
            head = self.commit(root, "wrong signer\n\nSigned-off-by: Other Person <other" + "@example.invalid>")
            result = self.check(root, base, head)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("DCO check failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
