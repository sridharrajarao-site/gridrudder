"""End-to-end Gate B release packet production and offline verification."""

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional, Tuple, Union

from .audit import AuditLog
from .benchmarks import canonical_scenarios
from .controller import HeuristicController
from .evidence import canonical_sha256, package_release_evidence
from .fault_benchmarks import canonical_fault_scenarios
from .gates import GateDecision, REQUIRED_SCENARIOS, evaluate_gate_b
from .integrated_faults import run_all_primary_traces
from .manifest import build_artifact_manifest, canonical_json, file_sha256, verify_manifest_files, write_new_manifest
from .standard_traces import run_all_standard_primary_traces
from .trace_verifier import verify_primary_trace


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseRun:
    release_directory: Path
    manifest_path: Path
    decision_path: Path
    packaged_results: Tuple[Mapping[str, Any], ...]
    gate_decision: GateDecision


@dataclass(frozen=True)
class PacketVerification:
    valid: bool
    reasons: Tuple[str, ...]
    gate_decision: Optional[GateDecision]


def _prepare_empty_release_directory(requested: Optional[Union[str, os.PathLike]]) -> Path:
    if requested is None:
        return Path(tempfile.mkdtemp(prefix="gridgpu-gate-b-"))
    root = Path(requested)
    if root.is_symlink():
        raise ReleaseError("release directory must not be a symbolic link")
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError("cannot prepare release directory: {}".format(exc)) from exc
    if not resolved.is_dir() or tuple(resolved.iterdir()):
        raise ReleaseError("release directory must be an empty directory")
    return resolved


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except OSError as exc:
        raise ReleaseError("cannot create release file without overwrite: {}".format(exc)) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(dict(document)) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _trace_mapping(trace: Any) -> Mapping[str, Any]:
    if hasattr(trace, "as_mapping") and callable(trace.as_mapping):
        return trace.as_mapping()
    if is_dataclass(trace):
        return asdict(trace)
    if isinstance(trace, Mapping):
        return dict(trace)
    raise ReleaseError("primary trace producer returned an unsupported value")


def _verified_producer_result(trace: Any) -> Mapping[str, Any]:
    packet = _trace_mapping(trace)
    verification = verify_primary_trace(packet)
    passed = all(verification.facts.values())
    return {
        "scenario_id": verification.scenario_id,
        "passed": passed,
        "findings": [] if passed else ["independent primary-trace verification found a false invariant"],
        "metrics": dict(verification.metrics),
        "invariants": dict(verification.facts),
        "primary_trace": packet,
        "trace_verifier": verification.as_mapping(),
    }


def run_gate_b_release(
    release_directory: Optional[Union[str, os.PathLike]] = None,
    *,
    project_root: Optional[Union[str, os.PathLike]] = None,
    policy_version: str = "gridgpu-policy:v1",
    artifact_identity: Any = None,
    configuration_identity: Any = None,
    input_identity: Any = None,
) -> ReleaseRun:
    """Produce a self-contained, non-overwritable, offline-verifiable packet."""

    if any(value is not None for value in (artifact_identity, configuration_identity, input_identity)):
        raise ReleaseError("official releases reject caller-supplied placeholder identities")
    root = _prepare_empty_release_directory(release_directory)
    project = Path(project_root).resolve(strict=True) if project_root else Path(__file__).resolve().parent.parent
    standard_definitions = canonical_scenarios()
    fault_definitions = canonical_fault_scenarios()
    standard_traces = run_all_standard_primary_traces()
    integrated_fault_traces = tuple(item for item in run_all_primary_traces() if item.scenario_id != "normal")
    producer_results = tuple(
        _verified_producer_result(item) for item in standard_traces + integrated_fault_traces
    )

    expected_ids = tuple(requirement.scenario_id for requirement in REQUIRED_SCENARIOS)
    actual_ids = tuple(result["scenario_id"] for result in producer_results)
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != set(expected_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ReleaseError("benchmark coverage does not exactly match Gate B requirements")

    scenario_definitions = [{"family": "standard", "definition": item} for item in standard_definitions] + [
        {"family": "fault", "scenario_id": item.kind.value, "expected_safe_state": item.expected_safe_state.value, "required_evidence": list(item.required_evidence)}
        for item in fault_definitions
    ]
    controller = HeuristicController(reserve_watts=100.0, recovery_step_watts=25.0)
    gate_requirements_manifest = [
        {
            "scenario_id": requirement.scenario_id,
            "description": requirement.description,
            "required_metrics": list(requirement.required_metrics),
            "required_invariants": list(requirement.required_invariants),
            "metric_predicates": [
                {"rule_id": predicate.rule_id, "description": predicate.description}
                for predicate in requirement.metric_predicates
            ],
        }
        for requirement in REQUIRED_SCENARIOS
    ]
    configuration = {
        "scenario_definitions": scenario_definitions,
        "controller_parameters": {"type": type(controller).__name__, "reserve_watts": controller.reserve_watts, "recovery_step_watts": controller.recovery_step_watts},
        "gate_requirements": gate_requirements_manifest,
        "test_command": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
    }
    manifest = build_artifact_manifest(
        project, root,
        scenario_definitions=scenario_definitions,
        controller_parameters=configuration["controller_parameters"],
        gate_requirements=gate_requirements_manifest,
        test_command=configuration["test_command"],
    )
    manifest_path = write_new_manifest(root, manifest)
    manifest_digest = "sha256:" + file_sha256(manifest_path)
    audit = AuditLog(root / "release-audit.jsonl")
    audit.append("release.manifest", {"manifest_reference": "manifest.json", "manifest_digest": manifest_digest}, actor="release:gate-b")

    packaged = package_release_evidence(
        producer_results,
        artifact_identity=manifest,
        configuration_identity={
            "scenario_definitions": manifest["scenario_definitions"],
            "controller_parameters": manifest["controller_parameters"],
            "gate_requirements": manifest["gate_requirements"],
            "test_command": manifest["test_command"],
            "runtime": manifest["runtime"],
        },
        policy_version=policy_version,
        input_identity={"scenario_ids": list(expected_ids)},
        raw_output_directory=root / "raw",
        audit_log=audit,
        audit_actor="release:gate-b",
    )
    decision = evaluate_gate_b(packaged)
    decision_base = {
        "packet_version": 1, "gate": "B", "go": decision.go,
        "reasons": list(decision.reasons),
        "required_scenario_count": decision.required_scenario_count,
        "received_scenario_count": decision.received_scenario_count,
        "missing_scenario_ids": list(decision.missing_scenario_ids),
        "scenario_ids": sorted(result["scenario_id"] for result in packaged),
        "manifest_reference": "manifest.json", "manifest_digest": manifest_digest,
        "raw_evidence": {result["scenario_id"]: result["evidence"]["raw_data_reference"] for result in sorted(packaged, key=lambda item: item["scenario_id"])},
    }
    decision_digest = canonical_sha256(decision_base)
    decision_audit = audit.append("release.gate_decision", {"decision_reference": "gate-b-decision.json", "decision_digest": decision_digest, "go": decision.go}, actor="release:gate-b")
    verification = audit.verify()
    document = dict(decision_base)
    document.update({"audit_record_count": verification.record_count, "audit_head_hash": verification.head_hash, "decision_audit_record_hash": decision_audit["record_hash"], "decision_content_digest": decision_digest})
    decision_path = root / "gate-b-decision.json"
    _write_new_json(decision_path, document)
    return ReleaseRun(root, manifest_path, decision_path, packaged, decision)


def verify_release_packet(release_directory: Union[str, os.PathLike]) -> PacketVerification:
    """Verify a packet without network or source-tree access."""

    reasons = []
    gate_decision = None
    try:
        root = Path(release_directory).resolve(strict=True)
        manifest_path, decision_path = root / "manifest.json", root / "gate-b-decision.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if manifest_path.read_text(encoding="utf-8") != canonical_json(manifest) + "\n":
            reasons.append("manifest encoding mismatch")
        if decision_path.read_text(encoding="utf-8") != canonical_json(decision) + "\n":
            reasons.append("decision encoding mismatch")
        reasons.extend(verify_manifest_files(root, manifest))
        manifest_digest = "sha256:" + file_sha256(manifest_path)
        if decision.get("manifest_digest") != manifest_digest:
            reasons.append("manifest digest mismatch")
        audit = AuditLog(root / "release-audit.jsonl")
        audit_verification = audit.verify()
        records = tuple(audit.records())
        if decision.get("audit_head_hash") != audit_verification.head_hash:
            reasons.append("audit head mismatch")
        if decision.get("audit_record_count") != audit_verification.record_count:
            reasons.append("audit record count mismatch")
        manifest_records = [row for row in records if row["event_type"] == "release.manifest"]
        if len(manifest_records) != 1 or manifest_records[0]["payload"].get("manifest_digest") != manifest_digest:
            reasons.append("manifest audit record mismatch")
        scenario_records = {row["payload"]["scenario_id"]: row for row in records if row["event_type"] == "release.scenario_evidence"}
        packaged = []
        for scenario_id, reference in decision.get("raw_evidence", {}).items():
            target = (root / Path(reference)).resolve(strict=True)
            target.relative_to(root)
            raw_text = target.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            record = scenario_records.get(scenario_id)
            if record is None:
                reasons.append("missing scenario audit record: {}".format(scenario_id))
                continue
            raw_digest = "sha256:" + hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()
            if raw_text != canonical_json(raw) + "\n":
                reasons.append("raw evidence encoding mismatch: {}".format(scenario_id))
            if record["payload"].get("raw_digest") != raw_digest:
                reasons.append("raw evidence digest mismatch: {}".format(scenario_id))
            trace_digest = canonical_sha256(raw.get("primary_trace"))
            if raw.get("primary_trace_digest") != trace_digest or record["payload"].get("primary_trace_digest") != trace_digest:
                reasons.append("primary trace digest mismatch: {}".format(scenario_id))
            independent = verify_primary_trace(raw.get("primary_trace"), scenario_id)
            if raw.get("trace_verifier") != independent.as_mapping():
                reasons.append("stored trace verifier result mismatch: {}".format(scenario_id))
            if raw.get("metrics") != dict(independent.metrics) or raw.get("invariants") != dict(independent.facts):
                reasons.append("derived trace facts mismatch: {}".format(scenario_id))
            payload = record["payload"]
            independently_passed = all(independent.facts.values())
            packaged.append({"scenario_id": scenario_id, "passed": independently_passed, "findings": [] if independently_passed else ["independent primary-trace verification found a false invariant"], "metrics": dict(independent.metrics), "evidence": {
                "artifact_version": payload["artifact_digest"], "configuration_digest": payload["configuration_digest"], "policy_version": payload["policy_version"], "input_digest": payload["input_digest"], "audit_head_hash": record["record_hash"], "raw_data_reference": reference, "primary_trace_digest": independent.primary_trace_digest, "trace_verifier": independent.as_mapping(), "invariants": dict(independent.facts)}})
        gate_decision = evaluate_gate_b(packaged)
        if gate_decision.go != decision.get("go") or list(gate_decision.reasons) != decision.get("reasons"):
            reasons.append("stored decision does not match offline gate evaluation")
        decision_records = [row for row in records if row["event_type"] == "release.gate_decision"]
        excluded = {"audit_record_count", "audit_head_hash", "decision_audit_record_hash", "decision_content_digest"}
        decision_base = {key: value for key, value in decision.items() if key not in excluded}
        digest = canonical_sha256(decision_base)
        if decision.get("decision_content_digest") != digest:
            reasons.append("decision content digest mismatch")
        if len(decision_records) != 1 or decision_records[0]["payload"].get("decision_digest") != digest:
            reasons.append("decision audit record mismatch")
        elif decision.get("decision_audit_record_hash") != decision_records[0]["record_hash"]:
            reasons.append("decision audit hash mismatch")
    except Exception as exc:
        reasons.append("packet verification failed: {}".format(exc))
    return PacketVerification(not reasons, tuple(reasons), gate_decision)
