"""Local-only CLI for read-only NVIDIA/BMC qualification evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Sequence

from .alignment import AlignmentPolicy, HostOverheadModel
from .gpu_observer import NvidiaPowerObserver
from .qualification import BmcPowerObserver, collect_read_only_qualification, qualification_packet_document
from .telemetry import FreshnessPolicy


class QualificationCliError(RuntimeError):
    pass


_FIELDS = {
    "schema", "host_id", "chassis_id", "gpu_uuid", "meter_id",
    "physical_boundary", "gpu_source_epoch", "bmc_source_epoch",
    "nvidia_smi_path", "ipmitool_path", "clock_synchronized", "samples",
    "sample_interval_seconds", "maximum_skew_seconds", "minimum_coverage",
    "maximum_observation_age_seconds", "maximum_ingest_latency_ms",
    "overhead_fixed_watts", "overhead_dynamic_fraction",
    "minimum_boundary_delta_watts", "maximum_boundary_delta_watts",
    "calibration_id",
}


def _text(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise QualificationCliError(f"{field} must be a non-empty string")
    return value


def _number(data: dict, field: str) -> float:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise QualificationCliError(f"{field} must be a finite number")
    return float(value)


def load_config(path: Path) -> dict:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise QualificationCliError("config must be an absolute regular non-symlink file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationCliError(f"cannot read qualification config: {exc}") from exc
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise QualificationCliError("qualification config fields do not exactly match schema v1")
    if data["schema"] != "gridrudder-read-only-qualification-config:v1":
        raise QualificationCliError("unsupported qualification config schema")
    for field in _FIELDS - {"schema", "clock_synchronized", "samples"}:
        if field.endswith("_watts") or field in {
            "sample_interval_seconds", "maximum_skew_seconds", "minimum_coverage",
            "maximum_observation_age_seconds", "maximum_ingest_latency_ms",
            "overhead_dynamic_fraction",
        }:
            _number(data, field)
        else:
            _text(data, field)
    if data["clock_synchronized"] is not True:
        raise QualificationCliError("clock_synchronized must be explicitly true")
    if (isinstance(data["samples"], bool) or not isinstance(data["samples"], int) or
            not 3 <= data["samples"] <= 3600):
        raise QualificationCliError("samples must be an integer in [3, 3600]")
    if re.fullmatch(r"GPU-[A-Za-z0-9-]+", data["gpu_uuid"]) is None:
        raise QualificationCliError("gpu_uuid does not match the exact schema")
    bounded = {
        "sample_interval_seconds": (0, 60, True),
        "maximum_skew_seconds": (0, 10, False),
        "minimum_coverage": (0.9, 1, True),
        "maximum_observation_age_seconds": (0, 60, True),
        "maximum_ingest_latency_ms": (0, 60000, True),
    }
    for field, (minimum, maximum, inclusive_minimum) in bounded.items():
        value = float(data[field])
        lower_ok = value >= minimum if inclusive_minimum else value > minimum
        if not lower_ok or value > maximum:
            raise QualificationCliError(f"{field} is outside the exact schema bounds")
    if data["overhead_fixed_watts"] < 0 or data["overhead_dynamic_fraction"] < 0:
        raise QualificationCliError("overhead calibration cannot be negative")
    if data["minimum_boundary_delta_watts"] > data["maximum_boundary_delta_watts"]:
        raise QualificationCliError("boundary calibration bounds are reversed")
    if not Path(data["nvidia_smi_path"]).is_absolute() or not Path(data["ipmitool_path"]).is_absolute():
        raise QualificationCliError("collector executable paths must be absolute")
    return data


def _validate_output_path(path: Path) -> None:
    if not path.is_absolute() or path.parent.is_symlink() or path.exists():
        raise QualificationCliError("output must be a new absolute path under a non-symlink parent")


def _write_new(path: Path, document: dict) -> None:
    _validate_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"),
                             allow_nan=False) + "\n"
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def run_local_read_only(
    config_path: Path, output_path: Path, *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    trusted_owner_uid: int = 0,
) -> dict:
    config = load_config(config_path)
    _validate_output_path(output_path)
    gpu = NvidiaPowerObserver(host_alias=config["host_id"],
        source_epoch=config["gpu_source_epoch"], executable=config["nvidia_smi_path"],
        runner=runner, clock=clock, monotonic=monotonic,
        maximum_ingest_age_seconds=config["maximum_observation_age_seconds"])
    bmc = BmcPowerObserver(host_id=config["host_id"],
        expected_chassis_id=config["chassis_id"], meter_id=config["meter_id"],
        physical_boundary=config["physical_boundary"], source_epoch=config["bmc_source_epoch"],
        executable=Path(config["ipmitool_path"]), runner=runner, clock=clock,
        monotonic=monotonic, required_owner_uid=trusted_owner_uid, clock_synchronized=True)
    packet = collect_read_only_qualification(host_id=config["host_id"],
        chassis_id=config["chassis_id"], gpu_uuid=config["gpu_uuid"], meter_id=config["meter_id"],
        expected_physical_boundary=config["physical_boundary"], gpu_observer=gpu,
        bmc_observer=bmc, samples=config["samples"],
        overhead_model=HostOverheadModel(config["overhead_fixed_watts"],
            config["overhead_dynamic_fraction"], config["minimum_boundary_delta_watts"],
            config["maximum_boundary_delta_watts"], config["calibration_id"]),
        alignment_policy=AlignmentPolicy(config["maximum_skew_seconds"],
            config["minimum_coverage"], config["maximum_observation_age_seconds"],
            config["maximum_ingest_latency_ms"]),
        freshness_policy=FreshnessPolicy(config["maximum_observation_age_seconds"],
            int(config["maximum_ingest_latency_ms"])), clock_synchronized=True,
        sleeper=sleeper, sample_interval_seconds=config["sample_interval_seconds"],
        trusted_nvidia_owner_uid=trusted_owner_uid)
    document = qualification_packet_document(packet)
    _write_new(output_path, document)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local read-only GPU/BMC qualification")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    document = run_local_read_only(args.config, args.output)
    print(json.dumps({"qualified": document["packet"]["qualified"],
                      "packet_sha256": document["packet_sha256"]}, sort_keys=True))
    return 0 if document["packet"]["qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
