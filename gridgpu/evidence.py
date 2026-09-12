"""Release-evidence packaging for producer-neutral scenario results."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

from .audit import AuditLog


_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EvidenceError(RuntimeError):
    """Raised when release evidence cannot be packaged safely."""


@dataclass(frozen=True)
class _NormalizedResult:
    scenario_id: str
    passed: bool
    findings: Tuple[str, ...]
    metrics: Mapping[str, float]
    invariants: Mapping[str, bool]
    primary_trace: Any
    trace_verifier: Mapping[str, Any]


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceError("value is not canonical JSON: {}".format(exc)) from exc


def canonical_sha256(value: Any) -> str:
    """Return a prefixed SHA-256 digest of canonical JSON data."""

    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _field(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(name)
    return getattr(result, name, None)


def _normalize_scenario_id(result: Any) -> str:
    value = _field(result, "scenario_id")
    if value is None:
        value = _field(result, "kind")
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str) or not _SCENARIO_ID.fullmatch(value):
        raise EvidenceError("scenario ID is missing, unsafe, or invalid")
    return value


def _normalize_result(result: Any) -> _NormalizedResult:
    scenario_id = _normalize_scenario_id(result)
    passed = _field(result, "passed")
    if not isinstance(passed, bool):
        raise EvidenceError("{}: passed must be boolean".format(scenario_id))

    findings_value = _field(result, "findings")
    if not isinstance(findings_value, (list, tuple)):
        raise EvidenceError("{}: findings must be a list or tuple".format(scenario_id))
    findings = []
    for finding in findings_value:
        if not isinstance(finding, str) or not finding.strip():
            raise EvidenceError("{}: finding is empty or invalid".format(scenario_id))
        findings.append(finding)

    metrics_value = _field(result, "metrics")
    if not isinstance(metrics_value, Mapping):
        raise EvidenceError("{}: metrics must be a mapping".format(scenario_id))
    metrics = {}
    for name, value in metrics_value.items():
        if not isinstance(name, str) or not name.strip():
            raise EvidenceError("{}: metric name is invalid".format(scenario_id))
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise EvidenceError("{}: metric {} is not finite numeric data".format(scenario_id, name))
        metrics[name] = value

    invariants_value = _field(result, "invariants")
    if not isinstance(invariants_value, Mapping) or not invariants_value:
        raise EvidenceError("{}: invariants must be a non-empty mapping".format(scenario_id))
    invariants = {}
    for name, value in invariants_value.items():
        if not isinstance(name, str) or not name.strip():
            raise EvidenceError("{}: invariant name is invalid".format(scenario_id))
        if not isinstance(value, bool):
            raise EvidenceError("{}: invariant {} must be boolean".format(scenario_id, name))
        invariants[name] = value

    # Round-trip snapshots inputs and proves no non-JSON keys/values slipped in.
    metrics = json.loads(_canonical_json(metrics))
    invariants = json.loads(_canonical_json(invariants))
    trace_value = _field(result, "primary_trace")
    if not isinstance(trace_value, Mapping) or not trace_value:
        raise EvidenceError("{}: primary_trace must be a non-empty full trace mapping".format(scenario_id))
    trace = json.loads(_canonical_json(dict(trace_value)))
    verifier_value = _field(result, "trace_verifier")
    if not isinstance(verifier_value, Mapping):
        raise EvidenceError("{}: trace_verifier must be a mapping".format(scenario_id))
    if not isinstance(verifier_value.get("verifier_id"), str) or not verifier_value["verifier_id"].strip():
        raise EvidenceError("{}: trace verifier identity is required".format(scenario_id))
    if not isinstance(verifier_value.get("verifier_version"), str) or not verifier_value["verifier_version"].strip():
        raise EvidenceError("{}: trace verifier version is required".format(scenario_id))
    if not isinstance(verifier_value.get("facts"), Mapping):
        raise EvidenceError("{}: trace verifier facts are required".format(scenario_id))
    verifier = json.loads(_canonical_json(dict(verifier_value)))
    return _NormalizedResult(scenario_id, passed, tuple(findings), metrics, invariants, trace, verifier)


def _validated_output_path(directory: Union[str, os.PathLike], scenario_id: str) -> Path:
    root = Path(directory)
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("cannot prepare raw output directory: {}".format(exc)) from exc
    if not resolved_root.is_dir():
        raise EvidenceError("raw output location is not a directory")
    target = resolved_root / "{}.json".format(scenario_id)
    if target.parent != resolved_root:
        raise EvidenceError("raw output path escapes the configured directory")
    return target


def _write_new_durable(path: Path, encoded: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise EvidenceError("refusing to overwrite retained raw evidence: {}".format(path)) from exc
    except OSError as exc:
        raise EvidenceError("cannot create retained raw evidence: {}".format(exc)) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def package_release_evidence(
    results: Iterable[Any],
    *,
    artifact_identity: Any,
    configuration_identity: Any,
    policy_version: str,
    input_identity: Any,
    raw_output_directory: Union[str, os.PathLike],
    audit_log: AuditLog,
    audit_actor: str = "release:evidence",
) -> Tuple[Mapping[str, Any], ...]:
    """Package scenario results into mappings consumable by Gate B.

    All results are normalized and checked for duplicate IDs before any file or
    audit mutation.  Individual raw files then become immutable by name.
    """

    if not isinstance(policy_version, str) or not policy_version.strip():
        raise EvidenceError("policy_version must be a non-empty string")
    if not isinstance(audit_actor, str) or not audit_actor.strip():
        raise EvidenceError("audit_actor must be a non-empty string")
    if not isinstance(audit_log, AuditLog):
        raise EvidenceError("audit_log must be an AuditLog")
    if not isinstance(artifact_identity, Mapping) or not isinstance(artifact_identity.get("files"), list) or not artifact_identity["files"]:
        raise EvidenceError("artifact_identity must be a real non-empty file manifest")
    if not isinstance(configuration_identity, Mapping) or not configuration_identity:
        raise EvidenceError("configuration_identity must be non-placeholder configuration")
    if not isinstance(input_identity, Mapping) or not input_identity:
        raise EvidenceError("input_identity must be non-placeholder input identity")
    try:
        supplied = list(results)
    except (TypeError, RuntimeError) as exc:
        raise EvidenceError("results are not a readable iterable: {}".format(exc)) from exc
    if not supplied:
        raise EvidenceError("at least one scenario result is required")

    normalized = tuple(_normalize_result(result) for result in supplied)
    identifiers = [result.scenario_id for result in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise EvidenceError("duplicate scenario results are not allowed")

    # Hash before writing anything so non-canonical identities fail atomically.
    artifact_digest = canonical_sha256(artifact_identity)
    configuration_digest = canonical_sha256(configuration_identity)
    input_digest = canonical_sha256(input_identity)

    targets = [
        _validated_output_path(raw_output_directory, result.scenario_id)
        for result in normalized
    ]
    existing = [str(target) for target in targets if target.exists()]
    if existing:
        raise EvidenceError(
            "refusing to overwrite retained raw evidence: {}".format(", ".join(existing))
        )

    packaged = []
    packet_root = audit_log.path.parent.resolve()
    for result, target in zip(normalized, targets):
        try:
            raw_reference = target.resolve().relative_to(packet_root).as_posix()
        except ValueError as exc:
            raise EvidenceError("raw evidence must be inside the release packet") from exc
        trace_digest = canonical_sha256(result.primary_trace)
        trace_verifier = dict(result.trace_verifier)
        supplied_trace_digest = trace_verifier.get("primary_trace_digest")
        if supplied_trace_digest != trace_digest:
            raise EvidenceError("{}: trace verifier digest does not match full primary trace".format(result.scenario_id))
        raw_record = {
            "scenario_id": result.scenario_id,
            "passed": result.passed,
            "findings": list(result.findings),
            "metrics": dict(result.metrics),
            "invariants": dict(result.invariants),
            "primary_trace": result.primary_trace,
            "primary_trace_digest": trace_digest,
            "trace_verifier": trace_verifier,
        }
        encoded = _canonical_json(raw_record)
        raw_digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        _write_new_durable(target, encoded)

        try:
            audit_record = audit_log.append(
                "release.scenario_evidence",
                {
                    "scenario_id": result.scenario_id,
                    "passed": result.passed,
                    "artifact_digest": artifact_digest,
                    "configuration_digest": configuration_digest,
                    "policy_version": policy_version,
                    "input_digest": input_digest,
                    "raw_digest": raw_digest,
                    "raw_data_reference": raw_reference,
                    "primary_trace_digest": trace_digest,
                    "trace_verifier": trace_verifier,
                    "invariants": dict(result.invariants),
                },
                actor=audit_actor,
            )
        except Exception:
            # The newly created file has not been referenced by an audit record.
            try:
                target.unlink()
            except OSError:
                pass
            raise

        verification = audit_log.verify()
        if verification.head_hash != audit_record["record_hash"]:
            raise EvidenceError(
                "audit head advanced unexpectedly while packaging {}".format(result.scenario_id)
            )

        packaged.append(
            {
                "scenario_id": result.scenario_id,
                "passed": result.passed,
                "findings": list(result.findings),
                "metrics": dict(result.metrics),
                "evidence": {
                    "artifact_version": artifact_digest,
                    "configuration_digest": configuration_digest,
                    "policy_version": policy_version,
                    "input_digest": input_digest,
                    "audit_head_hash": verification.head_hash,
                    "audit_record_hash": audit_record["record_hash"],
                    "raw_data_reference": raw_reference,
                    "raw_data_digest": raw_digest,
                    "primary_trace_digest": trace_digest,
                    "trace_verifier": trace_verifier,
                    "invariants": dict(result.invariants),
                },
            }
        )
    return tuple(packaged)
