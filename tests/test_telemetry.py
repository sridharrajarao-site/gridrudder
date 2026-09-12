from datetime import datetime, timedelta, timezone
import unittest

from gridgpu.telemetry import (
    FreshnessPolicy,
    MeterSnapshot,
    Quality,
    SourceSequenceReconciler,
    TelemetrySample,
    TelemetryValidationError,
    assess_meter_decision_eligibility,
    normalize_active_power_watts,
    validate_authoritative_meter_snapshot,
)


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
POLICY = FreshnessPolicy(max_age_seconds=5.0, max_future_skew_seconds=0.25, max_ingest_latency_ms=1_000)


def meter_snapshot(**sample_changes):
    values = {
        "timestamp_utc": NOW,
        "monotonic_sequence": 42,
        "source_id": "pcc-meter-1",
        "value": 12_500.0,
        "unit": "W",
        "quality": Quality.GOOD,
        "ingest_latency_ms": 50,
    }
    values.update(sample_changes)
    return MeterSnapshot(TelemetrySample(**values), "pcc-meter-1", maximum_watts=100_000.0)


class TelemetryEligibilityTests(unittest.TestCase):
    def test_current_good_authoritative_meter_is_eligible(self):
        result = assess_meter_decision_eligibility(meter_snapshot(), NOW, POLICY)
        self.assertTrue(result.eligible)
        self.assertEqual(result.reasons, ())
        self.assertIs(validate_authoritative_meter_snapshot(meter_snapshot(), NOW, POLICY).active_power.quality, Quality.GOOD)

    def test_non_authoritative_source_fails_closed(self):
        result = assess_meter_decision_eligibility(meter_snapshot(source_id="gpu-derived-power"), NOW, POLICY)
        self.assertFalse(result.eligible)
        self.assertIn("sample is not from the authoritative meter", result.reasons)

    def test_each_non_good_quality_fails_closed(self):
        for quality in (Quality.SUSPECT, Quality.STALE, Quality.BAD):
            with self.subTest(quality=quality):
                result = assess_meter_decision_eligibility(meter_snapshot(quality=quality), NOW, POLICY)
                self.assertFalse(result.eligible)
                self.assertIn("meter quality is not GOOD", result.reasons)

    def test_old_and_future_samples_fail_freshness_policy(self):
        old = assess_meter_decision_eligibility(
            meter_snapshot(timestamp_utc=NOW - timedelta(seconds=5.001)), NOW, POLICY
        )
        future = assess_meter_decision_eligibility(
            meter_snapshot(timestamp_utc=NOW + timedelta(seconds=0.251)), NOW, POLICY
        )
        self.assertIn("meter sample is stale", old.reasons)
        self.assertIn("meter sample is too far in the future", future.reasons)

    def test_boundary_timestamps_are_eligible(self):
        at_old_boundary = meter_snapshot(timestamp_utc=NOW - timedelta(seconds=5))
        at_future_boundary = meter_snapshot(timestamp_utc=NOW + timedelta(seconds=0.25))
        self.assertTrue(assess_meter_decision_eligibility(at_old_boundary, NOW, POLICY).eligible)
        self.assertTrue(assess_meter_decision_eligibility(at_future_boundary, NOW, POLICY).eligible)

    def test_unsynchronized_clock_and_excess_latency_fail_closed(self):
        unsynchronized = MeterSnapshot(
            meter_snapshot().active_power, "pcc-meter-1", clock_synchronized=False
        )
        delayed = meter_snapshot(ingest_latency_ms=1_001)
        self.assertIn(
            "meter clock is not synchronized",
            assess_meter_decision_eligibility(unsynchronized, NOW, POLICY).reasons,
        )
        self.assertIn(
            "meter ingest latency exceeds policy",
            assess_meter_decision_eligibility(delayed, NOW, POLICY).reasons,
        )

    def test_invalid_value_and_unit_fail_closed(self):
        for changes in (
            {"value": float("nan")},
            {"value": float("inf")},
            {"value": -1.0},
            {"unit": "MW"},
            {"value": True},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(
                    assess_meter_decision_eligibility(meter_snapshot(**changes), NOW, POLICY).eligible
                )

    def test_watts_and_kilowatts_expose_identical_canonical_watts(self):
        watts = meter_snapshot(value=12_500.0, unit="W")
        kilowatts = meter_snapshot(value=12.5, unit="kW")
        self.assertEqual(watts.active_power_watts, 12_500.0)
        self.assertEqual(kilowatts.active_power_watts, 12_500.0)
        self.assertEqual(normalize_active_power_watts(kilowatts.active_power), 12_500.0)

    def test_kilowatts_are_normalized_before_watt_bounds(self):
        below = MeterSnapshot(
            meter_snapshot(value=0.199, unit="kW").active_power,
            "pcc-meter-1",
            minimum_watts=200.0,
        )
        above = MeterSnapshot(
            meter_snapshot(value=100.001, unit="kW").active_power,
            "pcc-meter-1",
            maximum_watts=100_000.0,
        )
        self.assertIn(
            "active power is below the configured minimum",
            assess_meter_decision_eligibility(below, NOW, POLICY).reasons,
        )
        self.assertIn(
            "active power is above the configured maximum",
            assess_meter_decision_eligibility(above, NOW, POLICY).reasons,
        )

    def test_normalization_rejects_overflow_after_kw_conversion(self):
        sample = meter_snapshot(value=1.7976931348623157e308, unit="kW").active_power
        with self.assertRaises(TelemetryValidationError):
            normalize_active_power_watts(sample)

    def test_raise_path_contains_operator_reasons(self):
        invalid = meter_snapshot(
            timestamp_utc=NOW - timedelta(seconds=10), quality=Quality.SUSPECT
        )
        with self.assertRaises(TelemetryValidationError) as caught:
            validate_authoritative_meter_snapshot(invalid, NOW, POLICY)
        self.assertIn("quality", str(caught.exception))
        self.assertIn("stale", str(caught.exception))

    def test_naive_sample_timestamp_fails_closed(self):
        naive = meter_snapshot(timestamp_utc=datetime(2026, 8, 30, 12, 0))
        result = assess_meter_decision_eligibility(naive, NOW, POLICY)
        self.assertFalse(result.eligible)
        self.assertIn("meter timestamp must be timezone-aware", result.reasons)

    def test_empty_source_epoch_fails_closed(self):
        result = assess_meter_decision_eligibility(meter_snapshot(source_epoch=""), NOW, POLICY)
        self.assertIn("meter source_epoch is empty", result.reasons)


class SourceSequenceReconcilerTests(unittest.TestCase):
    def sample(self, source="meter-a", epoch="boot-1", sequence=0):
        return TelemetrySample(
            NOW, sequence, source, 1_000.0, "W", Quality.GOOD, 0, epoch
        )

    def test_first_sample_and_strictly_increasing_sequence_are_accepted(self):
        reconciler = SourceSequenceReconciler()
        first = reconciler.accept(self.sample(sequence=10))
        second = reconciler.accept(self.sample(sequence=11))
        self.assertEqual(first.last_sequence, 10)
        self.assertEqual(second.last_sequence, 11)

    def test_duplicate_is_rejected_without_advancing_cursor(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample(sequence=10))
        with self.assertRaisesRegex(TelemetryValidationError, "duplicate"):
            reconciler.accept(self.sample(sequence=10))
        self.assertEqual(reconciler.cursor("meter-a").last_sequence, 10)

    def test_regression_is_rejected_without_advancing_cursor(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample(sequence=10))
        with self.assertRaisesRegex(TelemetryValidationError, "regression"):
            reconciler.accept(self.sample(sequence=9))
        self.assertEqual(reconciler.cursor("meter-a").last_sequence, 10)

    def test_sequence_state_is_scoped_by_source(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample(source="meter-a", sequence=100))
        reconciler.accept(self.sample(source="meter-b", sequence=1))
        self.assertEqual(reconciler.cursor("meter-a").last_sequence, 100)
        self.assertEqual(reconciler.cursor("meter-b").last_sequence, 1)

    def test_epoch_change_requires_explicit_restart_declaration(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample(sequence=100))
        restarted = self.sample(epoch="boot-2", sequence=0)
        with self.assertRaisesRegex(TelemetryValidationError, "without declared restart"):
            reconciler.accept(restarted)
        reconciler.declare_restart_epoch("meter-a", "boot-2")
        cursor = reconciler.accept(restarted)
        self.assertEqual((cursor.source_epoch, cursor.last_sequence), ("boot-2", 0))

    def test_retired_epoch_cannot_be_replayed(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample(sequence=5))
        reconciler.declare_restart_epoch("meter-a", "boot-2")
        reconciler.accept(self.sample(epoch="boot-2", sequence=0))
        with self.assertRaisesRegex(TelemetryValidationError, "retired"):
            reconciler.accept(self.sample(epoch="boot-1", sequence=6))

    def test_restart_epoch_must_be_new_and_source_must_be_seen(self):
        reconciler = SourceSequenceReconciler()
        with self.assertRaisesRegex(TelemetryValidationError, "unseen"):
            reconciler.declare_restart_epoch("meter-a", "boot-2")
        reconciler.accept(self.sample())
        with self.assertRaisesRegex(TelemetryValidationError, "differ"):
            reconciler.declare_restart_epoch("meter-a", "boot-1")

    def test_different_pending_restart_cannot_be_overwritten(self):
        reconciler = SourceSequenceReconciler()
        reconciler.accept(self.sample())
        reconciler.declare_restart_epoch("meter-a", "boot-2")
        with self.assertRaisesRegex(TelemetryValidationError, "already pending"):
            reconciler.declare_restart_epoch("meter-a", "boot-3")


if __name__ == "__main__":
    unittest.main()
