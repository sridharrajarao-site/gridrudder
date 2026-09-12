"""Transport-neutral accelerator adapter contracts.

The supervisory controller consumes these interfaces without knowing whether
telemetry came from the simulator, a local CLI, or a future remote agent.
Physical adapters remain read-only during the shadow-mode milestone described
by ADR-0001.
"""

from dataclasses import dataclass, replace
from typing import Dict, Iterable, Optional, Protocol, Tuple


class AdapterError(RuntimeError):
    """Base error raised by accelerator adapters."""


class ReadOnlyAdapterError(AdapterError):
    """Raised when actuation is requested from a shadow adapter."""


@dataclass(frozen=True)
class AcceleratorCapabilities:
    telemetry_available: bool
    power_limit_visible: bool
    power_limit_writable: bool
    source: str
    detail: Optional[str] = None


@dataclass(frozen=True)
class AcceleratorDevice:
    device_id: str
    name: str
    power_watts: Optional[float]
    utilization_percent: Optional[float]
    power_limit_watts: Optional[float]
    min_power_limit_watts: Optional[float]
    max_power_limit_watts: Optional[float]


class AcceleratorAdapter(Protocol):
    """Minimum accelerator boundary used by controller-side code."""

    def capabilities(self) -> AcceleratorCapabilities:
        ...

    def list_devices(self) -> Tuple[AcceleratorDevice, ...]:
        ...

    def set_power_limit(self, device_id: str, watts: float) -> None:
        """Request a bounded limit.

        This exists in the domain contract for future approved adapters. Shadow
        adapters must reject it, and no MVP physical implementation may write.
        """
        ...


class SimulatedAcceleratorAdapter:
    """Deterministic in-memory adapter for controller and contract tests."""

    def __init__(self, devices: Iterable[AcceleratorDevice], writable: bool = True):
        self._devices: Dict[str, AcceleratorDevice] = {device.device_id: device for device in devices}
        if len(self._devices) == 0:
            raise ValueError("at least one simulated accelerator is required")
        self._writable = writable

    def capabilities(self) -> AcceleratorCapabilities:
        return AcceleratorCapabilities(True, True, self._writable, "simulator")

    def list_devices(self) -> Tuple[AcceleratorDevice, ...]:
        return tuple(self._devices[key] for key in sorted(self._devices))

    def set_power_limit(self, device_id: str, watts: float) -> None:
        if not self._writable:
            raise ReadOnlyAdapterError("simulated adapter is configured read-only")
        try:
            device = self._devices[device_id]
        except KeyError as exc:
            raise AdapterError("unknown accelerator: {}".format(device_id)) from exc
        minimum = device.min_power_limit_watts
        maximum = device.max_power_limit_watts
        if minimum is None or maximum is None:
            raise AdapterError("power-limit bounds are unknown for {}".format(device_id))
        if watts < minimum or watts > maximum:
            raise AdapterError(
                "power limit {:.3f} W is outside [{:.3f}, {:.3f}] W".format(watts, minimum, maximum)
            )
        self._devices[device_id] = replace(device, power_limit_watts=float(watts))

