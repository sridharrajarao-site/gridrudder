from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gridgpu.recovery_journal import (
    RecoveryError, RecoveryIntent, RecoveryJournal, RecoveryObservation,
    journal_then_actuate, plan_recovery,
)


class RecoveryJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trial.jsonl"
        self.journal = RecoveryJournal(self.path)
        self.intent = RecoveryIntent("trial", "host", "GPU-abc", "a" * 64, 175, 125,
                                     "2030-01-01T00:00:00+00:00")
        self.observation = RecoveryObservation("host", "GPU-abc", 175,
                                              "2030-01-01T00:01:00+00:00", "pinned-local-reader")

    def test_missing_journal_fails_closed(self):
        with self.assertRaises(RecoveryError):
            self.journal.read()

    def test_durable_intent_precedes_callback(self):
        events = []
        with patch("gridgpu.recovery_journal.os.fsync", side_effect=lambda _: events.append("fsync")):
            journal_then_actuate(self.journal, self.intent, lambda: events.append("actuate"))
        self.assertEqual(events, ["fsync", "fsync", "actuate"])
        self.assertEqual(plan_recovery(self.journal.read()), "unfinished_observe_device")

    def test_failed_durability_blocks_action(self):
        calls = []
        with patch("gridgpu.recovery_journal.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                journal_then_actuate(self.journal, self.intent, lambda: calls.append(1))
        self.assertEqual(calls, [])

    def test_callback_crash_leaves_unfinished_intent(self):
        def fail():
            raise RuntimeError("lost process")
        with self.assertRaises(RuntimeError):
            journal_then_actuate(self.journal, self.intent, fail)
        self.assertIsNone(self.journal.read().restored_observation)

    def test_existing_journal_cannot_be_reused(self):
        self.journal.create(self.intent)
        with self.assertRaises(RecoveryError):
            journal_then_actuate(self.journal, self.intent, lambda: self.fail("must not act"))

    def test_corrupt_torn_or_modified_journal_rejected(self):
        self.journal.create(self.intent)
        original = self.path.read_bytes()
        for data in (b"", b"{}\n", original[:-1], original.replace(b"175", b"180"), original + b"broken\n"):
            self.path.write_bytes(data)
            with self.subTest(data=data[:20]), self.assertRaises(RecoveryError):
                self.journal.read()

    def test_symlink_refused(self):
        real = self.path.with_name("real.jsonl")
        real.write_text("not evidence")
        self.path.symlink_to(real)
        with self.assertRaises(RecoveryError):
            self.journal.read()

    def test_verified_restoration_closes_durably(self):
        self.journal.create(self.intent)
        self.assertEqual(plan_recovery(self.journal.read(), self.observation), "unfinished_record_verified_restoration")
        with patch("gridgpu.recovery_journal.os.fsync") as fsync:
            self.journal.close_restored(self.observation)
            fsync.assert_called_once()
        self.assertEqual(plan_recovery(self.journal.read()), "closed_historical_record")
        with self.assertRaises(RecoveryError):
            self.journal.close_restored(self.observation)

    def test_nonoriginal_limit_requires_attended_recovery(self):
        self.journal.create(self.intent)
        capped = replace(self.observation, power_limit_watts=125)
        self.assertEqual(plan_recovery(self.journal.read(), capped), "unfinished_attended_restoration_required")
        with self.assertRaises(RecoveryError):
            self.journal.close_restored(capped)

    def test_bad_observation_cannot_close(self):
        self.journal.create(self.intent)
        for changes in (dict(host_id="other"), dict(gpu_uuid="other"), dict(source_id=""),
                        dict(power_limit_watts=float("nan")), dict(power_limit_watts=True),
                        dict(observed_at_utc="2029-01-01T00:00:00Z"), dict(observed_at_utc="2030-01-01")):
            with self.subTest(changes=changes), self.assertRaises(RecoveryError):
                self.journal.close_restored(replace(self.observation, **changes))

    def test_invalid_intent_rejected(self):
        for changes in (dict(target_watts=180), dict(original_watts=float("inf")),
                        dict(authorization_sha256="bad"), dict(created_at_utc="yesterday")):
            with self.assertRaises(RecoveryError):
                replace(self.intent, **changes)

    def test_closure_chain_tampering_rejected(self):
        self.journal.create(self.intent)
        self.journal.close_restored(self.observation)
        rows = self.path.read_text().splitlines()
        closure = json.loads(rows[1])
        closure["previous_sha256"] = "0" * 64
        self.path.write_text(rows[0] + "\n" + json.dumps(closure) + "\n")
        with self.assertRaises(RecoveryError):
            self.journal.read()

    def test_closure_fsync_failure_poisoned_for_current_process(self):
        self.journal.create(self.intent)
        with patch("gridgpu.recovery_journal.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(RecoveryError, "uncertain"):
                self.journal.close_restored(self.observation)
        # Even a complete readable closure is not acknowledged as durable.
        self.assertEqual(len(self.path.read_bytes().splitlines()), 2)
        with self.assertRaisesRegex(RecoveryError, "uncertain"):
            self.journal.read()
        with self.assertRaisesRegex(RecoveryError, "uncertain"):
            self.journal.close_restored(self.observation)

    def test_partial_closure_write_rejected_after_reopen(self):
        self.journal.create(self.intent)
        real_fdopen = os.fdopen

        def partial_stream(*args, **kwargs):
            stream = real_fdopen(*args, **kwargs)
            proxy = MagicMock(wraps=stream)
            proxy.__enter__.return_value = proxy
            proxy.__exit__.side_effect = stream.__exit__

            def fail_write(data):
                stream.write(data[:len(data) // 2])
                stream.flush()
                raise OSError("partial disk write")

            proxy.write.side_effect = fail_write
            return proxy

        with patch("gridgpu.recovery_journal.os.fdopen", side_effect=partial_stream):
            with self.assertRaisesRegex(RecoveryError, "uncertain"):
                self.journal.close_restored(self.observation)
        with self.assertRaisesRegex(RecoveryError, "uncertain"):
            self.journal.read()
        with self.assertRaisesRegex(RecoveryError, "corrupt"):
            RecoveryJournal(self.path).read()


if __name__ == "__main__":
    unittest.main()
