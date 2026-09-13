"""Bounded subprocess lifecycle for an explicitly requested fixed CUDA workload."""
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import selectors
import subprocess
import time

from .workload_benchmark import JobOutcome


class CudaWorkloadError(RuntimeError):
    pass


def bounded_communicate(process, timeout):
    deadline = time.monotonic() + timeout
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    with selectors.DefaultSelector() as selector:
        for name in chunks:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("CUDA worker", timeout)
            for key, _ in selector.select(min(remaining, 0.1)):
                block = os.read(key.fileobj.fileno(), 4096)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                chunks[key.data].extend(block)
                if len(chunks[key.data]) > 65536:
                    raise CudaWorkloadError("worker output exceeds bounded capture")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    return tuple(bytes(chunks[name]).decode("utf-8", errors="strict") for name in ("stdout", "stderr"))


def _close_pipes(process):
    for name in ("stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None:
            stream.close()


def stop_process_group(process, grace_seconds=2.0):
    """Stop the private session and reap its leader; failure is never drain proof."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace_seconds)
            # The worker never spawns children. Also kill any unexpected survivors.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _close_pipes(process)
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            raise CudaWorkloadError("worker process group still exists; drain unproven")
        except subprocess.TimeoutExpired:
            continue
    raise CudaWorkloadError("worker could not be reaped; drain is unproven")


def stop_worker(process):
    for action in (process.terminate, process.kill):
        if process.poll() is None:
            action()
        try:
            process.wait(timeout=2.0)
            _close_pipes(process)
            return
        except subprocess.TimeoutExpired:
            continue
    raise CudaWorkloadError("worker could not be reaped; drain is unproven")


class FixedCudaWorkload:
    def __init__(self, *, python_executable: Path, worker_path: Path, worker_sha256: str,
                 gpu_uuid: str, matrix_size: int = 512, iterations: int = 10,
                 popen=subprocess.Popen, stopper=None, monotonic=time.monotonic,
                 supervised_process_group=None, communicator=bounded_communicate):
        if (not gpu_uuid.startswith("GPU-") or type(matrix_size) is not int or not 16 <= matrix_size <= 4096 or
                type(iterations) is not int or not 1 <= iterations <= 10000):
            raise ValueError("invalid GPU or fixed workload configuration")
        self.python = Path(python_executable)
        if not self.python.is_absolute() or not self.python.is_file():
            raise ValueError("absolute Python runtime required")
        self.worker, self.sha = Path(worker_path), worker_sha256
        self.gpu_uuid, self.size, self.iterations = gpu_uuid, matrix_size, iterations
        if supervised_process_group is not None and (supervised_process_group != os.getpgrp() or
                supervised_process_group != os.getpid()):
            raise ValueError("supervised worker requires the current controller group leader")
        self._inherit_group = supervised_process_group is not None
        self._popen, self._mono = popen, monotonic
        self._communicate = communicator
        self._stopper = stopper or (stop_worker if self._inherit_group else stop_process_group)
        self._process = None
        self._request = None
        self._origin = None
        self._failed = False
        self.last_metadata = None
        self._check_worker()

    def _check_worker(self):
        if (not self.worker.is_absolute() or self.worker.is_symlink() or not self.worker.is_file() or
                hashlib.sha256(self.worker.read_bytes()).hexdigest() != self.sha):
            raise CudaWorkloadError("worker artifact does not match pinned hash")

    def start(self, request, origin):
        if self._failed or self._process is not None:
            raise CudaWorkloadError("workload active or failed; no new submissions")
        self._check_worker()
        ids = request.expected_job_ids
        now = self._mono()
        if (not 1 <= len(ids) <= 64 or len(set(ids)) != len(ids) or
                any(not isinstance(i, str) or not 1 <= len(i) <= 128 for i in ids) or
                any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (origin, request.duration_seconds, request.deadline_monotonic)) or
                type(now) not in (int, float) or not math.isfinite(now) or now < origin or
                request.duration_seconds <= 0 or request.deadline_monotonic <= now):
            raise CudaWorkloadError("invalid job manifest or expired deadline")
        self._submitted_at = now
        self._request, self._origin = request, origin
        specification = dict(job_ids=ids, matrix_size=self.size, iterations=self.iterations,
                             origin=origin, deadline=request.deadline_monotonic, parent_pid=os.getpid())
        env = {"PATH": "/usr/bin:/bin", "CUDA_VISIBLE_DEVICES": self.gpu_uuid,
               "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "PYTHONNOUSERSITE": "1"}
        try:
            self._process = self._popen((str(self.python), "-I", str(self.worker), "--request",
                json.dumps(specification, allow_nan=False)), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=not self._inherit_group, env=env)
        except BaseException:
            self._failed = True
            raise

    def abort(self):
        """Must be called by the supervisor on telemetry/trial failure, too."""
        self._failed = True
        if self._process is not None:
            self._stopper(self._process)
            self._process = None

    def require_idle(self):
        """Prove this adapter has no unreaped worker before power restoration."""
        if self._process is not None:
            raise CudaWorkloadError("workload worker remains active or unreaped; drain is unproven")

    def finish(self, request, origin):
        if self._process is None or request != self._request or origin != self._origin:
            self.abort()
            raise CudaWorkloadError("completion does not bind active submission")
        try:
            now = self._mono()
            if type(now) not in (int, float) or not math.isfinite(now) or now < self._submitted_at:
                raise CudaWorkloadError("workload clock regressed or invalid")
            remaining = request.deadline_monotonic - now
            if remaining <= 0:
                raise CudaWorkloadError("workload deadline expired")
            stdout, stderr = self._communicate(self._process, remaining)
            finished = self._mono()
            if (type(finished) not in (int, float) or not math.isfinite(finished) or
                    finished < now or finished > request.deadline_monotonic):
                raise CudaWorkloadError("workload completion exceeded deadline")
            if self._process.returncode != 0:
                raise CudaWorkloadError("CUDA worker exited unsuccessfully")
            if len(stdout) > 65536 or len(stderr) > 65536:
                raise CudaWorkloadError("worker response exceeds evidence bound")
            self._check_worker()
            result = json.loads(stdout)
            if result.get("schema") != "gridrudder-fixed-cuda-v1":
                raise CudaWorkloadError("unknown worker result schema")
            jobs = tuple(JobOutcome(**row) for row in result["jobs"])
            if tuple(job.job_id for job in jobs) != request.expected_job_ids:
                raise CudaWorkloadError("worker outcomes do not match ordered submitted IDs")
            for job in jobs:
                if (job.succeeded is not True or
                        not all(type(v) in (int, float) and math.isfinite(v)
                                for v in (job.started_seconds, job.finished_seconds)) or
                        not 0 <= job.started_seconds < job.finished_seconds <= request.duration_seconds):
                    raise CudaWorkloadError("worker result failed verification or exceeded measured window")
            self.last_metadata = dict(worker_sha256=self.sha, gpu_uuid=self.gpu_uuid,
                matrix_size=self.size, iterations=self.iterations, torch_version=result.get("torch_version"))
            _close_pipes(self._process)
            self._process = None
            return jobs
        except BaseException:
            self.abort()
            raise
