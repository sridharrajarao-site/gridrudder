"""Durable experiment intent and manual recovery planning; never restores hardware."""
from dataclasses import asdict, dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Callable, Optional


class RecoveryError(RuntimeError):
    pass


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise RecoveryError("timezone-aware timestamp required") from exc


def _watts(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class RecoveryIntent:
    trial_id: str
    host_id: str
    gpu_uuid: str
    authorization_sha256: str
    original_watts: float
    target_watts: float
    created_at_utc: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (self.trial_id, self.host_id, self.gpu_uuid)):
            raise RecoveryError("exact trial, host and GPU identities required")
        if (not isinstance(self.authorization_sha256, str) or len(self.authorization_sha256) != 64 or
                any(c not in "0123456789abcdef" for c in self.authorization_sha256)):
            raise RecoveryError("authorization binding must be SHA-256")
        if not _watts(self.original_watts) or not _watts(self.target_watts) or self.target_watts >= self.original_watts:
            raise RecoveryError("intent must lower a finite positive original limit")
        _time(self.created_at_utc)


@dataclass(frozen=True)
class RecoveryObservation:
    host_id: str
    gpu_uuid: str
    power_limit_watts: float
    observed_at_utc: str
    source_id: str


@dataclass(frozen=True)
class RecoveryState:
    intent: RecoveryIntent
    restored_observation: Optional[RecoveryObservation] = None


def _validate_observation(intent, observation):
    if (observation.host_id != intent.host_id or observation.gpu_uuid != intent.gpu_uuid or
            not isinstance(observation.source_id, str) or not observation.source_id.strip() or
            not _watts(observation.power_limit_watts) or
            _time(observation.observed_at_utc) < _time(intent.created_at_utc)):
        raise RecoveryError("observation does not bind a valid post-intent device reading")


def plan_recovery(state: RecoveryState, observation: Optional[RecoveryObservation] = None) -> str:
    """Return an operator next step. No observation means no inferred safe state."""
    if state.restored_observation is not None:
        _validate_observation(state.intent, state.restored_observation)
        if state.restored_observation.power_limit_watts != state.intent.original_watts:
            raise RecoveryError("closed journal does not prove original limit")
        return "closed_historical_record"
    if observation is None:
        return "unfinished_observe_device"
    _validate_observation(state.intent, observation)
    if observation.power_limit_watts == state.intent.original_watts:
        return "unfinished_record_verified_restoration"
    return "unfinished_attended_restoration_required"


def _encode(payload, previous):
    body = dict(payload=payload, previous_sha256=previous)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    body["sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    return (json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _decode(data):
    try:
        if not data.endswith(b"\n"):
            raise ValueError("torn final record")
        rows = data.splitlines()
        if len(rows) not in (1, 2):
            raise ValueError("invalid record count")
        previous = "0" * 64
        payloads = []
        for raw in rows:
            record = json.loads(raw)
            if set(record) != {"payload", "previous_sha256", "sha256"} or record["previous_sha256"] != previous:
                raise ValueError("invalid chain")
            expected = json.loads(_encode(record["payload"], previous))["sha256"]
            if expected != record["sha256"]:
                raise ValueError("invalid digest")
            payloads.append(record["payload"])
            previous = record["sha256"]
        intent = RecoveryIntent(**payloads[0])
        observation = RecoveryObservation(**payloads[1]) if len(payloads) == 2 else None
        state = RecoveryState(intent, observation)
        plan_recovery(state)
        return state, previous
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise RecoveryError("corrupt recovery journal; block new actuation") from exc


def _open(path: Path, flags):
    try:
        return os.open(path, flags | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise RecoveryError("journal unavailable; block new actuation") from exc


class RecoveryJournal:
    """One file per trial in an existing trusted directory; no overwrite/reuse."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self._closure_uncertain = False

    def create(self, intent: RecoveryIntent):
        intent = RecoveryIntent(**asdict(intent))
        descriptor = _open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_encode(asdict(intent), "0" * 64))
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def read(self) -> RecoveryState:
        if self._closure_uncertain:
            raise RecoveryError("closure durability is uncertain; reconcile before trusting this journal")
        with os.fdopen(_open(self.path, os.O_RDONLY), "rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            return _decode(stream.read())[0]

    def close_restored(self, observation: RecoveryObservation):
        if self._closure_uncertain:
            raise RecoveryError("closure durability is uncertain; reconcile before retrying")
        with os.fdopen(_open(self.path, os.O_RDWR | os.O_APPEND), "r+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            state, head = _decode(stream.read())
            if state.restored_observation is not None:
                raise RecoveryError("journal already closed")
            if plan_recovery(state, observation) != "unfinished_record_verified_restoration":
                raise RecoveryError("original power limit is not verified")
            self._closure_uncertain = True
            try:
                record = _encode(asdict(observation), head)
                if stream.write(record) != len(record):
                    raise OSError("short closure write")
                stream.flush()
                os.fsync(stream.fileno())
            except OSError as exc:
                raise RecoveryError("closure write or fsync failed; durability is uncertain") from exc
            self._closure_uncertain = False


def journal_then_actuate(journal: RecoveryJournal, intent: RecoveryIntent, actuation: Callable[[], object]):
    """Injected action is called only after file and directory fsync succeed."""
    journal.create(intent)
    return actuation()
