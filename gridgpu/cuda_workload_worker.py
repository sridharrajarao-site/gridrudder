"""Isolated fixed CUDA workload worker. Importing does not import torch."""
import argparse
import json
import math
import os
import signal
import sys
import time


def arm_parent_death(expected_parent_pid):
    """Linux worker dies if its controller dies, including the setup race."""
    if sys.platform != "linux" or type(expected_parent_pid) is not int or expected_parent_pid <= 1:
        raise RuntimeError("Linux and an exact live controller PID required")
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise RuntimeError("cannot arm worker parent-death signal")
    if os.getppid() != expected_parent_pid:
        raise RuntimeError("controller vanished before worker parent-death protection")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = json.loads(parser.parse_args().request)
    arm_parent_death(args["parent_pid"])
    ids, size, repeats = args["job_ids"], args["matrix_size"], args["iterations"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 64 or
            any(not isinstance(i, str) or not 1 <= len(i) <= 128 for i in ids) or
            len(set(ids)) != len(ids) or type(size) is not int or not 16 <= size <= 4096 or
            type(repeats) is not int or not 1 <= repeats <= 10000):
        raise ValueError("invalid fixed workload specification")
    origin, deadline = args["origin"], args["deadline"]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (origin, deadline)):
        raise ValueError("invalid workload clock bounds")
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("one visible CUDA GPU required")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    rows = []
    for job_id in ids:
        if time.monotonic() >= deadline:
            raise TimeoutError("workload deadline expired")
        started = time.monotonic() - origin
        a = torch.ones((size, size), device="cuda", dtype=torch.float32)
        b = torch.ones_like(a)
        torch.cuda.synchronize()
        for _ in range(repeats):
            if time.monotonic() >= deadline:
                raise TimeoutError("workload deadline expired")
            product = torch.mm(a, b)
        torch.cuda.synchronize()
        verified = bool(torch.all(product == float(size)).item())
        torch.cuda.synchronize()
        rows.append(dict(job_id=job_id, started_seconds=started,
                         finished_seconds=time.monotonic() - origin, succeeded=verified))
        if not verified:
            raise RuntimeError("CUDA output failed exact known-result verification")
    print(json.dumps({"schema": "gridrudder-fixed-cuda-v1", "jobs": rows,
                      "torch_version": torch.__version__}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
