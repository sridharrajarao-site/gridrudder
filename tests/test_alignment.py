from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from gridgpu.alignment import (
    AlignmentPolicy,
    GpuPowerObservation,
    HostOverheadModel,
    align_power_signals,
    validate_gpu_for_alignment,
    validate_meter_for_alignment,
)
from gridgpu.meter import MeterObservation, MeterProvenance
from gridgpu.telemetry import MeterSnapshot, Quality, TelemetrySample


BASE = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
OVERHEAD = HostOverheadModel(100.0, 0.0, 80.0, 120.0, "host-a:pdu-calibration:v1")


def meter(second, watts, ingest_delay=0.05, quality=Quality.GOOD, epoch="meter-epoch-1", meter_id="meter-1", host="host-a"):
    timestamp = BASE + timedelta(seconds=second)
    sample = TelemetrySample(timestamp, int(second), "pcc", watts, "W", quality, int(ingest_delay * 1000), epoch)
    raw = MeterObservation(
        MeterSnapshot(sample, "pcc"),
        timestamp + timedelta(seconds=ingest_delay),
        MeterProvenance("host-pdu-output", meter_id, "historian", "test", "memory"),
    )
    return validate_meter_for_alignment(raw, host_id=host, expected_physical_boundary="host-pdu-output")


def gpu(second, watts, ingest_delay=0.04, quality=Quality.GOOD, epoch="gpu-epoch-1", meter_id="meter-1", host="host-a", sequence=None):
    timestamp = BASE + timedelta(seconds=second)
    raw = GpuPowerObservation(
        timestamp, timestamp + timedelta(seconds=ingest_delay), watts, "dcgm", quality,
        host, meter_id, epoch, int(second * 10 if sequence is None else sequence), True,
        "nvidia-smi:uuid-bound:v1",
    )
    return validate_gpu_for_alignment(raw)


class SignalAlignmentTests(unittest.TestCase):
    def test_validated_aligned_signals_separate_boundary_overhead_from_confidence(self):
        report = align_power_signals(
            [meter(0, 1100), meter(1, 1200), meter(2, 1300)],
            [gpu(0.1, 1000), gpu(1.1, 1100), gpu(2.1, 1200)],
            OVERHEAD,
            AlignmentPolicy(maximum_skew_seconds=0.5, minimum_coverage=1.0),
        )
        self.assertTrue(report.accepted, report.reasons)
        self.assertEqual(report.coverage, 1.0)
        self.assertAlmostEqual(report.mean_latency_ms, 45.0)
        self.assertAlmostEqual(report.mean_boundary_delta_watts, 100.0)
        self.assertAlmostEqual(report.mean_expected_host_overhead_watts, 100.0)
        self.assertAlmostEqual(report.mean_absolute_overhead_deviation_watts, 0.0)
        self.assertGreater(report.temporal_confidence, 0.0)
        self.assertEqual(report.data_quality_confidence, 1.0)

    def test_dynamic_and_fixed_overhead_are_modeled_explicitly(self):
        model = HostOverheadModel(50.0, 0.05, 90.0, 110.0, "cal:v2")
        report = align_power_signals([meter(0, 1100)], [gpu(0, 1000)], model)
        pair = report.pairs[0]
        self.assertEqual(pair.boundary_delta_watts, 100.0)
        self.assertEqual(pair.expected_host_overhead_watts, 100.0)
        self.assertEqual(pair.overhead_deviation_watts, 0.0)

    def test_raw_unvalidated_observations_are_refused(self):
        valid_meter = meter(0, 1100)
        raw_meter = valid_meter.observation
        valid_gpu = gpu(0, 1000)
        raw_gpu = valid_gpu.observation
        self.assertIn("explicitly validated", " ".join(align_power_signals([raw_meter], [valid_gpu], OVERHEAD).reasons))
        self.assertIn("explicitly validated", " ".join(align_power_signals([valid_meter], [raw_gpu], OVERHEAD).reasons))

    def test_host_and_meter_bindings_must_match(self):
        host_mismatch = align_power_signals([meter(0, 1100)], [gpu(0, 1000, host="host-b")], OVERHEAD)
        meter_mismatch = align_power_signals([meter(0, 1100)], [gpu(0, 1000, meter_id="meter-2")], OVERHEAD)
        self.assertIn("same host", " ".join(host_mismatch.reasons))
        self.assertIn("authoritative meter", " ".join(meter_mismatch.reasons))

    def test_source_epoch_duplicate_and_regressed_sequences_fail_closed(self):
        epoch_change = align_power_signals(
            [meter(0, 1100), meter(1, 1100, epoch="meter-epoch-2")],
            [gpu(0, 1000), gpu(1, 1000)], OVERHEAD,
        )
        duplicate_gpu = align_power_signals(
            [meter(0, 1100), meter(1, 1100)],
            [gpu(0, 1000, sequence=2), gpu(1, 1000, sequence=2)], OVERHEAD,
        )
        self.assertIn("meter source/epoch/sequence", " ".join(epoch_change.reasons))
        self.assertIn("GPU source/epoch/sequence", " ".join(duplicate_gpu.reasons))

    def test_outside_calibrated_overhead_is_not_called_measurement_error_and_is_refused(self):
        report = align_power_signals([meter(0, 1400)], [gpu(0, 1000)], OVERHEAD)
        self.assertFalse(report.accepted)
        self.assertIn("boundary delta", " ".join(report.reasons))
        self.assertEqual(report.pairs[0].boundary_delta_watts, 400.0)
        self.assertFalse(report.pairs[0].overhead_within_calibration_bounds)
        self.assertFalse(any("measurement error" in name for name in report.__dataclass_fields__))

    def test_insufficient_misaligned_and_high_latency_evidence_is_refused(self):
        insufficient = align_power_signals(
            [meter(0, 1100), meter(1, 1100), meter(2, 1100)], [gpu(0, 1000)],
            OVERHEAD, AlignmentPolicy(minimum_coverage=0.8),
        )
        misaligned = align_power_signals(
            [meter(0, 1100)], [gpu(10, 1000)], OVERHEAD,
            AlignmentPolicy(maximum_skew_seconds=0.5),
        )
        delayed_gpu = gpu(0, 1000, ingest_delay=2)
        latency = align_power_signals(
            [meter(0, 1100)], [delayed_gpu], OVERHEAD,
            AlignmentPolicy(maximum_observation_age_seconds=5, maximum_ingest_latency_ms=1000),
        )
        self.assertIn("coverage", " ".join(insufficient.reasons))
        self.assertIn("misaligned", " ".join(misaligned.reasons))
        self.assertIn("latency", " ".join(latency.reasons))

    def test_validation_rejects_bad_quality_clock_provenance_and_boundary(self):
        with self.assertRaises(ValueError):
            gpu(0, 1000, quality=Quality.SUSPECT)
        good = gpu(0, 1000).observation
        with self.assertRaises(ValueError):
            validate_gpu_for_alignment(replace(good, clock_synchronized=False))
        raw_meter = meter(0, 1100).observation
        with self.assertRaises(ValueError):
            validate_meter_for_alignment(raw_meter, host_id="host-a", expected_physical_boundary="PCC")

    def test_forged_or_stale_validation_tokens_do_not_bypass_revalidation(self):
        valid_meter = meter(0, 1100)
        forged_meter = replace(valid_meter, token=replace(valid_meter.token, source_epoch="forged"))
        valid_gpu = gpu(0, 1000)
        forged_gpu = replace(valid_gpu, token=replace(valid_gpu.token, host_id="host-b"))
        meter_report = align_power_signals([forged_meter], [valid_gpu], OVERHEAD)
        gpu_report = align_power_signals([valid_meter], [forged_gpu], OVERHEAD)
        self.assertIn("meter validation token contradicts", " ".join(meter_report.reasons))
        self.assertIn("GPU validation token contradicts", " ".join(gpu_report.reasons))

    def test_empty_evidence_is_refused(self):
        report = align_power_signals([], [], OVERHEAD)
        self.assertFalse(report.accepted)
        self.assertIn("both validated meter and GPU evidence are required", report.reasons)


if __name__ == "__main__":
    unittest.main()
