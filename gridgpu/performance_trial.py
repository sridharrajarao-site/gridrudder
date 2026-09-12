"""Attended, deterministic useful-work benchmark for one isolated GPU.

The module contains no shell commands and no remote access.  Hardware actuation
is possible only through an explicitly injected control boundary after an
authorization verifier and an attended confirmation both succeed.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Callable, Optional, Protocol, Sequence

from .audit import AuditLog


class PerformanceTrialError(RuntimeError):
    pass


@dataclass(frozen=True)
class MeterSample:
    elapsed_seconds: float
    host_watts: float
    timestamp_utc: str
    source_id: str
    chassis_id: str


@dataclass(frozen=True)
class WorkSample:
    useful_units: float
    duration_seconds: float
    meter_samples: tuple[MeterSample, ...]


@dataclass(frozen=True)
class PerformanceTrialConfig:
    host_id: str
    gpu_uuid: str
    workload_id: str
    workload_sha256: str
    target_power_limit_watts: float
    meter_source_id: str
    chassis_id: str
    warmup_seconds: float = 30.0
    sample_seconds: float = 60.0
    repetitions: int = 3

    def __post_init__(self) -> None:
        for value in (self.host_id, self.gpu_uuid, self.workload_id,
                      self.meter_source_id, self.chassis_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("trial identities must be non-empty")
        if len(self.workload_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.workload_sha256):
            raise ValueError("workload_sha256 must be lowercase SHA-256")
        for value in (self.target_power_limit_watts, self.warmup_seconds, self.sample_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("power and durations must be finite and positive")
        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int) or self.repetitions < 2:
            raise ValueError("at least two repetitions are required")


def _binding(config: PerformanceTrialConfig, approval_id: str, operator: str,
             expires_at_utc: str, nonce: str) -> str:
    value = {
        "action": "attended_lower_gpu_power_limit_benchmark",
        "approval_id": approval_id,
        "operator": operator,
        "expires_at_utc": expires_at_utc,
        "nonce": nonce,
        "config": asdict(config),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperatorAuthorization:
    approval_id: str
    operator: str
    expires_at_utc: str
    nonce: str
    binding_sha256: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in
               (self.approval_id, self.operator, self.expires_at_utc, self.nonce)):
            raise ValueError("authorization identities must be non-empty")
        if len(self.binding_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.binding_sha256):
            raise ValueError("binding_sha256 must be lowercase SHA-256")

    @classmethod
    def bind(cls, config: PerformanceTrialConfig, *, approval_id: str, operator: str,
             expires_at_utc: str, nonce: str) -> "OperatorAuthorization":
        return cls(approval_id, operator, expires_at_utc, nonce,
                   _binding(config, approval_id, operator, expires_at_utc, nonce))


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    repetition: int
    useful_units: float
    duration_seconds: float
    throughput_per_second: float
    host_energy_joules: float
    average_host_watts: float
    joules_per_useful_unit: float
    meter_samples: tuple[MeterSample, ...]


@dataclass(frozen=True)
class PerformanceTrialResult:
    host_id: str
    gpu_uuid: str
    workload_id: str
    workload_sha256: str
    original_power_limit_watts: float
    target_power_limit_watts: float
    baseline: tuple[PhaseResult, ...]
    capped: tuple[PhaseResult, ...]
    restored_samples: tuple[PhaseResult, ...]
    restored: bool
    restored_limit_watts: float
    restored_at_utc: str
    driver_version: str
    nvidia_executable_sha256: str


class PowerControl(Protocol):
    def preflight(self) -> Sequence["GpuPreflight"]: ...
    def observe_limit(self, gpu_uuid: str) -> float: ...
    def set_limit(self, gpu_uuid: str, watts: float) -> None: ...


@dataclass(frozen=True)
class GpuPreflight:
    uuid: str
    healthy: bool
    mig_enabled: bool
    driver_version: str
    executable_sha256: str

    def __post_init__(self) -> None:
        if not self.uuid.strip() or not self.driver_version.strip():
            raise ValueError("GPU identity and driver version must be non-empty")
        if len(self.executable_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.executable_sha256):
            raise ValueError("executable provenance must be lowercase SHA-256")


class ExclusiveTrialLock(AbstractContextManager["ExclusiveTrialLock"]):
    """Non-blocking advisory lock keyed by the exact host/GPU pair."""

    def __init__(self, directory: Path, host_id: str, gpu_uuid: str) -> None:
        key = hashlib.sha256(f"{host_id}\0{gpu_uuid}".encode()).hexdigest()
        self.path = directory / f"loadhelm-{key}.lock"
        self._stream = None

    def __enter__(self) -> "ExclusiveTrialLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._stream.close()
            self._stream = None
            raise PerformanceTrialError("another trial owns the host/GPU lock") from exc
        return self

    def __exit__(self, *args: object) -> None:
        if self._stream is not None:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            self._stream.close()
            self._stream = None


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PerformanceTrialError("authorization expiry is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PerformanceTrialError("authorization expiry must be timezone-aware")
    return parsed


def _measure(phase: str, repetition: int, raw: WorkSample,
             expected_duration: float, expected_source: str,
             expected_chassis: str) -> PhaseResult:
    if not math.isfinite(raw.useful_units) or raw.useful_units <= 0:
        raise PerformanceTrialError("workload produced no valid useful work")
    if not math.isfinite(raw.duration_seconds) or raw.duration_seconds <= 0:
        raise PerformanceTrialError("workload duration is invalid")
    if abs(raw.duration_seconds - expected_duration) > max(1.0, expected_duration * 0.05):
        raise PerformanceTrialError("workload duration departed from the authorized window")
    samples = raw.meter_samples
    if any(not math.isfinite(sample.elapsed_seconds) for sample in samples):
        raise PerformanceTrialError("meter elapsed times must be finite")
    if len(samples) < 3 or samples[0].elapsed_seconds != 0 or abs(samples[-1].elapsed_seconds - raw.duration_seconds) > 1e-6:
        raise PerformanceTrialError("meter evidence must span the window with at least three samples")
    source = samples[0].source_id
    chassis = samples[0].chassis_id
    if source != expected_source or chassis != expected_chassis:
        raise PerformanceTrialError("meter evidence does not bind the authorized chassis")
    previous = -1.0
    previous_timestamp: Optional[datetime] = None
    energy = 0.0
    for left, right in zip(samples, samples[1:]):
        if (not left.timestamp_utc or not left.source_id or left.source_id != source or
                not left.chassis_id or left.chassis_id != chassis or
                not math.isfinite(left.host_watts) or left.host_watts < 0 or
                left.elapsed_seconds <= previous or right.elapsed_seconds <= left.elapsed_seconds):
            raise PerformanceTrialError("meter samples are invalid, unordered, or change source")
        timestamp = _parse_expiry(left.timestamp_utc)
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise PerformanceTrialError("meter timestamps are not strictly increasing")
        previous_timestamp = timestamp
        energy += (left.host_watts + right.host_watts) * 0.5 * (right.elapsed_seconds - left.elapsed_seconds)
        previous = left.elapsed_seconds
    last = samples[-1]
    if (not last.timestamp_utc or last.source_id != source or last.chassis_id != chassis or
            not math.isfinite(last.host_watts) or last.host_watts < 0):
        raise PerformanceTrialError("final meter sample is invalid")
    if previous_timestamp is not None and _parse_expiry(last.timestamp_utc) <= previous_timestamp:
        raise PerformanceTrialError("meter timestamps are not strictly increasing")
    throughput = raw.useful_units / raw.duration_seconds
    return PhaseResult(phase, repetition, raw.useful_units, raw.duration_seconds,
                       throughput, energy, energy / raw.duration_seconds,
                       energy / raw.useful_units, samples)


def run_attended_performance_trial(
    config: PerformanceTrialConfig,
    authorization: OperatorAuthorization,
    *,
    audit_log: AuditLog,
    control: PowerControl,
    workload_runner: Callable[[str, int, float], WorkSample],
    verify_authorization: Callable[[OperatorAuthorization], bool],
    attended_confirmation: Callable[[str], str],
    lock_directory: Path,
    workload_artifact_path: Path,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> PerformanceTrialResult:
    """Compare baseline/capped/restored work; restore after any attempted change."""

    def workload_digest() -> str:
        if workload_artifact_path.is_symlink() or not workload_artifact_path.is_file():
            raise PerformanceTrialError("workload artifact must be a regular non-symlink file")
        digest = hashlib.sha256()
        with workload_artifact_path.open("rb") as stream:
            for block in iter(lambda: stream.read(128 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    if workload_digest() != config.workload_sha256:
        raise PerformanceTrialError("workload artifact does not match authorized SHA-256")

    expected = _binding(config, authorization.approval_id, authorization.operator,
                        authorization.expires_at_utc, authorization.nonce)
    if authorization.binding_sha256 != expected or not verify_authorization(authorization):
        raise PerformanceTrialError("authorization is invalid or does not bind this exact trial")
    current_time = now()
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise PerformanceTrialError("authorization clock must be timezone-aware")
    if _parse_expiry(authorization.expires_at_utc) <= current_time:
        raise PerformanceTrialError("authorization has expired")
    if any(record["payload"].get("authorization_nonce") == authorization.nonce
           for record in audit_log.records()):
        raise PerformanceTrialError("authorization nonce was already used")
    phrase = f"RUN {config.host_id} {config.gpu_uuid} {config.target_power_limit_watts:.3f}W"
    if attended_confirmation(phrase) != phrase:
        raise PerformanceTrialError("fresh attended confirmation was not supplied")

    with ExclusiveTrialLock(lock_directory, config.host_id, config.gpu_uuid):
        inventory = tuple(control.preflight())
        if len({item.uuid for item in inventory}) != len(inventory):
            raise PerformanceTrialError("GPU inventory contains duplicate UUIDs")
        matches = [item for item in inventory if item.uuid == config.gpu_uuid]
        if len(matches) != 1:
            raise PerformanceTrialError("authorized GPU is not uniquely present")
        selected = matches[0]
        if not selected.healthy or selected.mig_enabled:
            raise PerformanceTrialError("GPU health or MIG preflight rejected actuation")
        original = control.observe_limit(config.gpu_uuid)
        if not math.isfinite(original) or config.target_power_limit_watts >= original:
            raise PerformanceTrialError("target must safely lower the observed power limit")
        audit_log.append("performance_trial.intent", {
            "authorization_nonce": authorization.nonce,
            "approval_id": authorization.approval_id,
            "binding_sha256": authorization.binding_sha256,
            "config": asdict(config),
            "original_power_limit_watts": original,
            "attended_only": True,
        }, actor=authorization.operator)
        baseline = []
        capped = []
        restored_samples = []
        changed = False
        trial_error: Optional[BaseException] = None
        restore_error: Optional[BaseException] = None
        try:
            workload_runner("baseline_warmup", -1, config.warmup_seconds)
            for repetition in range(config.repetitions):
                baseline.append(_measure("baseline", repetition,
                    workload_runner("baseline", repetition, config.sample_seconds), config.sample_seconds,
                    config.meter_source_id, config.chassis_id))
            if _parse_expiry(authorization.expires_at_utc) <= now():
                raise PerformanceTrialError("authorization expired before cap actuation")
            if workload_digest() != config.workload_sha256:
                raise PerformanceTrialError("workload artifact changed before cap actuation")
            changed = True
            control.set_limit(config.gpu_uuid, config.target_power_limit_watts)
            observed_cap = control.observe_limit(config.gpu_uuid)
            if not math.isfinite(observed_cap) or abs(observed_cap - config.target_power_limit_watts) > 0.5:
                raise PerformanceTrialError("capped limit could not be verified")
            workload_runner("capped_warmup", -1, config.warmup_seconds)
            for repetition in range(config.repetitions):
                capped.append(_measure("capped", repetition,
                    workload_runner("capped", repetition, config.sample_seconds), config.sample_seconds,
                    config.meter_source_id, config.chassis_id))
            control.set_limit(config.gpu_uuid, original)
            observed_restore = control.observe_limit(config.gpu_uuid)
            if not math.isfinite(observed_restore) or abs(observed_restore - original) > 0.5:
                raise PerformanceTrialError("restored limit could not be verified before workload")
            workload_runner("restored_warmup", -1, config.warmup_seconds)
            for repetition in range(config.repetitions):
                restored_samples.append(_measure("restored", repetition,
                    workload_runner("restored", repetition, config.sample_seconds), config.sample_seconds,
                    config.meter_source_id, config.chassis_id))
        except BaseException as exc:
            trial_error = exc
        finally:
            if changed:
                try:
                    control.set_limit(config.gpu_uuid, original)
                except BaseException as exc:
                    restore_error = exc
        try:
            restored_limit = control.observe_limit(config.gpu_uuid)
            restored = abs(restored_limit - original) <= 0.5
        except BaseException as exc:
            restore_error = restore_error or exc
            restored = False
            restored_limit = float("nan")
        if restore_error is not None or not restored:
            try:
                audit_log.append("performance_trial.restore_failed", {
                    "authorization_nonce": authorization.nonce,
                    "gpu_uuid": config.gpu_uuid,
                    "detail": str(restore_error or "restoration verification failed"),
                }, actor=authorization.operator)
            except BaseException:
                pass
            raise PerformanceTrialError("CRITICAL: original power limit restoration is unproven") from restore_error
        if trial_error is not None:
            audit_log.append("performance_trial.failed_safe", {
                "authorization_nonce": authorization.nonce,
                "gpu_uuid": config.gpu_uuid,
                "restored": True,
                "detail": str(trial_error),
            }, actor=authorization.operator)
            raise PerformanceTrialError(f"performance trial failed safely: {trial_error}") from trial_error
        if workload_digest() != config.workload_sha256:
            raise PerformanceTrialError("workload artifact changed during the trial")
        result = PerformanceTrialResult(config.host_id, config.gpu_uuid, config.workload_id,
            config.workload_sha256, original, config.target_power_limit_watts,
            tuple(baseline), tuple(capped), tuple(restored_samples), True, restored_limit, now().isoformat(),
            selected.driver_version, selected.executable_sha256)
        audit_log.append("performance_trial.completed", asdict(result), actor=authorization.operator)
        return result
