from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from gridgpu.local_approval import LocalApprovalAuthority, LocalApprovalError
from gridgpu.performance_trial import PerformanceTrialConfig, OperatorAuthorization
from gridgpu.recovery_journal import RecoveryIntent
from gridgpu.supervised_recovery import RecoveryApproval, intent_digest


class LocalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve() / "approvals"
        self.directory.mkdir(mode=0o700)
        self.now = datetime(2026, 9, 13, tzinfo=timezone.utc)
        self.authority = LocalApprovalAuthority(self.directory, clock=lambda: self.now)
        self.authority.initialize()
        self.config = PerformanceTrialConfig("host", "gpu", "work", "a" * 64,
                                             125, "meter", "chassis")
        self.approval = OperatorAuthorization.bind(self.config, approval_id="a", operator="operator",
            nonce="unique", expires_at_utc="2026-09-13T01:00:00+00:00")
        self.intent = RecoveryIntent("trial", "host", "gpu", self.approval.binding_sha256,
                                     175, 125, "2026-09-13T00:00:00+00:00")
        self.signed = self.authority.issue_trial(self.config, self.approval, self.intent)

    def verify(self, **changes):
        values = dict(config=self.config, authorization=self.approval,
                      intent=self.intent, signed=self.signed)
        values.update(changes)
        return self.authority.verify_trial(**values)

    def test_restart_replay_rejected(self):
        self.assertTrue(self.verify())
        self.authority = LocalApprovalAuthority(self.directory, clock=lambda: self.now)
        self.assertFalse(self.verify())

    def test_concurrent_claim_only_one_winner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: self.verify(), range(16)))
        self.assertEqual(sum(outcomes), 1)

    def test_config_intent_operator_signature_tamper(self):
        for changes in [dict(config=replace(self.config, sample_seconds=20)),
                        dict(intent=replace(self.intent, original_watts=180)),
                        dict(authorization=replace(self.approval, operator="other")),
                        dict(signed=replace(self.signed, signature="f" * 64))]:
            self.assertFalse(self.verify(**changes))
        self.assertTrue(self.verify())

    def test_expiry_and_naive_clock(self):
        self.now = datetime(2026, 9, 13, 1, tzinfo=timezone.utc)
        self.assertFalse(self.verify())
        self.now = datetime(2026, 9, 13)
        self.assertFalse(self.verify())

    def test_key_permissions_and_directory_permissions(self):
        (self.directory / "key").chmod(0o644)
        self.assertFalse(self.verify())
        (self.directory / "key").chmod(0o600)
        self.directory.chmod(0o755)
        self.assertFalse(self.verify())

    def test_symlink_key_rejected(self):
        key = self.directory / "key"
        key.rename(self.directory / "other")
        key.symlink_to("other")
        self.assertFalse(self.verify())

    def test_hardlink_key_rejected(self):
        os.link(self.directory / "key", self.directory / "other")
        self.assertFalse(self.verify())

    def test_symlink_parent_rejected(self):
        link = Path(self.temp.name).resolve() / "alias"
        link.symlink_to(self.directory, target_is_directory=True)
        self.authority = LocalApprovalAuthority(link, clock=lambda: self.now)
        self.assertFalse(self.verify())

    def test_existing_empty_claim_is_consumed(self):
        filename = "used-" + hashlib.sha256(self.approval.nonce.encode()).hexdigest()
        (self.directory / filename).touch(mode=0o600)
        self.assertFalse(self.verify())

    def test_recovery_bound_and_consumed(self):
        approval = RecoveryApproval(intent_digest(self.intent), "operator", "recovery-nonce",
                                    self.approval.expires_at_utc)
        signed = self.authority.issue_recovery(self.intent, approval)
        self.assertFalse(self.authority.verify_recovery(replace(self.intent, original_watts=180), approval, signed))
        self.assertTrue(self.authority.verify_recovery(self.intent, approval, signed))
        self.assertFalse(self.authority.verify_recovery(self.intent, approval, signed))

    def test_purpose_and_nonce_namespace(self):
        approval = RecoveryApproval(intent_digest(self.intent), "operator", self.approval.nonce,
                                    self.approval.expires_at_utc)
        signed = self.authority.issue_recovery(self.intent, approval)
        self.assertFalse(self.authority.verify_recovery(self.intent, approval, self.signed))
        self.assertTrue(self.verify())
        self.assertFalse(self.authority.verify_recovery(self.intent, approval, signed))

    def test_nonconsuming_check_and_no_key_overwrite(self):
        self.assertTrue(self.verify(consume=False))
        self.assertTrue(self.verify())
        with self.assertRaises(FileExistsError):
            self.authority.initialize()


if __name__ == "__main__":
    unittest.main()
