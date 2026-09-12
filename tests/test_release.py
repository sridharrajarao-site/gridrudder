import json
from pathlib import Path
import tempfile
import unittest

from gridgpu.gates import REQUIRED_SCENARIOS, evaluate_gate_b
from gridgpu.release import ReleaseError, run_gate_b_release, verify_release_packet
from gridgpu.trace_verifier import verify_primary_trace


class GateBReleaseRunnerTests(unittest.TestCase):
    def test_runs_and_packages_all_scenarios_then_records_honest_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            release_root = Path(directory) / "release"
            release = run_gate_b_release(release_root)
            document = json.loads(release.decision_path.read_text(encoding="utf-8"))
            reevaluated = evaluate_gate_b(release.packaged_results)

            self.assertEqual(release.gate_decision, reevaluated)
            self.assertEqual(document["go"], reevaluated.go)
            self.assertEqual(document["reasons"], list(reevaluated.reasons))
            self.assertEqual(document["required_scenario_count"], len(REQUIRED_SCENARIOS))
            self.assertEqual(document["received_scenario_count"], len(REQUIRED_SCENARIOS))
            self.assertEqual(document["audit_record_count"], len(REQUIRED_SCENARIOS) + 2)
            self.assertEqual(len(document["raw_evidence"]), len(REQUIRED_SCENARIOS))
            self.assertTrue(all((release.release_directory / path).is_file() for path in document["raw_evidence"].values()))
            self.assertTrue(release.manifest_path.is_file())
            self.assertTrue(verify_release_packet(release.release_directory).valid)

    def test_scenario_coverage_is_exact_and_deterministically_ordered_in_decision(self):
        expected = sorted(requirement.scenario_id for requirement in REQUIRED_SCENARIOS)
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first = run_gate_b_release(Path(first_directory) / "release")
            second = run_gate_b_release(Path(second_directory) / "release")
            first_document = json.loads(first.decision_path.read_text(encoding="utf-8"))
            second_document = json.loads(second.decision_path.read_text(encoding="utf-8"))
        self.assertEqual(first_document["scenario_ids"], expected)
        self.assertEqual(second_document["scenario_ids"], expected)
        self.assertEqual(
            [item["scenario_id"] for item in first.packaged_results],
            [item["scenario_id"] for item in second.packaged_results],
        )

    def test_common_provenance_and_invariants_are_packaged_for_every_result(self):
        with tempfile.TemporaryDirectory() as directory:
            release = run_gate_b_release(Path(directory) / "release")
            for result in release.packaged_results:
                with self.subTest(scenario_id=result["scenario_id"]):
                    evidence = result["evidence"]
                    for field in (
                        "artifact_version",
                        "configuration_digest",
                        "policy_version",
                        "input_digest",
                        "audit_head_hash",
                        "raw_data_reference",
                    ):
                        self.assertTrue(evidence[field])
                    self.assertTrue(evidence["invariants"])
                    self.assertTrue(evidence["primary_trace_digest"])
                    self.assertFalse(Path(evidence["raw_data_reference"]).is_absolute())

    def test_official_raw_packets_are_full_real_traces_and_facts_come_from_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            release = run_gate_b_release(Path(directory) / "release")
            by_id = {item["scenario_id"]: item for item in release.packaged_results}
            for scenario_id, item in by_id.items():
                with self.subTest(scenario_id=scenario_id):
                    raw_path = release.release_directory / item["evidence"]["raw_data_reference"]
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    trace = raw["primary_trace"]
                    if scenario_id in {"normal_constraint", "infeasible_constraint", "rebound_recovery", "stale_meter"}:
                        self.assertIn("trace_rows", trace)
                        self.assertIn("raw_facts", trace)
                    else:
                        self.assertIn("injection_ledger", trace)
                        self.assertIn("mutation_ledger", trace)
                    verified = verify_primary_trace(trace, scenario_id)
                    self.assertEqual(raw["metrics"], dict(verified.metrics))
                    self.assertEqual(raw["invariants"], dict(verified.facts))
                    self.assertEqual(raw["trace_verifier"], verified.as_mapping())

    def test_existing_or_nonempty_release_directory_fails_before_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            sentinel = root / "gate-b-decision.json"
            sentinel.write_text("retain-me", encoding="utf-8")
            with self.assertRaises(ReleaseError):
                run_gate_b_release(root)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "retain-me")
            self.assertEqual(tuple(root.iterdir()), (sentinel,))

    def test_symlink_release_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ReleaseError):
                run_gate_b_release(link)
            self.assertEqual(tuple(real.iterdir()), ())

    def test_no_directory_allocates_a_new_persistent_temporary_release(self):
        release = run_gate_b_release()
        try:
            self.assertTrue(release.release_directory.is_dir())
            self.assertTrue(release.decision_path.is_file())
        finally:
            # The API intentionally returns a persistent location; tests own cleanup.
            import shutil
            shutil.rmtree(release.release_directory)

    def test_offline_verifier_detects_tampered_artifact_raw_and_decision(self):
        targets = ("artifact", "raw", "decision")
        for target_kind in targets:
            with self.subTest(target_kind=target_kind), tempfile.TemporaryDirectory() as directory:
                release = run_gate_b_release(Path(directory) / "release")
                document = json.loads(release.decision_path.read_text(encoding="utf-8"))
                if target_kind == "artifact":
                    manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
                    target = release.release_directory / manifest["files"][0]["path"]
                    target.write_bytes(target.read_bytes() + b"tamper")
                elif target_kind == "raw":
                    target = release.release_directory / next(iter(document["raw_evidence"].values()))
                    target.write_bytes(target.read_bytes() + b" ")
                else:
                    document["go"] = not document["go"]
                    release.decision_path.write_text(json.dumps(document), encoding="utf-8")
                self.assertFalse(verify_release_packet(release.release_directory).valid)

    def test_placeholder_identity_overrides_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReleaseError):
                run_gate_b_release(Path(directory) / "release", artifact_identity={"component": "gridgpu"})


if __name__ == "__main__":
    unittest.main()
