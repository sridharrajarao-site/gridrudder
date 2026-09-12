"""Tamper-evident, append-only JSONL audit records.

The chain detects modification, deletion (other than undetectable tail deletion),
insertion, and reordering of records.  It does not replace durable storage,
access controls, or an externally anchored chain head.  Persist or sign the
latest hash outside this file when detection of tail truncation is required.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterator, Mapping, Optional, Union

try:  # POSIX deployment target; the in-process lock remains as a fallback.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX systems
    fcntl = None  # type: ignore[assignment]


AUDIT_VERSION = 1
GENESIS_HASH = "0" * 64


class AuditError(Exception):
    """Base class for audit log errors."""


class AuditIntegrityError(AuditError):
    """Raised when an existing audit log fails integrity verification."""


class AuditEncodingError(AuditError):
    """Raised when a proposed record cannot be represented safely as JSON."""


@dataclass(frozen=True)
class VerificationResult:
    """Successful verification summary."""

    record_count: int
    head_hash: str


_process_lock = threading.RLock()


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
        raise AuditEncodingError(f"audit value is not canonical JSON: {exc}") from exc


def _record_hash(unsigned_record: Mapping[str, Any]) -> str:
    encoded = _canonical_json(unsigned_record).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


@contextmanager
def _locked_file(path: Path) -> Iterator[Any]:
    """Open a log for reading/appending while excluding cooperating writers."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with _process_lock:
        with path.open("a+", encoding="utf-8", newline="\n") as stream:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield stream
            finally:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _verify_stream(stream: Any) -> VerificationResult:
    stream.seek(0)
    expected_previous = GENESIS_HASH
    count = 0

    for line_number, raw_line in enumerate(stream, start=1):
        if not raw_line.endswith("\n"):
            raise AuditIntegrityError(
                f"line {line_number}: incomplete record (missing newline)"
            )
        if not raw_line.strip():
            raise AuditIntegrityError(f"line {line_number}: blank record")
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError(
                f"line {line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise AuditIntegrityError(f"line {line_number}: record is not an object")

        required = {
            "version",
            "sequence",
            "timestamp",
            "event_type",
            "actor",
            "payload",
            "previous_hash",
            "record_hash",
        }
        if set(record) != required:
            missing = sorted(required - set(record))
            extra = sorted(set(record) - required)
            raise AuditIntegrityError(
                f"line {line_number}: invalid fields; missing={missing}, extra={extra}"
            )
        if record["version"] != AUDIT_VERSION:
            raise AuditIntegrityError(f"line {line_number}: unsupported version")
        if record["sequence"] != count + 1:
            raise AuditIntegrityError(f"line {line_number}: invalid sequence")
        if not isinstance(record["timestamp"], str) or not record["timestamp"]:
            raise AuditIntegrityError(f"line {line_number}: invalid timestamp")
        if not isinstance(record["event_type"], str) or not record["event_type"]:
            raise AuditIntegrityError(f"line {line_number}: invalid event_type")
        if not isinstance(record["actor"], str) or not record["actor"]:
            raise AuditIntegrityError(f"line {line_number}: invalid actor")
        if not isinstance(record["payload"], dict):
            raise AuditIntegrityError(f"line {line_number}: payload is not an object")
        if record["previous_hash"] != expected_previous:
            raise AuditIntegrityError(f"line {line_number}: previous hash mismatch")

        claimed_hash = record["record_hash"]
        if not isinstance(claimed_hash, str):
            raise AuditIntegrityError(f"line {line_number}: invalid record hash")
        unsigned = {key: value for key, value in record.items() if key != "record_hash"}
        calculated_hash = _record_hash(unsigned)
        if claimed_hash != calculated_hash:
            raise AuditIntegrityError(f"line {line_number}: record hash mismatch")

        expected_previous = claimed_hash
        count += 1

    return VerificationResult(record_count=count, head_hash=expected_previous)


def verify_audit_log(path: Union[str, os.PathLike]) -> VerificationResult:
    """Verify the entire log, raising ``AuditIntegrityError`` on corruption."""

    audit_path = Path(path)
    if not audit_path.exists():
        return VerificationResult(record_count=0, head_hash=GENESIS_HASH)
    with _locked_file(audit_path) as stream:
        return _verify_stream(stream)


class AuditLog:
    """Append and verify records in one hash-chained JSONL file."""

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self.path = Path(path)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        actor: str,
        timestamp: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append one durable record after verifying the existing chain.

        ``timestamp`` is injectable for deterministic tests and data import.  It
        must be an explicit non-empty string; semantic clock validation belongs
        at the event-ingress boundary.
        """

        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor must be a non-empty string")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        if timestamp is not None and (not isinstance(timestamp, str) or not timestamp):
            raise ValueError("timestamp must be a non-empty string")

        # Canonical round-trip both validates and snapshots mutable input.
        payload_copy = json.loads(_canonical_json(dict(payload)))

        with _locked_file(self.path) as stream:
            current = _verify_stream(stream)
            unsigned: dict[str, Any] = {
                "version": AUDIT_VERSION,
                "sequence": current.record_count + 1,
                "timestamp": timestamp or _utc_timestamp(),
                "event_type": event_type,
                "actor": actor,
                "payload": payload_copy,
                "previous_hash": current.head_hash,
            }
            record = {**unsigned, "record_hash": _record_hash(unsigned)}
            stream.seek(0, os.SEEK_END)
            stream.write(_canonical_json(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return record

    def verify(self) -> VerificationResult:
        return verify_audit_log(self.path)

    def records(self) -> Iterator[dict[str, Any]]:
        """Yield verified records as independent dictionaries."""

        if not self.path.exists():
            return
        with _locked_file(self.path) as stream:
            _verify_stream(stream)
            stream.seek(0)
            snapshot = [json.loads(line) for line in stream]
        yield from snapshot
