"""Journal-aware trial control and one attended recovery attempt; no hardware CLI."""
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from .performance_trial import ExclusiveTrialLock
from .recovery_journal import RecoveryError, RecoveryIntent, RecoveryJournal, RecoveryObservation, _time


def intent_digest(intent: RecoveryIntent) -> str:
    return hashlib.sha256(json.dumps(asdict(intent), sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class JournaledPowerControl:
    """PowerControl-compatible decorator used inside the attended trial lock.

    Exact-trial authorization and audit still belong to performance_trial. The
    mandatory verifier independently gates the cap against this recovery intent.
    Restoration to the captured original remains possible after cap failure.
    """
    def __init__(self, control, journal: RecoveryJournal, intent: RecoveryIntent, *,
                 verify_intent: Callable[[RecoveryIntent], bool],
                 clock: Callable[[], datetime], observation_source: str):
        if not isinstance(observation_source, str) or not observation_source.strip():
            raise RecoveryError("trusted observation source required")
        self.control, self.journal, self.intent = control, journal, intent
        self.verify_intent, self.clock, self.source = verify_intent, clock, observation_source
        self._preflight = False
        self._cap_started = False
        self._closed = False

    def preflight(self):
        if self._preflight:
            raise RecoveryError("single-trial wrapper already used")
        inventory = tuple(self.control.preflight())
        matches = [gpu for gpu in inventory if gpu.uuid == self.intent.gpu_uuid]
        if len(matches) != 1 or not matches[0].healthy or matches[0].mig_enabled:
            raise RecoveryError("recovery intent GPU does not match healthy preflight")
        if self.control.observe_limit(self.intent.gpu_uuid) != self.intent.original_watts:
            raise RecoveryError("recovery original differs from observed preflight")
        self._preflight = True
        return inventory

    def observe_limit(self, gpu_uuid):
        if gpu_uuid != self.intent.gpu_uuid:
            raise RecoveryError("GPU outside recovery scope")
        return self.control.observe_limit(gpu_uuid)

    def set_limit(self, gpu_uuid, watts):
        if not self._preflight or gpu_uuid != self.intent.gpu_uuid or isinstance(watts, bool):
            raise RecoveryError("unqualified or out-of-scope actuation")
        if watts == self.intent.target_watts:
            if self._cap_started or self._closed or self.verify_intent(self.intent) is not True:
                raise RecoveryError("cap authorization invalid or already consumed")
            if _time(self.clock().isoformat()) < _time(self.intent.created_at_utc):
                raise RecoveryError("intent is in the future")
            self.journal.create(self.intent)  # File and directory fsync complete before any cap.
            self._cap_started = True
            self.control.set_limit(gpu_uuid, watts)
        elif watts == self.intent.original_watts:
            if not self._cap_started or self._closed:
                if self.observe_limit(gpu_uuid) != watts:
                    raise RecoveryError("unexpected state outside active recovery intent")
                return
            # Retry hardware restoration even if an earlier journal closure failed.
            self.control.set_limit(gpu_uuid, watts)
            observed = self.observe_limit(gpu_uuid)
            if observed != watts:
                raise RecoveryError("original limit restoration is unproven")
            self.journal.close_restored(RecoveryObservation(self.intent.host_id, gpu_uuid,
                observed, self.clock().isoformat(), self.source))
            self._closed = True
        else:
            raise RecoveryError("only intended cap and original restoration allowed")


@dataclass(frozen=True)
class RecoveryApproval:
    intent_sha256: str
    operator: str
    nonce: str
    expires_at_utc: str


def reconcile_attended_once(journal: RecoveryJournal, approval: RecoveryApproval, *,
        lock_directory: Path, process_gone: Callable[[], bool],
        verify_and_consume: Callable[[RecoveryApproval], bool],
        confirm: Callable[[str], str], observe: Callable[[RecoveryIntent], RecoveryObservation],
        restore: Callable[[RecoveryIntent], None], clock: Callable[[], datetime],
        monotonic: Callable[[], float], source_id: str, maximum_seconds: float = 10.0) -> str:
    """One authorized reconciliation attempt after independent process-loss proof.

    Time bounds are checked cooperatively after calls return. The injected broker
    must enforce actual I/O deadlines; this function cannot interrupt a hung call.
    """
    if type(maximum_seconds) not in (float, int) or not math.isfinite(maximum_seconds) or maximum_seconds <= 0:
        raise RecoveryError("finite positive recovery bound required")
    if not isinstance(source_id, str) or not source_id.strip():
        raise RecoveryError("trusted recovery source required")
    initial = journal.read()
    with ExclusiveTrialLock(lock_directory, initial.intent.host_id, initial.intent.gpu_uuid):
        state = journal.read()
        if state.intent != initial.intent:
            raise RecoveryError("recovery intent changed")
        if state.restored_observation is not None:
            return "already_closed_historical_record"
        if process_gone() is not True:
            raise RecoveryError("original workload process loss is unproven")
        if (approval.intent_sha256 != intent_digest(state.intent) or
                not isinstance(approval.operator, str) or not approval.operator.strip() or
                not isinstance(approval.nonce, str) or not approval.nonce.strip() or
                _time(approval.expires_at_utc) <= _time(clock().isoformat())):
            raise RecoveryError("recovery authorization does not bind an unexpired exact intent")
        phrase = f"RESTORE {state.intent.trial_id} {state.intent.gpu_uuid} {state.intent.original_watts:.3f}W"
        if confirm(phrase) != phrase:
            raise RecoveryError("fresh attended restoration confirmation required")
        if verify_and_consume(approval) is not True:
            raise RecoveryError("recovery authorization rejected or consumed")
        started = monotonic()
        if type(started) not in (int, float) or not math.isfinite(started):
            raise RecoveryError("invalid recovery clock")

        def check_deadline():
            current = monotonic()
            if (type(current) not in (int, float) or not math.isfinite(current) or
                    current < started or current - started > maximum_seconds):
                raise RecoveryError("recovery deadline exceeded or clock regressed; state uncertain")

        def fresh_observation():
            before = _time(clock().isoformat())
            value = observe(state.intent)
            after = _time(clock().isoformat())
            check_deadline()
            timestamp = _time(value.observed_at_utc)
            if (value.host_id != state.intent.host_id or value.gpu_uuid != state.intent.gpu_uuid or
                    value.source_id != source_id or not before <= timestamp <= after or
                    type(value.power_limit_watts) not in (int, float) or
                    not math.isfinite(value.power_limit_watts) or value.power_limit_watts <= 0):
                raise RecoveryError("recovery observation is stale, invalid or out of scope")
            return value

        observed = fresh_observation()
        if observed.power_limit_watts != state.intent.original_watts:
            if _time(approval.expires_at_utc) <= _time(clock().isoformat()):
                raise RecoveryError("recovery approval expired before write")
            restore(state.intent)
            check_deadline()
            observed = fresh_observation()
        if observed.power_limit_watts != state.intent.original_watts:
            raise RecoveryError("recovery did not verify original limit")
        journal.close_restored(observed)
        return "verified_restoration_recorded"
