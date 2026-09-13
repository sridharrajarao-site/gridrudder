"""Private durable JSON evidence; hashes detect corruption, not authenticity."""
from dataclasses import asdict, is_dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat


class ArchiveError(ValueError):
    pass


def _json(value):
    if is_dataclass(value):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ArchiveError("aware evidence timestamps required")
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ArchiveError("string evidence keys required")
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write_trial_archive(path: Path, *, evidence_kind: str, config, outcome,
                        measurements, command_evidence, recovery_state,
                        runtime: dict, qualification: dict) -> str:
    """Write once into an existing private directory; never publish raw evidence.

    ``physical_unqualified`` deliberately makes no metrology/savings assertion.
    Qualification data is retained for review, not promoted to a passed gate.
    Failed trials can supply an error outcome and all partial observations.
    """
    if evidence_kind not in {"simulated", "physical_unqualified"}:
        raise ArchiveError("explicit simulated or physical_unqualified kind required")
    path = Path(path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ArchiveError("absolute archive path required")
    if path.parent.resolve() != path.parent:
        raise ArchiveError("symlink or noncanonical archive parent rejected")
    parent = path.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ArchiveError("existing owner-only archive directory required")
    if not runtime or not qualification:
        raise ArchiveError("runtime and qualification context required")
    payload = _json(dict(schema="gridrudder-trial-evidence:v1", evidence_kind=evidence_kind,
        config=config, outcome=outcome, measurements=measurements,
        command_evidence=command_evidence, recovery_state=recovery_state,
        runtime=runtime, qualification=qualification))
    digest = hashlib.sha256(_encode(payload)).hexdigest()
    encoded = _encode(dict(payload=payload, sha256=digest)) + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return digest


def verify_trial_archive(path: Path) -> dict:
    data = Path(path).read_bytes()
    if not data.endswith(b"\n"):
        raise ArchiveError("incomplete archive")
    try:
        document = json.loads(data)
        if set(document) != {"payload", "sha256"}:
            raise ArchiveError("unexpected archive fields")
        payload = document["payload"]
        if hashlib.sha256(_encode(payload)).hexdigest() != document["sha256"]:
            raise ArchiveError("archive digest mismatch")
        if (payload["schema"] != "gridrudder-trial-evidence:v1" or
                payload["evidence_kind"] not in {"simulated", "physical_unqualified"}):
            raise ArchiveError("unsupported evidence schema/kind")
        return payload
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ArchiveError("invalid archive") from exc
