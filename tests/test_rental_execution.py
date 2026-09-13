"""Rental composition checks with real local approvals and no hardware I/O."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gridgpu.local_approval import LocalApprovalAuthority
from gridgpu.performance_trial import PerformanceTrialConfig, OperatorAuthorization
from gridgpu.recovery_journal import RecoveryIntent
from gridgpu.rental_execution import DrainBeforeControl, load_recipe, run_rental_trial
from gridgpu.live_measurement import LiveReadOnlyCollector
from gridgpu.power_adapter import NvidiaSingleGpuPowerControl
from gridgpu.workload_benchmark import JobOutcome
from gridgpu.trial_archive import verify_trial_archive


@dataclass
class FixtureResult:
    completed: bool = True


class RentalExecutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.run = self.base / "run"
        self.run.mkdir(mode=0o700)
        self.keys = self.base / "keys"
        self.keys.mkdir(mode=0o700)
        self.now = datetime(2026, 9, 13, tzinfo=timezone.utc)
        self.authority = LocalApprovalAuthority(self.keys, clock=lambda: self.now)
        self.authority.initialize()
        self.recipe = dict(worker_path="/fixture/worker", worker_sha256="b" * 64,
            python_executable="/fixture/python", nvidia_smi="/fixture/nvidia-smi",
            ipmitool="/fixture/ipmitool", matrix_size=512, iterations=10,
            job_ids=["one"], meter_id="meter", physical_boundary="server", source_epoch="epoch",
            qualification_path="/fixture/qualification.json", qualification_sha256="c" * 64,
            metrology_review_id="fixture-review")
        self.path = self.base / "recipe.json"
        self.path.write_text(json.dumps(self.recipe))
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.config = PerformanceTrialConfig("host", "GPU-fixture", "recipe", digest,
            125, "host:meter", "chassis", warmup_seconds=1, sample_seconds=3)
        self.authorization = OperatorAuthorization.bind(self.config, approval_id="approval",
            operator="operator", nonce="trial-one", expires_at_utc="2026-09-13T01:00:00+00:00")
        self.intent = RecoveryIntent("trial", "host", "GPU-fixture", self.authorization.binding_sha256,
            175, 125, "2026-09-13T00:00:00+00:00")
        self.signed = self.authority.issue_trial(self.config, self.authorization, self.intent)
        self.workload = Mock(last_metadata=None)
        self.raw = Mock(evidence=[])
        self.collector = Mock(evidence=[])
        self.archiver = Mock()

    def arguments(self, **changes):
        result = dict(config=self.config, authorization=self.authorization, intent=self.intent,
            signed=self.signed, authority_directory=self.keys, run_directory=self.run,
            recipe_path=self.path, clock=lambda: self.now, confirm=lambda phrase: phrase)
        result.update(changes)
        return result

    def boundaries(self, trial):
        """Keep real auth and orchestration; replace only hardware/data producers."""
        def benchmark(collector, **_):
            result = Mock(measurements=[])
            result.side_effect = collector
            return result
        patches = {
            "FixedCudaWorkload": Mock(return_value=self.workload),
            "NvidiaSingleGpuPowerControl": Mock(return_value=self.raw, QUERY="query"),
            "LiveReadOnlyCollector": Mock(return_value=self.collector, NVIDIA_QUERY="telemetry"),
            "PosixBoundedRunner": Mock(),
            "CompleteFreshCollector": lambda collector, **_: collector,
            "BenchmarkRunner": benchmark,
            "run_attended_performance_trial": trial,
            "validate_comparison": Mock(),
            "write_trial_archive": self.archiver,
            "validate_qualification_packet": Mock(return_value={"status": "fixture-only"}),
        }
        for name, value in patches.items():
            active = patch("gridgpu.rental_execution." + name, value)
            active.start()
            self.addCleanup(active.stop)
        for name in ("getpid", "getpgrp"):
            active = patch("gridgpu.rental_execution.os." + name, return_value=4321)
            active.start()
            self.addCleanup(active.stop)
        return patches

    def test_recipe_digest_binds_workload_settings(self):
        self.assertEqual(load_recipe(self.path, self.config.workload_sha256), self.recipe)
        self.recipe["iterations"] = 20
        self.path.write_text(json.dumps(self.recipe))
        with self.assertRaisesRegex(ValueError, "hash"):
            load_recipe(self.path, self.config.workload_sha256)

    def test_requires_process_group_leader_before_hardware(self):
        with patch("gridgpu.rental_execution.os.getpid", return_value=1), \
                patch("gridgpu.rental_execution.os.getpgrp", return_value=2), \
                patch("gridgpu.rental_execution.FixedCudaWorkload") as workload:
            with self.assertRaisesRegex(ValueError, "group"):
                run_rental_trial(**self.arguments())
            workload.assert_not_called()

    def test_drain_checked_before_cap_or_restoration(self):
        events = []
        self.workload.require_idle.side_effect = lambda: events.append("idle")
        self.raw.set_limit.side_effect = lambda *_: events.append("write")
        control = DrainBeforeControl(self.raw, self.workload)
        control.set_limit("GPU-fixture", 125)
        control.set_limit("GPU-fixture", 175)
        self.assertEqual(events, ["idle", "write", "idle", "write"])
        self.workload.require_idle.side_effect = RuntimeError("active")
        with self.assertRaisesRegex(RuntimeError, "active"):
            control.set_limit("GPU-fixture", 175)
        self.assertEqual(self.raw.set_limit.call_count, 2)

    def test_collector_failure_aborts_and_archives(self):
        def trial(config, authorization, **kwargs):
            self.assertTrue(kwargs["verify_authorization"](authorization))
            return kwargs["workload_runner"]("request")
        self.boundaries(trial)
        self.collector.side_effect = RuntimeError("meter lost")
        with self.assertRaisesRegex(RuntimeError, "meter lost"):
            run_rental_trial(**self.arguments())
        self.assertGreaterEqual(self.workload.abort.call_count, 1)
        self.assertEqual(self.archiver.call_args.kwargs["outcome"]["status"], "failed")

    def test_real_signature_replay_denied_by_trial_gate(self):
        def trial(config, authorization, **kwargs):
            if not kwargs["verify_authorization"](authorization):
                raise ValueError("replayed approval")
            return FixtureResult()
        patches = self.boundaries(trial)
        self.assertTrue(run_rental_trial(**self.arguments()).completed)
        patches["FixedCudaWorkload"].assert_called_once()
        self.assertEqual(patches["FixedCudaWorkload"].call_args.kwargs["supervised_process_group"], 4321)
        second = self.base / "run2"
        second.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "replayed"):
            run_rental_trial(**self.arguments(run_directory=second))

    def test_changed_trial_rejected_before_hardware(self):
        patches = self.boundaries(Mock())
        with self.assertRaisesRegex(ValueError, "approval"):
            run_rental_trial(**self.arguments(config=replace(self.config, repetitions=4)))
        patches["FixedCudaWorkload"].assert_not_called()

    def test_meter_binding_rejected_before_hardware(self):
        patches = self.boundaries(Mock())
        with self.assertRaisesRegex(ValueError, "meter"):
            run_rental_trial(**self.arguments(config=replace(self.config, meter_source_id="other")))
        patches["FixedCudaWorkload"].assert_not_called()

    def test_existing_evidence_never_overwritten(self):
        patches = self.boundaries(Mock())
        (self.run / "existing").write_text("retain")
        with self.assertRaisesRegex(ValueError, "empty"):
            run_rental_trial(**self.arguments())
        patches["FixedCudaWorkload"].assert_not_called()
        self.assertEqual((self.run / "existing").read_text(), "retain")

    def full_composition(self, fail_capped=False):
        """Actual trial, collector, journal, archive; only device/work replaced."""
        for name in ("nvidia_smi", "ipmitool"):
            artifact = self.base / name
            artifact.write_text("trusted fixture, never executed")
            artifact.chmod(0o700)
            self.recipe[name] = str(artifact)
        self.path.write_text(json.dumps(self.recipe))
        self.config = replace(self.config, gpu_uuid="GPU-abcd", warmup_seconds=2,
            workload_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.authorization = OperatorAuthorization.bind(self.config, approval_id="approval",
            operator="operator", nonce="trial-full", expires_at_utc="2026-09-13T01:00:00+00:00")
        self.intent = replace(self.intent, gpu_uuid=self.config.gpu_uuid,
                              authorization_sha256=self.authorization.binding_sha256)
        self.signed = self.authority.issue_trial(self.config, self.authorization, self.intent)
        self.elapsed, self.limit = 0.0, 175.0
        self.active, self.events, self.phase = False, [], None

        def utc():
            return self.now + timedelta(seconds=self.elapsed)

        def sleep(seconds):
            self.elapsed += seconds

        def start(request, origin):
            self.assertFalse(self.active)
            self.active = True
            self.phase = request.phase
            self.events.append(("start", request.phase, request.repetition))

        def finish(request, origin):
            self.active = False
            self.events.append(("finish", request.phase, request.repetition))
            return (JobOutcome("one", 0.1, 0.5, True),)

        def abort():
            self.events.append(("abort", self.phase))
            self.active = False

        def idle():
            self.assertFalse(self.active, "actuation occurred with active workload")
            self.events.append(("idle",))

        workload = Mock(last_metadata={"fixture": True}, start=start, finish=finish,
                        abort=abort, require_idle=idle)

        def command(argv, **kwargs):
            if "-pl" in argv:
                self.assertFalse(self.active)
                self.limit = float(argv[-1])
                self.events.append(("write", self.limit))
                output = "applied"
            elif NvidiaSingleGpuPowerControl.QUERY in argv:
                output = f"GPU-abcd, 550.1, {self.limit}, 100, 200, 45, Disabled, Default\n"
            elif "fru" in argv:
                output = "Chassis Serial : chassis\n"
            elif "dcmi" in argv:
                if fail_capped and self.phase == "capped" and self.active:
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                output = f"Instantaneous power reading: {self.limit + 100} Watts\n"
            else:
                output = f"GPU-abcd, {self.limit - 5}, 550.1\n"
            return subprocess.CompletedProcess(argv, 0, output, "")

        def control_factory(**kwargs):
            return NvidiaSingleGpuPowerControl(**kwargs, required_owner_uid=os.getuid())
        control_factory.QUERY = NvidiaSingleGpuPowerControl.QUERY

        def collector_factory(**kwargs):
            return LiveReadOnlyCollector(**kwargs, required_owner_uid=os.getuid())
        collector_factory.NVIDIA_QUERY = LiveReadOnlyCollector.NVIDIA_QUERY
        qualification = Mock(return_value={"status": "fixture-only"})
        replacements = {"FixedCudaWorkload": Mock(return_value=workload),
            "NvidiaSingleGpuPowerControl": control_factory,
            "LiveReadOnlyCollector": collector_factory,
            "PosixBoundedRunner": Mock(return_value=command),
            "validate_qualification_packet": qualification,
            "time.monotonic": lambda: self.elapsed, "time.sleep": sleep,
            "os.getpid": lambda: 4321, "os.getpgrp": lambda: 4321}
        for name, value in replacements.items():
            active = patch("gridgpu.rental_execution." + name, value)
            active.start()
            self.addCleanup(active.stop)
        return utc, qualification

    def test_full_actual_trial_chronology_restoration_and_archive(self):
        utc, qualification = self.full_composition()
        result = run_rental_trial(**self.arguments(clock=utc))
        self.assertTrue(result.restored)
        self.assertEqual(self.limit, 175)
        self.assertEqual([event for event in self.events if event[0] == "write"],
                         [("write", 125), ("write", 175)])
        starts = [event[1:] for event in self.events if event[0] == "start"]
        self.assertEqual(starts, [(p, r) for base in ("baseline", "capped", "restored")
            for p, r in [(base + "_warmup", -1)] + [(base, i) for i in range(3)]])
        payload = verify_trial_archive(self.run / "evidence.json")
        self.assertEqual(payload["outcome"]["status"], "completed_unqualified")
        self.assertEqual(len(payload["measurements"]), 45)
        samples = list((self.run / "samples").glob("sample-*.json"))
        self.assertEqual(len(samples), 45)
        self.assertTrue(payload["recovery_state"]["restored_observation"])
        self.assertEqual(qualification.call_count, 2)

    def test_full_actual_mid_capped_failure_drains_then_restores(self):
        utc, _ = self.full_composition(fail_capped=True)
        with self.assertRaisesRegex(RuntimeError, "failed safely"):
            run_rental_trial(**self.arguments(clock=utc))
        self.assertFalse(self.active)
        self.assertEqual(self.limit, 175)
        restore_index = self.events.index(("write", 175))
        abort_index = self.events.index(("abort", "capped"))
        self.assertLess(abort_index, restore_index)
        payload = verify_trial_archive(self.run / "evidence.json")
        self.assertEqual(payload["outcome"]["status"], "failed")
        self.assertTrue(payload["recovery_state"]["restored_observation"])
        self.assertGreater(len(payload["measurements"]), 0)
        self.assertEqual(len(list((self.run / "samples").glob("sample-*.json"))),
                         len(payload["measurements"]))


if __name__ == "__main__":
    unittest.main()
