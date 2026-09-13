# Fixed CUDA workload implementation

Use `FixedCudaWorkload.start` and `.finish` as LiveReadOnlyCollector's workload
callbacks. The supervisor must call `.abort()` for telemetry or trial exceptions,
not only worker failures. Finish waits for and reaps the worker, binds ordered
outcomes to submitted IDs, and rejects failed, malformed or out-of-window results.
Worker failure permanently disables new submissions. Stop escalates termination
to kill and bounded reap; an unproven drain raises explicitly.

The worker uses a fixed all-ones FP32 matrix multiplication, fixed dimensions and
iteration count, checks every output element against the exact expected matrix
dimension, and synchronizes CUDA before recording job completion. This simple
known-answer workload tests execution and measurement plumbing; it does not
represent production training or inference. Warmup currently starts a separate
process, so CUDA initialization repeats for every window; compare identical
conditions and retain that overhead rather than claiming steady-state throughput.

The SHA-256 pins the worker script. Runtime identity, PyTorch/CUDA versions, matrix
dimensions, iterations and submitted IDs must also be bound in the approved trial
manifest; a script hash alone does not bind all those settings. Package import
does not import torch or run CUDA. The selected isolated Python environment must
already contain a compatible PyTorch/CUDA runtime; no installation is performed.

For the external POSIX controller supervisor, construct with
`supervised_process_group=os.getpgrp()` only in the controller group leader.
The worker then inherits that group and never spawns children. The parent watchdog
must kill/drain the entire group on controller death before any restoration.
Before importing torch, the Linux worker arms SIGKILL on controller death via
prctl and rechecks its parent PID to close the setup race. Other platforms fail
closed. This stops workload processes; it cannot restore GPU limits after the
entire supervisor chain is lost, so the unfinished journal requires reconciliation.
Default standalone mode starts a private session and is not controller-crash
safe without a separate external process tracker. Inherited-mode abort kills and
reaps the one worker PID; it does not kill its own controller group.

The parent incrementally bounds captured stdout/stderr to 64 KiB each and bounds
communication time. Cleanup reaps without buffering arbitrary output. This still
requires a trusted pinned worker, not an untrusted-code sandbox.
Python runtime/shared-library provenance and protection against executable
replacement remain deployment responsibilities. Actual driver hangs, SIGKILL,
kernel failures and server reboot must be qualified on the rental.

Primary API references: [CUDA synchronization](https://docs.pytorch.org/docs/main/generated/torch.cuda.synchronize.html)
waits for kernels across device streams; [deterministic algorithms](https://docs.pytorch.org/docs/main/generated/torch.use_deterministic_algorithms.html)
reject unsupported nondeterministic operations. [PyTorch reproducibility guidance](https://docs.pytorch.org/docs/stable/notes/randomness.html)
warns that reproducibility is not guaranteed across releases/platforms. These
references validate API intent, not this worker on any real GPU.
