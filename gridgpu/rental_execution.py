"""Concrete attended trial composition. Only explicit CLI invocation runs hardware.

Run the controller under rental_supervisor, never directly on a shared machine.
Hardware qualification and an approved lower limit are prerequisites, not inferred.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import sys
import time
import uuid

from .audit import AuditLog
from .cuda_workload import FixedCudaWorkload
from .live_measurement import LiveReadOnlyCollector
from .local_approval import LocalApprovalAuthority, SignedLocalApproval
from .measurement_collection import CompleteFreshCollector
from .performance_trial import OperatorAuthorization, PerformanceTrialConfig, run_attended_performance_trial
from .power_adapter import NvidiaSingleGpuPowerControl
from .qualification_gate import validate_qualification_packet
from .recovery_journal import RecoveryIntent, RecoveryJournal
from .rental_supervisor import PosixBoundedRunner, OriginalLimitBroker, supervise_attended_controller, arm_parent_death
from .supervised_recovery import JournaledPowerControl, RecoveryApproval, intent_digest
from .recovery_journal import RecoveryObservation
from .trial_archive import write_trial_archive
from .workload_benchmark import BenchmarkRunner, validate_comparison


RECIPE_FIELDS = {"worker_path", "worker_sha256", "python_executable", "nvidia_smi",
    "ipmitool", "matrix_size", "iterations", "job_ids", "meter_id",
    "physical_boundary", "source_epoch", "qualification_path", "qualification_sha256",
    "metrology_review_id"}


def load_recipe(path, digest):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("absolute regular recipe required")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("recipe differs from approved workload hash")
    recipe = json.loads(data)
    if set(recipe) != RECIPE_FIELDS:
        raise ValueError("recipe fields differ from schema")
    ids = recipe["job_ids"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 64 or
            any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in ids) or len(set(ids)) != len(ids)):
        raise ValueError("fixed unique job IDs required")
    for name in ("worker_path", "python_executable", "nvidia_smi", "ipmitool"):
        if not Path(recipe[name]).is_absolute():
            raise ValueError("absolute executable and artifact paths required")
    return recipe


class DrainBeforeControl:
    def __init__(self, control, workload, before_cap=None, target=None):
        self.control, self.workload = control, workload
        self.before_cap, self.target = before_cap, target

    def preflight(self):
        return self.control.preflight()

    def observe_limit(self, gpu):
        return self.control.observe_limit(gpu)

    def set_limit(self, gpu, watts):
        self.workload.require_idle()
        if self.before_cap is not None and watts == self.target:
            self.before_cap()
        return self.control.set_limit(gpu, watts)


def run_rental_trial(*, config, authorization, intent, signed, authority_directory,
                     run_directory, recipe_path, confirm=input,
                     clock=lambda: datetime.now(timezone.utc)):
    """Requires an externally supervised session leader and fresh signed approval.

    Credentials/signatures are never exported in the result archive. Each run uses
    a new private directory. Read-only observations still require hardware access.
    """
    if os.name != "posix" or os.getpid() != os.getpgrp():
        raise ValueError("controller must be a watchdog-owned process-group leader")
    directory = Path(run_directory)
    if (not directory.is_absolute() or directory.resolve() != directory or
            directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077):
        raise ValueError("private canonical run directory required")
    if any(directory.iterdir()):
        raise ValueError("new empty run directory required; never overwrite prior evidence")
    recipe = load_recipe(recipe_path, config.workload_sha256)
    if config.meter_source_id != config.host_id + ":" + recipe["meter_id"]:
        raise ValueError("recipe meter does not bind trial")
    authority = LocalApprovalAuthority(authority_directory, clock=clock)
    if not authority.verify_trial(config, authorization, intent, signed, consume=False):
        raise ValueError("signed exact trial approval rejected before hardware access")

    def qualify():
        return validate_qualification_packet(Path(recipe["qualification_path"]), recipe["qualification_sha256"],
            host_id=config.host_id, chassis_id=config.chassis_id, gpu_uuid=config.gpu_uuid,
            meter_id=recipe["meter_id"], physical_boundary=recipe["physical_boundary"],
            metrology_review_id=recipe["metrology_review_id"], nvidia_executable=Path(recipe["nvidia_smi"]),
            bmc_executable=Path(recipe["ipmitool"]), clock=clock)

    qualification = qualify()
    workload = FixedCudaWorkload(python_executable=Path(recipe["python_executable"]),
        worker_path=Path(recipe["worker_path"]), worker_sha256=recipe["worker_sha256"],
        gpu_uuid=config.gpu_uuid, matrix_size=recipe["matrix_size"], iterations=recipe["iterations"],
        supervised_process_group=os.getpgrp())
    nvidia, bmc = str(Path(recipe["nvidia_smi"]).resolve()), str(Path(recipe["ipmitool"]).resolve())
    commands = [(nvidia, NvidiaSingleGpuPowerControl.QUERY, "--format=csv,noheader,nounits"),
        (nvidia, LiveReadOnlyCollector.NVIDIA_QUERY, "--format=csv,noheader,nounits"),
        (bmc, "fru", "print", "0"), (bmc, "dcmi", "power", "reading")]
    commands.extend((nvidia, "-i", config.gpu_uuid, "-pl", f"{value:.3f}")
                    for value in (intent.target_watts, intent.original_watts))
    command_runner = PosixBoundedRunner(commands, supervised_process_group=os.getpid())
    raw_control = NvidiaSingleGpuPowerControl(executable=Path(nvidia), gpu_uuid=config.gpu_uuid,
        target_power_limit_watts=config.target_power_limit_watts, runner=command_runner)
    journal = RecoveryJournal(directory / "recovery.jsonl")
    control = DrainBeforeControl(JournaledPowerControl(raw_control, journal, intent,
        verify_intent=lambda value: value == intent and authority.verify_trial(
            config, authorization, value, signed, consume=False), clock=clock,
        observation_source="pinned-nvidia-readback"), workload,
        before_cap=qualify, target=intent.target_watts)
    sample_directory = directory / "samples"
    sample_directory.mkdir(mode=0o700)
    sample_count = 0

    def retain_sample(sample):
        nonlocal sample_count
        write_trial_archive(sample_directory / f"sample-{sample_count:06d}.json",
            evidence_kind="physical_unqualified", config=config,
            outcome={"status": "partial_sample_only"}, measurements=[sample],
            command_evidence=[], recovery_state=None,
            runtime={"python": platform.python_version()},
            qualification={"status": "not_a_complete_trial"})
        sample_count += 1

    collector = LiveReadOnlyCollector(host_id=config.host_id, chassis_id=config.chassis_id,
        gpu_uuid=config.gpu_uuid, meter_id=recipe["meter_id"],
        physical_boundary=recipe["physical_boundary"], source_epoch=recipe["source_epoch"],
        workload_sha256=config.workload_sha256, nvidia_executable=Path(nvidia), bmc_executable=Path(bmc),
        runner=command_runner, utc_clock=clock, monotonic_clock=time.monotonic, sleeper=time.sleep,
        start_workload=workload.start, finish_workload=workload.finish, evidence_sink=retain_sample)

    def collect(request):
        try:
            return collector(request)
        except BaseException:
            workload.abort()
            raise

    benchmark = BenchmarkRunner(CompleteFreshCollector(collect,
        expected_jobs=lambda *_: tuple(recipe["job_ids"]), utc_clock=clock, monotonic_clock=time.monotonic),
        workload_sha256=config.workload_sha256, meter_source_id=config.meter_source_id,
        chassis_id=config.chassis_id)
    outcome = {"status": "incomplete"}
    try:
        result = run_attended_performance_trial(config, authorization,
            audit_log=AuditLog(directory / "audit.jsonl"), control=control, workload_runner=benchmark,
            verify_authorization=lambda value: authority.verify_trial(config, value, intent, signed),
            attended_confirmation=confirm, lock_directory=directory,
            workload_artifact_path=Path(recipe_path), now=clock)
        validate_comparison(tuple(benchmark.measurements), config.repetitions)
        outcome = {"status": "completed_unqualified", "result": asdict(result)}
        return result
    except BaseException as exc:
        outcome = {"status": "failed", "error_type": type(exc).__name__, "detail": str(exc)}
        raise
    finally:
        try:
            workload.abort()
        finally:
            try:
                state = journal.read()
            except Exception as exc:
                state = {"unavailable": type(exc).__name__}
            write_trial_archive(directory / "evidence.json", evidence_kind="physical_unqualified",
                config=config, outcome=outcome, measurements=collector.evidence,
                command_evidence=raw_control.evidence, recovery_state=state,
                runtime={"python": platform.python_version(), "platform": platform.platform(),
                         "workload": workload.last_metadata, "recipe": recipe},
                qualification=qualification)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--execute-approved-trial", action="store_true", required=True)
    parser.add_argument("--controller", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--supervisor-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--settings-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args()
    raw_settings = args.settings.read_bytes()
    if len(raw_settings) > 1048576:
        raise ValueError("settings exceed size bound")
    settings_sha256 = hashlib.sha256(raw_settings).hexdigest()
    if args.controller and args.settings_sha256 != settings_sha256:
        raise ValueError("controller settings differ from supervisor-approved bytes")
    data = json.loads(raw_settings)
    expected = {"config", "authorization", "intent", "signed", "authority_directory", "run_directory", "recipe_path"}
    if set(data) != expected:
        raise ValueError("settings fields differ from schema")
    config = PerformanceTrialConfig(**data["config"])
    authorization = OperatorAuthorization(**data["authorization"])
    intent = RecoveryIntent(**data["intent"])
    signed = SignedLocalApproval(**data["signed"])
    if args.controller:
        arm_parent_death(args.supervisor_pid)
        run_rental_trial(config=config, authorization=authorization, intent=intent,
            signed=signed, authority_directory=data["authority_directory"],
            run_directory=data["run_directory"], recipe_path=data["recipe_path"])
        return
    authority = LocalApprovalAuthority(data["authority_directory"])
    recipe = load_recipe(data["recipe_path"], config.workload_sha256)
    if not authority.verify_trial(config, authorization, intent, signed, consume=False):
        raise ValueError("exact launch approval rejected")
    maximum_seconds = 3 * (config.warmup_seconds + config.repetitions * config.sample_seconds) + 60
    if maximum_seconds > 3600:
        raise ValueError("first rental trial must fit one hour including cleanup margin")
    phrase = f"RUN {config.host_id} {config.gpu_uuid} {config.target_power_limit_watts:.3f}W"
    if input(f"Attended trial: type {phrase}\n") != phrase:
        raise ValueError("fresh launch confirmation rejected")
    command = (sys.executable, "-m", "gridgpu.rental_execution", "--settings",
               str(args.settings.resolve()), "--execute-approved-trial", "--controller",
               "--supervisor-pid", str(os.getpid()), "--settings-sha256", settings_sha256)
    journal = RecoveryJournal(Path(data["run_directory"]) / "recovery.jsonl")
    recovery = RecoveryApproval(intent_digest(intent), authorization.operator,
        uuid.uuid4().hex, (datetime.now(timezone.utc) + timedelta(seconds=maximum_seconds + 600)).isoformat())
    recovery_signed = authority.issue_recovery(intent, recovery)
    nvidia = str(Path(recipe["nvidia_smi"]).resolve())
    observer = NvidiaSingleGpuPowerControl(executable=Path(nvidia), gpu_uuid=config.gpu_uuid,
        target_power_limit_watts=config.target_power_limit_watts,
        runner=PosixBoundedRunner(((nvidia, NvidiaSingleGpuPowerControl.QUERY,
                                   "--format=csv,noheader,nounits"),)))

    def restore(value):
        OriginalLimitBroker(journal, Path(nvidia), authorize_restore=lambda expected:
            expected == intent and authority.verify_recovery(intent, recovery, recovery_signed,
                                                             consume=False))(value)

    result = {"status": "supervision_incomplete"}
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f"supervisor received signal {signum}")

    previous_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        result = supervise_attended_controller(command, journal,
            authorize_launch=lambda actual: actual == command and authority.verify_trial(
                config, authorization, intent, signed, consume=False),
            maximum_seconds=maximum_seconds, controller_input=phrase + "\n",
            recovery_approval=recovery, reconciliation_options=dict(
                lock_directory=Path(data["run_directory"]),
                verify_and_consume=lambda approval: authority.verify_recovery(intent, approval, recovery_signed),
                confirm=lambda text: input(f"Recovery required: type {text}\n"),
                observe=lambda value: RecoveryObservation(value.host_id, value.gpu_uuid,
                    observer.observe_limit(value.gpu_uuid), datetime.now(timezone.utc).isoformat(),
                    "pinned-nvidia-readback"), restore=restore,
                clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic,
                source_id="pinned-nvidia-readback", maximum_seconds=35))
        observed = observer.observe_limit(config.gpu_uuid)
        result["final_observed_watts"] = observed
        result["final_observed_at_utc"] = datetime.now(timezone.utc).isoformat()
        if observed != intent.original_watts:
            raise RuntimeError("CRITICAL: supervisor final restoration check failed")
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__, detail=str(exc))
        raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        try:
            state = journal.read()
        except Exception as exc:
            state = {"unavailable": type(exc).__name__}
        write_trial_archive(Path(data["run_directory"]) / "supervisor-evidence.json",
            evidence_kind="physical_unqualified", config=config, outcome=result,
            measurements=[], command_evidence=observer.evidence, recovery_state=state,
            runtime={"python": platform.python_version(), "platform": platform.platform()},
            qualification={"status": "supervision_record_not_energy_evidence"})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
