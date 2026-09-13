from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gridgpu.performance_trial import GpuPreflight
from gridgpu.recovery_journal import RecoveryError, RecoveryIntent, RecoveryJournal, RecoveryObservation
from gridgpu.supervised_recovery import JournaledPowerControl, RecoveryApproval, intent_digest, reconcile_attended_once


class SupervisedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.journal = RecoveryJournal(self.directory / "intent.jsonl")
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.intent = RecoveryIntent("trial", "host", "GPU-a", "a" * 64, 175, 125, self.now.isoformat())
        self.limit = 175
        self.writes = []
        self.fail_write = False
        self.wrapper = JournaledPowerControl(self, self.journal, self.intent,
            verify_intent=lambda _: True, clock=lambda: self.now, observation_source="trusted")

    def preflight(self):
        return (GpuPreflight("GPU-a", True, False, "550", "b" * 64),)

    def observe_limit(self, _):
        return self.limit

    def set_limit(self, uuid, watts):
        self.assertEqual(uuid, "GPU-a")
        self.assertEqual(self.journal.read().intent, self.intent)
        self.writes.append(watts)
        self.limit = watts
        if self.fail_write:
            self.fail_write = False
            raise TimeoutError("write may have completed")

    def test_cap_intent_and_verified_restoration(self):
        self.wrapper.preflight()
        self.wrapper.set_limit("GPU-a", 125)
        self.assertIsNone(self.journal.read().restored_observation)
        self.wrapper.set_limit("GPU-a", 175)
        self.wrapper.set_limit("GPU-a", 175)
        self.assertEqual(self.writes, [125, 175])
        self.assertEqual(self.journal.read().restored_observation.power_limit_watts, 175)

    def test_intent_durability_failure_blocks_write(self):
        self.wrapper.preflight()
        with patch("gridgpu.recovery_journal.os.fsync", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.wrapper.set_limit("GPU-a", 125)
        self.assertEqual(self.writes, [])
        self.wrapper.set_limit("GPU-a", 175)  # Verified unchanged, no write required.

    def test_partial_cap_timeout_still_restores(self):
        self.wrapper.preflight()
        self.fail_write = True
        with self.assertRaises(TimeoutError):
            self.wrapper.set_limit("GPU-a", 125)
        self.wrapper.set_limit("GPU-a", 175)
        self.assertEqual(self.limit, 175)
        self.assertIsNotNone(self.journal.read().restored_observation)

    def test_scope_authorization_and_replay_rejected(self):
        self.wrapper.preflight()
        for uuid, watts in (("other", 125), ("GPU-a", 130), ("GPU-a", True)):
            with self.assertRaises(RecoveryError):
                self.wrapper.set_limit(uuid, watts)
        self.wrapper.verify_intent = lambda _: False
        with self.assertRaises(RecoveryError):
            self.wrapper.set_limit("GPU-a", 125)
        self.assertEqual(self.writes, [])
        self.wrapper.verify_intent = lambda _: True
        self.wrapper.set_limit("GPU-a", 125)
        with self.assertRaises(RecoveryError):
            self.wrapper.set_limit("GPU-a", 125)

    def approval(self):
        return RecoveryApproval(intent_digest(self.intent), "operator", "fresh-nonce", "2030-01-01T01:00:00Z")

    def recover(self, **changes):
        def restore(intent):
            self.writes.append(intent.original_watts)
            self.limit = intent.original_watts
        options = dict(lock_directory=self.directory, process_gone=lambda: True,
            verify_and_consume=lambda _: True, confirm=lambda phrase: phrase,
            observe=lambda intent: RecoveryObservation(intent.host_id, intent.gpu_uuid, self.limit,
                                                       self.now.isoformat(), "trusted"),
            restore=restore, clock=lambda: self.now, monotonic=lambda: 0.0, source_id="trusted")
        approval = changes.pop("approval", self.approval())
        options.update(changes)
        return reconcile_attended_once(self.journal, approval, **options)

    def test_process_loss_simulation_reopens_and_recovers(self):
        self.wrapper.preflight()
        self.wrapper.set_limit("GPU-a", 125)
        # Drop the wrapper without a restoration call, simulating lost process state.
        self.wrapper = None
        self.journal = RecoveryJournal(self.directory / "intent.jsonl")
        self.assertEqual(self.recover(), "verified_restoration_recorded")
        self.assertEqual(self.writes, [125, 175])
        self.assertEqual(self.recover(), "already_closed_historical_record")
        self.assertEqual(self.writes, [125, 175])

    def test_live_process_and_bad_authorization_block_recovery(self):
        self.journal.create(self.intent)
        self.limit = 125
        for changes in (dict(process_gone=lambda: False), dict(verify_and_consume=lambda _: False),
                        dict(confirm=lambda _: "no"), dict(approval=replace(self.approval(), intent_sha256="b" * 64)),
                        dict(approval=replace(self.approval(), expires_at_utc="2029-01-01T00:00:00Z"))):
            with self.assertRaises(RecoveryError):
                self.recover(**changes)
        self.assertEqual(self.writes, [])

    def test_stale_and_wrong_device_observation_block(self):
        self.journal.create(self.intent)
        for host, time in (("wrong", self.now.isoformat()), ("host", "2029-01-01T00:00:00Z")):
            with self.assertRaises(RecoveryError):
                self.recover(observe=lambda _: RecoveryObservation(host, "GPU-a", 125, time, "trusted"))
        self.assertEqual(self.writes, [])

    def test_recovery_mismatch_never_closes(self):
        self.journal.create(self.intent)
        self.limit = 125
        with self.assertRaisesRegex(RecoveryError, "did not verify"):
            self.recover(restore=lambda _: None)
        self.assertIsNone(self.journal.read().restored_observation)

    def test_deadline_failure_never_closes(self):
        self.journal.create(self.intent)
        times = iter((0.0, 11.0))
        with self.assertRaisesRegex(RecoveryError, "deadline"):
            self.recover(monotonic=lambda: next(times))
        self.assertIsNone(self.journal.read().restored_observation)
        self.assertEqual(self.writes, [])

    def test_closure_uncertainty_preserves_hardware_restoration(self):
        self.wrapper.preflight()
        self.wrapper.set_limit("GPU-a", 125)
        with patch("gridgpu.recovery_journal.os.fsync", side_effect=OSError("disk")):
            with self.assertRaisesRegex(RecoveryError, "uncertain"):
                self.wrapper.set_limit("GPU-a", 175)
        self.assertEqual(self.limit, 175)
        with self.assertRaises(RecoveryError):
            self.journal.read()


if __name__ == "__main__":
    unittest.main()
