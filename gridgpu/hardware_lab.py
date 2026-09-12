"""Deprecated first-generation physical power-cap experiment.

This module is intentionally separate from the production read-only adapter.  It
may only lower one explicitly identified GPU's power limit, records intent before
mutation, reads whole-host power through IPMI DCMI, and restores the original
device state before returning. Its CLI is disabled: new integrations must use
``performance_trial.run_attended_performance_trial`` because this older API
does not bind authorization to the host, workload artifact, and BMC chassis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Optional, Sequence

from .audit import AuditLog


class HardwareTrialError(RuntimeError):
    """The trial failed closed or could not prove restoration."""


@dataclass(frozen=True)
class GpuPowerState:
    uuid: str
    power_draw_watts: float
    power_limit_watts: float
    minimum_power_limit_watts: float
    maximum_power_limit_watts: float
    persistence_enabled: bool


@dataclass(frozen=True)
class HardwareTrialConfig:
    gpu_uuid: str
    target_power_limit_watts: float
    approval_id: str
    actor: str
    settle_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.gpu_uuid.strip() or not self.approval_id.strip() or not self.actor.strip():
            raise ValueError("gpu_uuid, approval_id, and actor must be non-empty")
        if not math.isfinite(self.target_power_limit_watts):
            raise ValueError("target power limit must be finite")
        if not math.isfinite(self.settle_seconds) or self.settle_seconds < 0:
            raise ValueError("settle_seconds must be finite and non-negative")


@dataclass(frozen=True)
class HardwareTrialResult:
    gpu_uuid: str
    original_limit_watts: float
    target_limit_watts: float
    baseline_gpu_watts: float
    capped_gpu_watts: float
    baseline_host_watts: float
    capped_host_watts: float
    gpu_delta_watts: float
    host_delta_watts: float
    restored: bool
    audit_head_hash: str


CommandRunner = Callable[..., subprocess.CompletedProcess]


def _run_checked(
    runner: CommandRunner, command: Sequence[str], *, description: str
) -> subprocess.CompletedProcess:
    try:
        result = runner(command, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HardwareTrialError(f"{description} failed: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise HardwareTrialError(f"{description} failed: {detail}")
    return result


def _prepare_audit_path(audit_log: AuditLog) -> None:
    path = Path(audit_log.path)
    parent = path.parent
    if parent.is_symlink() or (path.exists() and (path.is_symlink() or not path.is_file())):
        raise HardwareTrialError("audit path must be a regular non-symlink file")
    parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    information = path.stat()
    if information.st_uid != os.geteuid():
        raise HardwareTrialError("audit file must be owned by the effective operator")
    os.chmod(path, 0o600)


def _append_best_effort(audit_log: AuditLog, event_type: str, payload: dict, actor: str) -> None:
    try:
        audit_log.append(event_type, payload, actor=actor)
    except BaseException:
        # The caller still raises the original critical condition.  This helper
        # exists only to avoid masking it with a secondary audit failure.
        pass


class NvidiaLabPowerControl:
    """Minimal NVIDIA write surface, restricted to persistence and power caps."""

    def __init__(self, executable: str = "nvidia-smi", runner: CommandRunner = subprocess.run):
        self.executable = executable
        self.runner = runner

    def observe(self, expected_uuid: str) -> GpuPowerState:
        result = _run_checked(
            self.runner,
            (
                self.executable,
                "--query-gpu=uuid,power.draw,power.limit,power.min_limit,power.max_limit,persistence_mode",
                "--format=csv,noheader,nounits",
            ),
            description="NVIDIA observation",
        )
        rows = [row for row in csv.reader(result.stdout.splitlines()) if row]
        matches = [row for row in rows if row[0].strip() == expected_uuid]
        if len(matches) != 1 or len(matches[0]) != 6:
            raise HardwareTrialError("exactly one matching GPU observation is required")
        row = [value.strip() for value in matches[0]]
        try:
            values = tuple(float(value) for value in row[1:5])
        except ValueError as exc:
            raise HardwareTrialError("NVIDIA observation contains a nonnumeric value") from exc
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise HardwareTrialError("NVIDIA observation contains an invalid power value")
        persistence = row[5].lower()
        if persistence not in {"enabled", "disabled"}:
            raise HardwareTrialError("NVIDIA persistence state is invalid")
        return GpuPowerState(row[0], *values, persistence == "enabled")

    def set_persistence(self, gpu_uuid: str, enabled: bool) -> None:
        _run_checked(
            self.runner,
            ("sudo", "-n", self.executable, "-i", gpu_uuid, "-pm", "1" if enabled else "0"),
            description="persistence-mode change",
        )

    def set_power_limit(self, gpu_uuid: str, watts: float) -> None:
        _run_checked(
            self.runner,
            ("sudo", "-n", self.executable, "-i", gpu_uuid, "-pl", f"{watts:.3f}"),
            description="power-limit change",
        )


class DcmiPowerMeter:
    """Read instantaneous whole-host watts from the independent BMC path."""

    _READING = re.compile(r"Instantaneous power reading:\s*([0-9]+(?:\.[0-9]+)?)\s+Watts")

    def __init__(
        self,
        executable: str = "ipmitool",
        runner: CommandRunner = subprocess.run,
        dynamic_library_path: Optional[str] = None,
    ):
        self.executable = executable
        self.runner = runner
        if dynamic_library_path is not None and not Path(dynamic_library_path).is_absolute():
            raise ValueError("dynamic_library_path must be absolute")
        self.dynamic_library_path = dynamic_library_path

    def read_watts(self) -> float:
        command = ["sudo", "-n"]
        if self.dynamic_library_path is not None:
            command.extend(("env", f"LD_LIBRARY_PATH={self.dynamic_library_path}"))
        command.extend((self.executable, "dcmi", "power", "reading"))
        result = _run_checked(
            self.runner,
            tuple(command),
            description="DCMI power observation",
        )
        match = self._READING.search(result.stdout)
        if match is None:
            raise HardwareTrialError("DCMI response has no instantaneous whole-host watts")
        watts = float(match.group(1))
        if not math.isfinite(watts) or watts < 0:
            raise HardwareTrialError("DCMI power observation is invalid")
        return watts


def run_hardware_trial(
    config: HardwareTrialConfig,
    *,
    audit_log: AuditLog,
    control: Optional[NvidiaLabPowerControl] = None,
    meter: Optional[DcmiPowerMeter] = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> HardwareTrialResult:
    """Deprecated test seam retained only for historical hardware-free tests.

    There is intentionally no supported CLI entry. Do not use for new physical
    trials; it lacks the exact-scope controls in ``performance_trial``.
    """

    control = control or NvidiaLabPowerControl()
    meter = meter or DcmiPowerMeter()
    if isinstance(audit_log, AuditLog):
        _prepare_audit_path(audit_log)
    initial = control.observe(config.gpu_uuid)
    target = config.target_power_limit_watts
    if target < initial.minimum_power_limit_watts or target > initial.maximum_power_limit_watts:
        raise HardwareTrialError("target power limit is outside device bounds")
    if target >= initial.power_limit_watts:
        raise HardwareTrialError("lab trial target must lower the current power limit")

    baseline_host = meter.read_watts()
    intent_record = audit_log.append(
        "physical_trial.intent",
        {
            "approval_id": config.approval_id,
            "gpu_uuid": config.gpu_uuid,
            "original_limit_watts": initial.power_limit_watts,
            "target_limit_watts": target,
            "baseline_gpu_watts": initial.power_draw_watts,
            "baseline_host_watts": baseline_host,
            "facility_write_control": False,
            "lab_only": True,
        },
        actor=config.actor,
    )
    if isinstance(audit_log, AuditLog):
        intent_verification = audit_log.verify()
        if intent_verification.head_hash != intent_record.get("record_hash"):
            raise HardwareTrialError("durable intent could not be verified before mutation")

    persistence_attempted = False
    mutation_attempted = False
    capped: Optional[GpuPowerState] = None
    capped_host: Optional[float] = None
    trial_error: Optional[BaseException] = None
    restore_error: Optional[BaseException] = None
    try:
        if not initial.persistence_enabled:
            persistence_attempted = True
            control.set_persistence(config.gpu_uuid, True)
        mutation_attempted = True
        control.set_power_limit(config.gpu_uuid, target)
        sleeper(config.settle_seconds)
        capped = control.observe(config.gpu_uuid)
        if abs(capped.power_limit_watts - target) > 0.5:
            raise HardwareTrialError("requested power cap did not become effective")
        capped_host = meter.read_watts()
    except BaseException as exc:  # restoration must also run for injected failures
        trial_error = exc
    finally:
        if mutation_attempted:
            try:
                control.set_power_limit(config.gpu_uuid, initial.power_limit_watts)
            except BaseException as exc:
                restore_error = exc
        if persistence_attempted:
            try:
                control.set_persistence(config.gpu_uuid, False)
            except BaseException as exc:
                restore_error = restore_error or exc

    verification_error: Optional[BaseException] = None
    try:
        restored_state = control.observe(config.gpu_uuid)
        restored = (
            abs(restored_state.power_limit_watts - initial.power_limit_watts) <= 0.5
            and restored_state.persistence_enabled == initial.persistence_enabled
        )
    except BaseException as exc:
        verification_error = exc
        restored = False
    if restore_error is not None or not restored:
        _append_best_effort(
            audit_log,
            "physical_trial.restore_failed",
            {
                "approval_id": config.approval_id,
                "gpu_uuid": config.gpu_uuid,
                "restored": restored,
                "detail": str(restore_error or verification_error or "restoration verification failed"),
            },
            config.actor,
        )
        cause = restore_error or verification_error
        raise HardwareTrialError("CRITICAL: original GPU state restoration is unproven") from cause
    if trial_error is not None:
        audit_log.append(
            "physical_trial.failed_safe",
            {
                "approval_id": config.approval_id,
                "gpu_uuid": config.gpu_uuid,
                "restored": True,
                "detail": str(trial_error),
            },
            actor=config.actor,
        )
        if isinstance(trial_error, HardwareTrialError):
            raise trial_error
        raise HardwareTrialError(f"trial failed: {trial_error}") from trial_error

    assert capped is not None and capped_host is not None
    result = HardwareTrialResult(
        gpu_uuid=config.gpu_uuid,
        original_limit_watts=initial.power_limit_watts,
        target_limit_watts=target,
        baseline_gpu_watts=initial.power_draw_watts,
        capped_gpu_watts=capped.power_draw_watts,
        baseline_host_watts=baseline_host,
        capped_host_watts=capped_host,
        gpu_delta_watts=capped.power_draw_watts - initial.power_draw_watts,
        host_delta_watts=capped_host - baseline_host,
        restored=True,
        audit_head_hash="",
    )
    audit_log.append("physical_trial.completed", asdict(result), actor=config.actor)
    verified = audit_log.verify()
    return HardwareTrialResult(**{**asdict(result), "audit_head_hash": verified.head_hash})
