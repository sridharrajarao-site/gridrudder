from dataclasses import replace
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gridgpu.cuda_workload import FixedCudaWorkload, CudaWorkloadError, stop_worker, bounded_communicate
from gridgpu.measurement_collection import CollectionRequest
from gridgpu import cuda_workload_worker


class FakeProcess:
    def __init__(self):
        self.returncode = 0
        self.timeout = False
        self.output = json.dumps(dict(schema="gridrudder-fixed-cuda-v1", torch_version="fixture",
            jobs=[dict(job_id="one", started_seconds=1, finished_seconds=2, succeeded=True)]))

    def communicate(self, timeout):
        if self.timeout:
            raise subprocess.TimeoutExpired("fixture", timeout)
        return self.output, ""


class CudaWorkloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve() / "worker.py"
        self.path.write_text("fixture never executed")
        self.process = FakeProcess()
        self.kwargs = None
        self.stops = []
        self.request = CollectionRequest("baseline", 0, 10, ("one",), 12)
        self.work = self.make()

    def make(self, **extra):
        return FixedCudaWorkload(python_executable=Path(sys.executable).resolve(),
            worker_path=self.path, worker_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
            gpu_uuid="GPU-abcd", popen=self.spawn, stopper=lambda p: self.stops.append(p),
            monotonic=lambda: 0, communicator=lambda p, timeout: p.communicate(timeout=timeout), **extra)

    def spawn(self, argv, **kwargs):
        self.kwargs = kwargs
        self.assertEqual(argv[1], "-I")
        self.assertEqual(json.loads(argv[-1])["job_ids"], ["one"])
        return self.process

    def test_complete_verified_job_and_isolated_process(self):
        self.work.start(self.request, 0)
        jobs = self.work.finish(self.request, 0)
        self.assertTrue(jobs[0].succeeded)
        self.assertTrue(self.kwargs["start_new_session"])
        self.assertEqual(self.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "GPU-abcd")
        self.assertEqual(self.stops, [])
        self.work.require_idle()

    def test_timeout_drains_and_prevents_resubmission(self):
        self.work.start(self.request, 0)
        self.process.timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.work.finish(self.request, 0)
        self.assertEqual(self.stops, [self.process])
        with self.assertRaises(CudaWorkloadError):
            self.work.start(replace(self.request, repetition=1), 0)

    def test_nonzero_and_malformed_output_drain(self):
        for bad in ("nonzero", "malformed", "missing", "failed", "late"):
            self.setUp()
            self.work.start(self.request, 0)
            if bad == "nonzero":
                self.process.returncode = 1
            elif bad == "malformed":
                self.process.output = "invalid"
            else:
                value = json.loads(self.process.output)
                if bad == "missing":
                    value["jobs"] = []
                elif bad == "failed":
                    value["jobs"][0]["succeeded"] = False
                else:
                    value["jobs"][0]["finished_seconds"] = 11
                self.process.output = json.dumps(value)
            with self.assertRaises((CudaWorkloadError, ValueError)):
                self.work.finish(self.request, 0)
            self.assertEqual(self.stops, [self.process])

    def test_changed_artifact_blocks_start(self):
        self.path.write_text("replaced")
        with self.assertRaisesRegex(CudaWorkloadError, "hash"):
            self.work.start(self.request, 0)
        self.assertIsNone(self.kwargs)

    def test_external_telemetry_failure_abort_drains(self):
        self.work.start(self.request, 0)
        with self.assertRaisesRegex(CudaWorkloadError, "unreaped"):
            self.work.require_idle()
        self.work.abort()
        self.assertEqual(self.stops, [self.process])
        self.work.require_idle()

    def test_supervised_worker_inherits_controller_group(self):
        with patch("gridgpu.cuda_workload.os.getpgrp", return_value=123), patch("gridgpu.cuda_workload.os.getpid", return_value=123):
            work = self.make(supervised_process_group=123)
        work.start(self.request, 0)
        self.assertFalse(self.kwargs["start_new_session"])

    def test_wrong_supervised_group_rejected(self):
        with self.assertRaisesRegex(ValueError, "group leader"):
            self.make(supervised_process_group=-1)

    def test_failed_drain_is_explicit(self):
        self.work.start(self.request, 0)
        def unproven(_):
            raise CudaWorkloadError("drain unproven")
        self.work._stopper = unproven
        with self.assertRaisesRegex(CudaWorkloadError, "unproven"):
            self.work.abort()
        self.assertIsNotNone(self.work._process)
        with self.assertRaises(CudaWorkloadError):
            self.work.require_idle()

    def test_stop_worker_escalates_and_reaps(self):
        class Process:
            def __init__(self):
                self.events = []
            def poll(self):
                return None
            def terminate(self):
                self.events.append("terminate")
            def kill(self):
                self.events.append("kill")
            def wait(self, timeout):
                self.events.append("wait")
                if "kill" not in self.events:
                    raise subprocess.TimeoutExpired("fixture", timeout)
                return "", ""
        process = Process()
        stop_worker(process)
        self.assertEqual(process.events, ["terminate", "wait", "kill", "wait"])

    def test_bounded_capture_cpu_only(self):
        process = subprocess.Popen((sys.executable, "-c", "print('fixture')"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(bounded_communicate(process, 5), ("fixture\n", ""))
        finally:
            stop_worker(process)

    def test_excess_output_rejected_cpu_only(self):
        process = subprocess.Popen((sys.executable, "-c", "print('x' * 70000)"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(CudaWorkloadError, "bounded capture"):
                bounded_communicate(process, 5)
        finally:
            stop_worker(process)

    def test_invalid_clock_bounds_reject_spawn(self):
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(CudaWorkloadError):
                self.work.start(replace(self.request, deadline_monotonic=value), 0)
        self.assertIsNone(self.kwargs)

    def test_worker_algorithm_with_mock_torch_no_cuda(self):
        events = []
        fake = SimpleNamespace(__version__="mock-only", float32="float32",
            cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1,
                                 synchronize=lambda: events.append("synchronize")),
            backends=SimpleNamespace(cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
                                     cudnn=SimpleNamespace(allow_tf32=True)),
            use_deterministic_algorithms=lambda enabled: events.append(("deterministic", enabled)),
            ones=lambda *a, **k: "matrix", ones_like=lambda _: "matrix",
            mm=lambda *a: 16.0,
            all=lambda value: SimpleNamespace(item=lambda: value))
        spec = dict(job_ids=["one"], matrix_size=16, iterations=1, origin=0, deadline=10, parent_pid=123)
        output = io.StringIO()
        with patch.object(cuda_workload_worker, "arm_parent_death") as armed, \
                patch.dict(sys.modules, {"torch": fake}), patch.object(sys, "argv",
                ["worker", "--request", json.dumps(spec)]), patch.object(cuda_workload_worker.time,
                "monotonic", side_effect=[1, 1.1, 1.2, 1.3]), redirect_stdout(output):
            cuda_workload_worker.main()
        result = json.loads(output.getvalue())
        armed.assert_called_once_with(123)
        self.assertTrue(result["jobs"][0]["succeeded"])
        self.assertEqual(events.count("synchronize"), 3)
        self.assertIn(("deterministic", True), events)
