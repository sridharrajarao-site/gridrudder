from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from gridgpu.qualification_gate import validate_qualification_packet, QualificationGateError


class QualificationGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.exe = self.base / "fixture"
        self.exe.write_text("fixture")
        self.exe.chmod(0o700)
        self.hash = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.packet = dict(host_id="host", chassis_id="chassis", gpu_uuid="GPU-a", meter_id="meter",
            nvidia_executable_sha256=self.hash, bmc_executable_sha256=self.hash,
            qualified=True, alignment=dict(accepted=True, pairs=[{}, {}, {}]),
            meter_observations=[], gpu_observations=[], bmc_evidence=[])
        for offset in (3, 2, 1):
            timestamp = (self.now - timedelta(seconds=offset)).isoformat()
            mo = dict(provenance=dict(physical_boundary="server", meter_id="meter"),
                ingested_at_utc=timestamp, snapshot=dict(authoritative_source_id="host:meter",
                clock_synchronized=True, active_power=dict(source_id="host:meter", quality="good",
                timestamp_utc=timestamp, value=200)))
            go = dict(host_id="host", source_id="host:GPU-a", bound_meter_id="meter", quality="good",
                clock_synchronized=True, watts=120, timestamp_utc=timestamp, ingested_at_utc=timestamp)
            for kind, obs, key in (("meter", mo, "meter_observations"), ("gpu", go, "gpu_observations")):
                self.packet[key].append(dict(observation=obs,
                    token=dict(host_id="host", meter_id="meter", signal_type=kind)))
            self.packet["bmc_evidence"].append(dict(chassis_id="chassis", observation=mo, executable=dict(sha256=self.hash)))
        self.path = self.base / "packet.json"

    def check(self, **kwargs):
        digest = hashlib.sha256(json.dumps(self.packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.path.write_text(json.dumps(dict(schema="gridrudder-read-only-qualification:v1",
            packet=self.packet, packet_sha256=digest)))
        args = dict(host_id="host", chassis_id="chassis", gpu_uuid="GPU-a", meter_id="meter",
            physical_boundary="server", metrology_review_id="operator-review", nvidia_executable=self.exe,
            bmc_executable=self.exe, clock=lambda: self.now, required_owner_uid=os.getuid())
        args.update(kwargs)
        return validate_qualification_packet(self.path, hashlib.sha256(self.path.read_bytes()).hexdigest(), **args)

    def test_fresh_bound_packet(self):
        self.assertEqual(self.check()["sample_count"], 3)

    def test_stale_packet(self):
        with self.assertRaisesRegex(QualificationGateError, "stale"):
            self.check(clock=lambda: self.now + timedelta(hours=2))

    def test_scope_and_boundary(self):
        for kwargs in (dict(gpu_uuid="GPU-other"), dict(chassis_id="other"), dict(physical_boundary="other")):
            with self.assertRaises(QualificationGateError):
                self.check(**kwargs)

    def test_unqualified_or_missing_review(self):
        with self.assertRaises(QualificationGateError):
            self.check(metrology_review_id="")
        self.packet["qualified"] = False
        with self.assertRaisesRegex(QualificationGateError, "accepted"):
            self.check()

    def test_replaced_executable(self):
        self.exe.write_text("replacement")
        with self.assertRaisesRegex(QualificationGateError, "hashes"):
            self.check()

    def test_missing_samples_and_replay(self):
        self.packet["alignment"]["pairs"] = []
        with self.assertRaisesRegex(QualificationGateError, "three"):
            self.check()
        self.packet["alignment"]["pairs"] = [{}, {}, {}]
        self.packet["gpu_observations"][1] = self.packet["gpu_observations"][0]
        with self.assertRaisesRegex(QualificationGateError, "unordered"):
            self.check()

    def test_age_cannot_be_unbounded(self):
        for age in (0, 3601, float("nan"), True):
            with self.assertRaises(QualificationGateError):
                self.check(maximum_age_seconds=age)

    def test_approved_file_and_internal_digest_tampering_rejected(self):
        self.check()
        original_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        document = json.loads(self.path.read_text())
        document["packet"]["qualified"] = False
        self.path.write_text(json.dumps(document))
        for digest, message in ((original_hash, "recipe hash"),
                (hashlib.sha256(self.path.read_bytes()).hexdigest(), "digest mismatch")):
            with self.assertRaisesRegex(QualificationGateError, message):
                validate_qualification_packet(self.path, digest, host_id="host", chassis_id="chassis",
                    gpu_uuid="GPU-a", meter_id="meter", physical_boundary="server",
                    metrology_review_id="review", nvidia_executable=self.exe, bmc_executable=self.exe,
                    clock=lambda: self.now, required_owner_uid=os.getuid())
