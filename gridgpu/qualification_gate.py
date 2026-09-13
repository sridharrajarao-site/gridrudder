"""Approved, fresh read-only qualification packet gate; no hardware commands."""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from .qualification import inspect_pinned_executable


class QualificationGateError(ValueError):
    pass


def validate_qualification_packet(path, expected_file_sha256, *, host_id, chassis_id,
        gpu_uuid, meter_id, physical_boundary, metrology_review_id, nvidia_executable,
        bmc_executable, clock, maximum_age_seconds=900, required_owner_uid=0):
    """Require a recipe-bound packet and explicit operator metrology attestation.

    A hash binds approved bytes, not the truth of a measurement. This gate cannot
    independently prove meter calibration, site ownership or operator review.
    """
    if (type(maximum_age_seconds) not in (int, float) or not math.isfinite(maximum_age_seconds)
            or not 0 < maximum_age_seconds <= 3600):
        raise QualificationGateError("qualification maximum age must be in (0, 3600]")
    if any(not isinstance(v, str) or not v.strip() for v in
            (host_id, chassis_id, gpu_uuid, meter_id, physical_boundary, metrology_review_id)):
        raise QualificationGateError("exact qualification identities and metrology review required")
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 10000000:
        raise QualificationGateError("bounded absolute regular qualification packet required")
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest()
    if file_hash != expected_file_sha256:
        raise QualificationGateError("qualification file differs from approved recipe hash")
    now = clock()
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise QualificationGateError("aware qualification clock required")

    def fresh(value):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.utcoffset() is None or not 0 <= (now - timestamp).total_seconds() <= maximum_age_seconds:
            raise QualificationGateError("qualification observation is stale or future dated")
        return timestamp

    try:
        document = json.loads(raw)
        if set(document) != {"schema", "packet", "packet_sha256"} or document["schema"] != "gridrudder-read-only-qualification:v1":
            raise QualificationGateError("unsupported qualification packet schema")
        packet = document["packet"]
        digest = hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if digest != document["packet_sha256"]:
            raise QualificationGateError("qualification packet digest mismatch")
        for key, expected in dict(host_id=host_id, chassis_id=chassis_id, gpu_uuid=gpu_uuid, meter_id=meter_id).items():
            if packet[key] != expected:
                raise QualificationGateError("qualification scope mismatch: " + key)
        if packet["qualified"] is not True or packet["alignment"]["accepted"] is not True:
            raise QualificationGateError("qualification or alignment was not accepted")
        nvidia = inspect_pinned_executable(Path(nvidia_executable), required_owner_uid)
        bmc = inspect_pinned_executable(Path(bmc_executable), required_owner_uid)
        if (packet["nvidia_executable_sha256"] != nvidia.sha256 or
                packet["bmc_executable_sha256"] != bmc.sha256):
            raise QualificationGateError("qualified executable hashes no longer match")
        meters, gpus, evidence = (packet[key] for key in ("meter_observations", "gpu_observations", "bmc_evidence"))
        if (not all(isinstance(v, list) and len(v) >= 3 for v in (meters, gpus, evidence)) or
                len(meters) != len(gpus) or len(meters) != len(evidence) or
                len(packet["alignment"]["pairs"]) < 3):
            raise QualificationGateError("qualification requires at least three complete aligned observations")
        previous_meter = previous_gpu = None
        for meter, gpu, bmc_sample in zip(meters, gpus, evidence):
            mo, go = meter["observation"], gpu["observation"]
            sample = mo["snapshot"]["active_power"]
            source = host_id + ":" + meter_id
            if (mo["provenance"]["physical_boundary"] != physical_boundary or
                    mo["provenance"]["meter_id"] != meter_id or
                    mo["snapshot"]["authoritative_source_id"] != source or
                    mo["snapshot"]["clock_synchronized"] is not True or
                    sample["source_id"] != source or sample["quality"] != "good" or
                    go["host_id"] != host_id or go["source_id"] != host_id + ":" + gpu_uuid or
                    go["bound_meter_id"] != meter_id or go["quality"] != "good" or
                    go["clock_synchronized"] is not True or
                    bmc_sample["chassis_id"] != chassis_id or bmc_sample["observation"] != mo or
                    bmc_sample["executable"]["sha256"] != bmc.sha256):
                raise QualificationGateError("nested qualification binding or source quality mismatch")
            for observation, kind in ((meter, "meter"), (gpu, "gpu")):
                token = observation["token"]
                if token["host_id"] != host_id or token["meter_id"] != meter_id or token["signal_type"] != kind:
                    raise QualificationGateError("validation token scope mismatch")
            for watts in (sample["value"], go["watts"]):
                if type(watts) not in (int, float) or not math.isfinite(watts) or watts < 0:
                    raise QualificationGateError("qualification power observation invalid")
            mt, gt = fresh(sample["timestamp_utc"]), fresh(go["timestamp_utc"])
            if fresh(mo["ingested_at_utc"]) < mt or fresh(go["ingested_at_utc"]) < gt:
                raise QualificationGateError("qualification ingestion precedes measurement")
            if (previous_meter is not None and mt <= previous_meter) or (previous_gpu is not None and gt <= previous_gpu):
                raise QualificationGateError("qualification observations are replayed or unordered")
            previous_meter, previous_gpu = mt, gt
        return dict(file_sha256=file_hash, packet_sha256=digest,
            metrology_review_id=metrology_review_id, physical_boundary=physical_boundary,
            validated_at_utc=now.isoformat(), sample_count=len(meters),
            status="approved_packet_checked_not_independent_metrology_proof")
    except QualificationGateError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationGateError("malformed qualification evidence") from exc
