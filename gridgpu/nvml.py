"""Read-only NVIDIA shadow adapter backed by the ``nvidia-smi`` CLI.

No pynvml dependency is required. More importantly, this module deliberately
contains no command that can modify a physical GPU. Capability reporting must
therefore never advertise physical write support.
"""

import csv
import math
import shutil
import subprocess
from typing import Callable, List, Optional, Sequence, Tuple

from .adapters import (
    AcceleratorCapabilities,
    AcceleratorDevice,
    AdapterError,
    ReadOnlyAdapterError,
)


_QUERY_FIELDS = (
    "index",
    "uuid",
    "name",
    "power.draw",
    "utilization.gpu",
    "power.limit",
    "power.min_limit",
    "power.max_limit",
)


def _optional_float(value: str) -> Optional[float]:
    normalized = value.strip()
    if not normalized or normalized.lower() in {"n/a", "[not supported]", "not supported"}:
        return None
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise AdapterError("invalid numeric value from nvidia-smi: {!r}".format(value)) from exc
    if not math.isfinite(parsed):
        raise AdapterError("non-finite numeric value from nvidia-smi: {!r}".format(value))
    return parsed


def _validate_device(device: AcceleratorDevice, row_number: int) -> None:
    if not device.device_id.strip():
        raise AdapterError("nvidia-smi row {} has no device identity".format(row_number))
    if not device.name.strip():
        raise AdapterError("nvidia-smi row {} has an empty device name".format(row_number))
    if device.power_watts is not None and device.power_watts < 0.0:
        raise AdapterError("nvidia-smi row {} has negative power draw".format(row_number))
    if device.utilization_percent is not None and not 0.0 <= device.utilization_percent <= 100.0:
        raise AdapterError("nvidia-smi row {} has utilization outside 0-100".format(row_number))
    for field_name, value in (
        ("power limit", device.power_limit_watts),
        ("minimum power limit", device.min_power_limit_watts),
        ("maximum power limit", device.max_power_limit_watts),
    ):
        if value is not None and value <= 0.0:
            raise AdapterError(
                "nvidia-smi row {} has non-positive {}".format(row_number, field_name)
            )
    minimum = device.min_power_limit_watts
    maximum = device.max_power_limit_watts
    current = device.power_limit_watts
    if minimum is not None and maximum is not None and minimum > maximum:
        raise AdapterError("nvidia-smi row {} has inverted power-limit bounds".format(row_number))
    if current is not None and minimum is not None and current < minimum:
        raise AdapterError("nvidia-smi row {} has power limit below minimum".format(row_number))
    if current is not None and maximum is not None and current > maximum:
        raise AdapterError("nvidia-smi row {} has power limit above maximum".format(row_number))


class NvidiaSmiShadowAdapter:
    """Discover and observe local NVIDIA GPUs without permitting actuation."""

    def __init__(
        self,
        executable: str = "nvidia-smi",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        which: Callable[[str], Optional[str]] = shutil.which,
    ):
        self._executable = executable
        self._runner = runner
        self._which = which

    def _resolved_executable(self) -> Optional[str]:
        # An explicit path remains testable and avoids a second PATH lookup.
        if "/" in self._executable:
            return self._executable
        return self._which(self._executable)

    def capabilities(self) -> AcceleratorCapabilities:
        executable = self._resolved_executable()
        if executable is None:
            return AcceleratorCapabilities(
                False,
                False,
                False,
                "nvidia-smi",
                "nvidia-smi executable not found",
            )
        try:
            devices = self._query(executable)
        except AdapterError as exc:
            return AcceleratorCapabilities(False, False, False, "nvidia-smi", str(exc))
        return AcceleratorCapabilities(
            telemetry_available=bool(devices),
            power_limit_visible=bool(devices) and all(d.power_limit_watts is not None for d in devices),
            power_limit_writable=False,
            source="nvidia-smi",
            detail=None if devices else "no NVIDIA accelerators reported",
        )

    def list_devices(self) -> Tuple[AcceleratorDevice, ...]:
        executable = self._resolved_executable()
        if executable is None:
            raise AdapterError("nvidia-smi executable not found")
        return self._query(executable)

    def _query(self, executable: str) -> Tuple[AcceleratorDevice, ...]:
        command: Sequence[str] = (
            executable,
            "--query-gpu={}".format(",".join(_QUERY_FIELDS)),
            "--format=csv,noheader,nounits",
        )
        try:
            result = self._runner(command, capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdapterError("unable to execute nvidia-smi: {}".format(exc)) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise AdapterError("nvidia-smi query failed: {}".format(detail))
        devices: List[AcceleratorDevice] = []
        seen_indices = set()
        for row_number, row in enumerate(csv.reader(result.stdout.splitlines()), start=1):
            if not row or all(not field.strip() for field in row):
                continue
            if len(row) != len(_QUERY_FIELDS):
                raise AdapterError(
                    "unexpected nvidia-smi row {}: expected {} fields, received {}".format(
                        row_number, len(_QUERY_FIELDS), len(row)
                    )
                )
            index, uuid, name, draw, utilization, limit, minimum, maximum = (field.strip() for field in row)
            if not index:
                raise AdapterError("nvidia-smi row {} has an empty device index".format(row_number))
            if index in seen_indices:
                raise AdapterError("duplicate NVIDIA device index: {}".format(index))
            seen_indices.add(index)
            device = AcceleratorDevice(
                    device_id=uuid or index,
                    name=name,
                    power_watts=_optional_float(draw),
                    utilization_percent=_optional_float(utilization),
                    power_limit_watts=_optional_float(limit),
                    min_power_limit_watts=_optional_float(minimum),
                    max_power_limit_watts=_optional_float(maximum),
                )
            _validate_device(device, row_number)
            if any(existing.device_id == device.device_id for existing in devices):
                raise AdapterError("duplicate NVIDIA device identity: {}".format(device.device_id))
            devices.append(device)
        return tuple(sorted(devices, key=lambda device: device.device_id))

    def set_power_limit(self, device_id: str, watts: float) -> None:
        del device_id, watts
        raise ReadOnlyAdapterError(
            "physical accelerator actuation is disabled; ADR-0001 requires shadow mode"
        )
