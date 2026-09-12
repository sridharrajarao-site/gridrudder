import json
import math
from pathlib import Path
import tempfile
import unittest

from gridgpu.audit import (
    GENESIS_HASH,
    AuditEncodingError,
    AuditIntegrityError,
    AuditLog,
    verify_audit_log,
)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "audit.jsonl"

    def test_empty_missing_log_is_valid(self):
        result = verify_audit_log(self.path)
        self.assertEqual(result.record_count, 0)
        self.assertEqual(result.head_hash, GENESIS_HASH)

    def test_append_builds_verifiable_chain(self):
        log = AuditLog(self.path)
        first = log.append(
            "dispatch.requested",
            {"target_kw": 100, "tags": ["pilot", "manual"]},
            actor="operator:alice",
            timestamp="2026-08-30T12:00:00Z",
        )
        second = log.append(
            "dispatch.approved",
            {"request_sequence": 1},
            actor="operator:bob",
            timestamp="2026-08-30T12:00:01Z",
        )

        result = log.verify()
        self.assertEqual(result.record_count, 2)
        self.assertEqual(result.head_hash, second["record_hash"])
        self.assertEqual(first["previous_hash"], GENESIS_HASH)
        self.assertEqual(second["previous_hash"], first["record_hash"])
        self.assertEqual([record["sequence"] for record in log.records()], [1, 2])

    def test_payload_is_snapshotted_before_append(self):
        source = {"nested": {"value": 1}}
        log = AuditLog(self.path)
        log.append("test", source, actor="tester")
        source["nested"]["value"] = 99
        self.assertEqual(list(log.records())[0]["payload"]["nested"]["value"], 1)

    def test_modified_payload_is_detected(self):
        log = AuditLog(self.path)
        log.append("test", {"value": 1}, actor="tester")
        record = json.loads(self.path.read_text())
        record["payload"]["value"] = 2
        self.path.write_text(json.dumps(record, separators=(",", ":")) + "\n")

        with self.assertRaisesRegex(AuditIntegrityError, "record hash mismatch"):
            log.verify()

    def test_deleted_middle_record_is_detected(self):
        log = AuditLog(self.path)
        for number in range(3):
            log.append("test", {"number": number}, actor="tester")
        lines = self.path.read_text().splitlines(keepends=True)
        self.path.write_text(lines[0] + lines[2])

        with self.assertRaisesRegex(AuditIntegrityError, "invalid sequence"):
            log.verify()

    def test_reordered_records_are_detected(self):
        log = AuditLog(self.path)
        log.append("one", {}, actor="tester")
        log.append("two", {}, actor="tester")
        lines = self.path.read_text().splitlines(keepends=True)
        self.path.write_text(lines[1] + lines[0])

        with self.assertRaisesRegex(AuditIntegrityError, "invalid sequence"):
            log.verify()

    def test_truncated_record_is_detected(self):
        log = AuditLog(self.path)
        log.append("test", {}, actor="tester")
        self.path.write_bytes(self.path.read_bytes()[:-1])

        with self.assertRaisesRegex(AuditIntegrityError, "incomplete record"):
            log.verify()

    def test_append_refuses_to_extend_corrupt_log(self):
        log = AuditLog(self.path)
        log.append("test", {}, actor="tester")
        self.path.write_text("not-json\n")

        with self.assertRaisesRegex(AuditIntegrityError, "invalid JSON"):
            log.append("another", {}, actor="tester")
        self.assertEqual(self.path.read_text(), "not-json\n")

    def test_rejects_noncanonical_json_values(self):
        log = AuditLog(self.path)
        for bad_value in (math.nan, object()):
            with self.subTest(bad_value=repr(bad_value)):
                with self.assertRaises(AuditEncodingError):
                    log.append("test", {"unsupported": bad_value}, actor="tester")

    def test_rejects_blank_identity_fields(self):
        for event_type, actor in (
            ("", "tester"),
            ("test", ""),
            ("   ", "tester"),
            ("test", "   "),
        ):
            with self.subTest(event_type=event_type, actor=actor):
                with self.assertRaises(ValueError):
                    AuditLog(self.path).append(event_type, {}, actor=actor)


if __name__ == "__main__":
    unittest.main()
