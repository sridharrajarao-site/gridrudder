"""Bounded local command boundary for an attended single-GPU experiment.

Not wired to a CLI. Authorization, the durable audit and the exclusive trial
lock belong to performance_trial. An OS-enforced command broker is still
required; this Python allowlist is not a privilege-isolation mechanism.
"""

from dataclasses import dataclass
import csv
import math
from pathlib import Path
import re
import subprocess
from typing import Callable

from .performance_trial import GpuPreflight
from .qualification import inspect_pinned_executable


class PowerAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandEvidence:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class NvidiaSingleGpuPowerControl:
    """Allow exactly one cap and the captured original limit on one UUID.

    The mandatory runner permits hardware-free testing and explicit selection
    of a deployment command boundary. No shell, sudo, persistence-mode changes,
    GPU index selection, remote arguments, or caller-provided command flags.
    """

    QUERY = ("--query-gpu=uuid,driver_version,power.limit,power.min_limit,"
             "power.max_limit,temperature.gpu,mig.mode.current,compute_mode")

    def __init__(self, *, executable: Path, gpu_uuid: str,
                 target_power_limit_watts: float, runner: Callable,
                 required_owner_uid: int = 0, maximum_temperature_c: float = 80):
        if not re.fullmatch(r"GPU-[0-9a-fA-F-]+", gpu_uuid):
            raise ValueError("an exact NVIDIA GPU UUID is required")
        if (isinstance(target_power_limit_watts, bool) or
                not math.isfinite(target_power_limit_watts) or target_power_limit_watts <= 0):
            raise ValueError("target must be finite and positive")
        if not math.isfinite(maximum_temperature_c) or not 0 < maximum_temperature_c <= 80:
            raise ValueError("temperature ceiling must be in (0, 80]")
        if float(f"{target_power_limit_watts:.3f}") != target_power_limit_watts:
            raise ValueError("target must have at most three decimal places")
        self.provenance = inspect_pinned_executable(executable, required_owner_uid)
        self.gpu_uuid = gpu_uuid
        self.target = target_power_limit_watts
        self._runner = runner
        self._owner = required_owner_uid
        self._temperature = maximum_temperature_c
        self._original = None
        self._attempted = False
        self.evidence: list[CommandEvidence] = []

    def _run(self, args):
        path = Path(self.provenance.resolved_path)
        if inspect_pinned_executable(path, self._owner) != self.provenance:
            raise PowerAdapterError("NVIDIA executable provenance changed")
        argv = (str(path), *args)
        try:
            result = self._runner(argv, capture_output=True, text=True, check=False,
                                  timeout=10, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        except (OSError, subprocess.SubprocessError) as exc:
            raise PowerAdapterError("NVIDIA command failed or timed out; state is uncertain") from exc
        self.evidence.append(CommandEvidence(argv, result.returncode, result.stdout, result.stderr))
        if inspect_pinned_executable(path, self._owner) != self.provenance:
            raise PowerAdapterError("NVIDIA executable changed during command")
        if result.returncode != 0:
            raise PowerAdapterError("NVIDIA command rejected; inspect retained command evidence")
        return result.stdout

    def _read(self):
        rows = list(csv.reader(self._run((self.QUERY, "--format=csv,noheader,nounits")).splitlines()))
        if len(rows) != 1 or len(rows[0]) != 8:
            raise PowerAdapterError("exactly one physical GPU with complete fields is required")
        row = [value.strip() for value in rows[0]]
        if row[0] != self.gpu_uuid or not row[1]:
            raise PowerAdapterError("GPU identity or driver is invalid")
        try:
            limit, minimum, maximum, temperature = map(float, row[2:6])
        except ValueError as exc:
            raise PowerAdapterError("unsupported or malformed power/temperature observation") from exc
        if (not all(math.isfinite(value) for value in (limit, minimum, maximum, temperature))
                or not 0 < minimum <= limit <= maximum or temperature < 0):
            raise PowerAdapterError("invalid GPU power bounds or temperature")
        mig_safe = row[6] in {"Disabled", "N/A", "[N/A]"}
        healthy = temperature <= self._temperature and row[7] == "Default" and mig_safe
        return row[1], limit, minimum, maximum, healthy, not mig_safe

    def preflight(self):
        driver, limit, minimum, _, healthy, mig = self._read()
        if not healthy or not minimum <= self.target < limit:
            raise PowerAdapterError("GPU screening or lower-only target rejected")
        if self._original is not None:
            raise PowerAdapterError("adapter instances are single-trial; preflight already captured")
        self._original = limit
        return (GpuPreflight(self.gpu_uuid, healthy, mig, driver, self.provenance.sha256),)

    def observe_limit(self, gpu_uuid: str) -> float:
        self._identity(gpu_uuid)
        return self._read()[1]

    def _identity(self, gpu_uuid):
        if gpu_uuid != self.gpu_uuid:
            raise PowerAdapterError("GPU is outside the adapter scope")

    def set_limit(self, gpu_uuid: str, watts: float) -> None:
        self._identity(gpu_uuid)
        if self._original is None or isinstance(watts, bool) or watts not in (self.target, self._original):
            raise PowerAdapterError("only the configured cap or captured restoration is allowed")
        restoring = watts == self._original
        if not restoring:
            if self._attempted:
                raise PowerAdapterError("a cap was already attempted on this single-trial adapter")
            _, limit, minimum, _, healthy, _ = self._read()
            if not healthy or limit != self._original or self.target < minimum:
                raise PowerAdapterError("GPU state changed before cap")
            self._attempted = True  # A timeout/nonzero response may still have mutated hardware.
        elif not self._attempted:
            # The trial requests restoration even when our pre-cap screening
            # rejected the write. Prove unchanged state without issuing a write.
            if self.observe_limit(gpu_uuid) != self._original:
                raise PowerAdapterError("unattempted cap has unexpected state; restoration is unproven")
            return
        # Restoration remains available after a failed cap or unhealthy telemetry.
        self._run(("-i", self.gpu_uuid, "-pl", f"{watts:.3f}"))
        if abs(self.observe_limit(gpu_uuid) - watts) > 0.5:
            raise PowerAdapterError("power-limit readback did not verify requested state")
