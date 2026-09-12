"""Read-only independent meter replay adapters.

Replay input is evidence, never an actuator.  Records retain their physical
boundary and provenance and are normalized through the authoritative telemetry
gate before callers may use them.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, Mapping, Tuple

from .telemetry import (
    FreshnessPolicy,
    MeterSnapshot,
    Quality,
    SourceSequenceReconciler,
    TelemetrySample,
    TelemetryValidationError,
    validate_authoritative_meter_snapshot,
)


class MeterReplayError(ValueError):
    pass


@dataclass(frozen=True)
class MeterProvenance:
    physical_boundary: str
    meter_id: str
    source_system: str
    replay_format: str
    replay_path: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.physical_boundary, self.meter_id, self.source_system)):
            raise ValueError("meter boundary, identity, and source system are required")


@dataclass(frozen=True)
class MeterObservation:
    snapshot: MeterSnapshot
    ingested_at_utc: datetime
    provenance: MeterProvenance

    @property
    def watts(self) -> float:
        return self.snapshot.active_power_watts

    @property
    def timestamp_utc(self) -> datetime:
        return self.snapshot.active_power.timestamp_utc


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise MeterReplayError("{} must be an ISO-8601 string".format(field))
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MeterReplayError("{} is not valid ISO-8601".format(field)) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MeterReplayError("{} must include a timezone".format(field))
    return parsed


def _boolean(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise MeterReplayError("{} must be true or false".format(field))


def _record_to_observation(
    record: Mapping[str, object], replay_format: str, replay_path: str
) -> Tuple[MeterObservation, bool]:
    required = (
        "timestamp_utc", "ingested_at_utc", "sequence", "epoch", "source_id",
        "value", "unit", "quality", "clock_synchronized", "physical_boundary",
        "meter_id", "source_system",
    )
    missing = [field for field in required if field not in record or record[field] in (None, "")]
    if missing:
        raise MeterReplayError("missing required fields: {}".format(", ".join(missing)))
    try:
        quality = Quality(str(record["quality"]).lower())
        sequence = int(str(record["sequence"]))
        value = float(str(record["value"]))
        latency = int(str(record.get("ingest_latency_ms", "0")))
        maximum = record.get("maximum_watts")
        maximum_watts = None if maximum in (None, "") else float(str(maximum))
        restart = _boolean(record.get("restart_epoch", False), "restart_epoch")
        clock_synchronized = _boolean(record["clock_synchronized"], "clock_synchronized")
    except (ValueError, TypeError) as exc:
        raise MeterReplayError("record contains an invalid numeric or enum value") from exc

    source_id = str(record["source_id"])
    sample = TelemetrySample(
        _timestamp(record["timestamp_utc"], "timestamp_utc"),
        sequence,
        source_id,
        value,
        str(record["unit"]),
        quality,
        latency,
        str(record["epoch"]),
    )
    snapshot = MeterSnapshot(
        sample,
        source_id,
        clock_synchronized=clock_synchronized,
        minimum_watts=0.0,
        maximum_watts=maximum_watts,
    )
    provenance = MeterProvenance(
        str(record["physical_boundary"]),
        str(record["meter_id"]),
        str(record["source_system"]),
        replay_format,
        replay_path,
    )
    return MeterObservation(snapshot, _timestamp(record["ingested_at_utc"], "ingested_at_utc"), provenance), restart


class _ReplayAdapter:
    replay_format = ""

    def __init__(self, path: Path, freshness_policy: FreshnessPolicy = FreshnessPolicy()):
        self.path = Path(path)
        self.freshness_policy = freshness_policy

    @property
    def read_only(self) -> bool:
        return True

    def _records(self) -> Iterable[Mapping[str, object]]:
        raise NotImplementedError

    def observations(self) -> Tuple[MeterObservation, ...]:
        reconciler = SourceSequenceReconciler()
        output = []
        for index, record in enumerate(self._records(), 1):
            try:
                observation, restart = _record_to_observation(
                    record, self.replay_format, str(self.path.resolve())
                )
                sample = observation.snapshot.active_power
                if restart:
                    reconciler.declare_restart_epoch(sample.source_id, sample.source_epoch)
                reconciler.accept(sample)
                validate_authoritative_meter_snapshot(
                    observation.snapshot, observation.ingested_at_utc, self.freshness_policy
                )
            except (TelemetryValidationError, MeterReplayError, ValueError) as exc:
                raise MeterReplayError("record {}: {}".format(index, exc)) from exc
            output.append(observation)
        return tuple(output)


class JsonlMeterReplay(_ReplayAdapter):
    replay_format = "jsonl"

    def _records(self) -> Iterator[Mapping[str, object]]:
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MeterReplayError("line {} is not valid JSON".format(line_number)) from exc
                if not isinstance(record, dict):
                    raise MeterReplayError("line {} must contain a JSON object".format(line_number))
                yield record


class CsvMeterReplay(_ReplayAdapter):
    replay_format = "csv"

    def _records(self) -> Iterator[Mapping[str, object]]:
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)

