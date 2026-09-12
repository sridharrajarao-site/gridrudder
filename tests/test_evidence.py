from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
import tempfile
import unittest

from gridgpu.audit import AuditLog
from gridgpu.evidence import EvidenceError, canonical_sha256, package_release_evidence
from gridgpu.gates import ScenarioRequirement, evaluate_gate_b


def result(scenario_id="scenario_one"):
    trace = {"schema_version": 1, "scenario_id": scenario_id, "rows": [{"sequence": 1, "watts": 1000.0}]}
    digest = canonical_sha256(trace)
    return {
        "scenario_id": scenario_id,
        "passed": True,
        "findings": [],
        "metrics": {"count": 1, "maximum_error": 0.0},
        "invariants": {"safe_state_reached": True},
        "primary_trace": trace,
        "trace_verifier": {"verifier_id": "test", "verifier_version": "1", "primary_trace_digest": digest, "facts": {"safe_state_reached": True}},
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.raw = self.root / "raw"
        self.audit = AuditLog(self.root / "audit.jsonl")

    def package(self, results):
        return package_release_evidence(
            results,
            artifact_identity={"version": 1, "files": [{"path": "files/gridgpu.py", "size": 1, "sha256": "a" * 64}]},
            configuration_identity={"control_interval": 5},
            policy_version="policy:v1",
            input_identity={"fixture": "canonical"},
            raw_output_directory=self.raw,
            audit_log=self.audit,
        )

    def test_packages_canonical_raw_data_and_audited_gate_evidence(self):
        packaged = self.package([result()])
        item = packaged[0]
        raw_path = self.root / item["evidence"]["raw_data_reference"]
        self.assertTrue(raw_path.is_file())
        expected = result()
        expected["primary_trace_digest"] = canonical_sha256(expected["primary_trace"])
        expected["trace_verifier"] = dict(expected["trace_verifier"])
        expected["trace_verifier"]["primary_trace_digest"] = expected["primary_trace_digest"]
        self.assertEqual(
            raw_path.read_text(),
            json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
        )
        records = list(self.audit.records())
        self.assertEqual(records[-1]["event_type"], "release.scenario_evidence")
        self.assertEqual(records[-1]["payload"]["scenario_id"], "scenario_one")
        self.assertEqual(item["evidence"]["audit_head_hash"], self.audit.verify().head_hash)
        self.assertEqual(item["evidence"]["audit_record_hash"], records[-1]["record_hash"])
        self.assertTrue(item["evidence"]["artifact_version"].startswith("sha256:"))
        self.assertEqual(item["evidence"]["primary_trace_digest"], canonical_sha256(result()["primary_trace"]))
        self.assertFalse(Path(item["evidence"]["raw_data_reference"]).is_absolute())

        requirement = ScenarioRequirement(
            "scenario_one", "test", ("count", "maximum_error"), ("safe_state_reached",)
        )
        decision = evaluate_gate_b(packaged, requirements=(requirement,))
        self.assertTrue(decision.go, decision.reasons)

    def test_canonical_hash_is_order_independent_and_rejects_nan(self):
        self.assertEqual(canonical_sha256({"a": 1, "b": 2}), canonical_sha256({"b": 2, "a": 1}))
        with self.assertRaises(EvidenceError):
            canonical_sha256({"bad": math.nan})

    def test_generic_object_and_enum_kind_are_supported(self):
        class Kind(str, Enum):
            OBJECT = "object_scenario"

        @dataclass
        class ObjectResult:
            kind: Kind
            passed: bool
            findings: tuple
            metrics: dict
            invariants: dict
            primary_trace: dict
            trace_verifier: dict

        packaged = self.package(
            [ObjectResult(Kind.OBJECT, True, (), {"count": 1}, {"safe_state_reached": True}, {"scenario_id": "object_scenario", "rows": [{"event": 1}]}, {"verifier_id": "test", "verifier_version": "1", "primary_trace_digest": canonical_sha256({"scenario_id": "object_scenario", "rows": [{"event": 1}]}), "facts": {"safe_state_reached": True}})]
        )
        self.assertEqual(packaged[0]["scenario_id"], "object_scenario")

    def test_rejects_path_traversal_and_unsafe_scenario_names(self):
        for unsafe in ("../escape", "/absolute", "two/parts", "..", "", " space"):
            with self.subTest(unsafe=unsafe), self.assertRaises(EvidenceError):
                self.package([result(unsafe)])
        self.assertFalse((self.root / "escape.json").exists())

    def test_refuses_overwrite_without_appending_audit(self):
        self.raw.mkdir()
        target = self.raw / "scenario_one.json"
        target.write_text("original\n")
        with self.assertRaisesRegex(EvidenceError, "overwrite"):
            self.package([result()])
        self.assertEqual(target.read_text(), "original\n")
        self.assertEqual(self.audit.verify().record_count, 0)

    def test_prevalidates_duplicates_and_nan_before_any_write(self):
        with self.assertRaisesRegex(EvidenceError, "duplicate"):
            self.package([result(), result()])
        self.assertFalse(self.raw.exists() and any(self.raw.iterdir()))
        bad = result()
        bad["metrics"]["bad"] = math.nan
        with self.assertRaisesRegex(EvidenceError, "not finite"):
            self.package([bad])
        self.assertEqual(self.audit.verify().record_count, 0)

    def test_rejects_noncanonical_identities_before_raw_write(self):
        with self.assertRaises(EvidenceError):
            package_release_evidence(
                [result()],
                artifact_identity={"files": [{"bad": object()}]},
                configuration_identity={"real": True},
                policy_version="policy:v1",
                input_identity={"real": True},
                raw_output_directory=self.raw,
                audit_log=self.audit,
            )
        self.assertFalse(self.raw.exists() and any(self.raw.iterdir()))

    def test_rejects_malformed_result_fields(self):
        cases = []
        no_metrics = result()
        no_metrics.pop("metrics")
        cases.append(no_metrics)
        bad_pass = result()
        bad_pass["passed"] = 1
        cases.append(bad_pass)
        no_invariants = result()
        no_invariants["invariants"] = {}
        cases.append(no_invariants)
        bad_findings = result()
        bad_findings["findings"] = [""]
        cases.append(bad_findings)
        no_trace = result()
        no_trace["primary_trace"] = {}
        cases.append(no_trace)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(EvidenceError):
                self.package([bad])

    def test_rejects_trace_verifier_digest_that_does_not_bind_full_trace(self):
        bad = result()
        bad["trace_verifier"]["primary_trace_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(EvidenceError, "digest does not match"):
            self.package([bad])


if __name__ == "__main__":
    unittest.main()
