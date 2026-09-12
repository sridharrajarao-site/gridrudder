from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from gridgpu.meter import CsvMeterReplay, JsonlMeterReplay, MeterReplayError


def record(**changes):
    values = {
        "timestamp_utc": "2026-08-30T12:00:00Z",
        "ingested_at_utc": "2026-08-30T12:00:00.050Z",
        "sequence": 1,
        "epoch": "boot-1",
        "source_id": "pcc-1",
        "value": 12.5,
        "unit": "kW",
        "quality": "good",
        "clock_synchronized": True,
        "physical_boundary": "point-of-common-coupling",
        "meter_id": "revenue-meter-7",
        "source_system": "facility-historian",
        "ingest_latency_ms": 50,
        "maximum_watts": 100_000,
        "restart_epoch": False,
    }
    values.update(changes)
    return values


class MeterReplayTests(unittest.TestCase):
    def test_jsonl_replay_is_read_only_normalized_and_provenanced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meter.jsonl"
            path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
            adapter = JsonlMeterReplay(path)
            observations = adapter.observations()
        self.assertTrue(adapter.read_only)
        self.assertEqual(observations[0].watts, 12_500.0)
        self.assertEqual(observations[0].provenance.physical_boundary, "point-of-common-coupling")
        self.assertEqual(observations[0].provenance.replay_format, "jsonl")
        self.assertEqual(observations[0].snapshot.active_power.source_epoch, "boot-1")

    def test_csv_replay_parses_same_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meter.csv"
            fields = list(record().keys())
            import csv
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(record(value=500, unit="W"))
            observation = CsvMeterReplay(path).observations()[0]
        self.assertEqual(observation.watts, 500.0)
        self.assertEqual(observation.provenance.replay_format, "csv")

    def test_replay_rejects_stale_bad_or_unsynchronized_records(self):
        cases = (
            record(ingested_at_utc="2026-08-30T12:00:06Z"),
            record(quality="bad"),
            record(clock_synchronized=False),
        )
        for index, item in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.jsonl"
                path.write_text(json.dumps(item) + "\n", encoding="utf-8")
                with self.assertRaises(MeterReplayError):
                    JsonlMeterReplay(path).observations()

    def test_replay_rejects_duplicate_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.jsonl"
            path.write_text(
                json.dumps(record()) + "\n" + json.dumps(record()) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(MeterReplayError, "duplicate"):
                JsonlMeterReplay(path).observations()

    def test_replay_accepts_only_explicit_restart_epoch(self):
        first = record(sequence=9)
        restart = record(sequence=0, epoch="boot-2", restart_epoch=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restart.jsonl"
            path.write_text(json.dumps(first) + "\n" + json.dumps(restart) + "\n", encoding="utf-8")
            observations = JsonlMeterReplay(path).observations()
        self.assertEqual([item.snapshot.active_power.source_epoch for item in observations], ["boot-1", "boot-2"])

    def test_missing_boundary_or_naive_timestamp_is_rejected(self):
        for item in (record(physical_boundary=""), record(timestamp_utc="2026-08-30T12:00:00")):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.jsonl"
                path.write_text(json.dumps(item) + "\n", encoding="utf-8")
                with self.assertRaises(MeterReplayError):
                    JsonlMeterReplay(path).observations()


if __name__ == "__main__":
    unittest.main()

