# Attended physical power adapter: implementation boundary

`NvidiaSingleGpuPowerControl` implements the `performance_trial.PowerControl`
interface. It requires an explicit command runner, absolute pinned executable,
exact GPU UUID and one target. It is not wired into a CLI or autonomous controller.

The adapter reuses qualification executable ownership/mode/hash inspection before
and after commands. It rejects multi-GPU inventory and unsupported numeric
telemetry, screens temperature, compute mode and MIG, captures the original limit
once, and accepts only the selected lower cap or that captured original. It
retains completed command responses in memory. The runner has a fixed environment
and finite timeout; no sudo, remote transport, persistence mode, or shell exists.
After an attempted cap, restoration can be retried even when the cap timed out or
temperature screening fails. Readback mismatch is an error, not success.

## Remaining deployment gates

This is a Python command allowlist, **not OS-enforced least privilege**. Do not
give the benchmark process unrestricted root or a broad sudo nvidia-smi rule.
A trusted local broker must enforce the same exact UUID and two allowed limits.
The pinned-file check cannot eliminate the pathname execution TOCTOU race; trusted
parent directories, loader dependencies and an immutable executable deployment
are required. Provenance replacement blocks even restoration; the attended
operator needs an independent emergency restoration procedure.

`healthy` here means temperature/compute/MIG screening passed; it does not establish
absence of Xid, ECC, driver, workload, tenant or hardware faults. `N/A` MIG is
accepted for consumer devices without MIG; unsupported power/temperature is not.
The physical qualification must separately verify exclusive host ownership,
fault state, clock synchronization, meter/chassis identity and aligned readings.

Authenticated exact-trial approval, a durable nonce registry, audit-before-write,
the process lock and workload hash checks remain in the attended orchestration
boundary. Durable export of command responses and timestamped BMC/workload samples,
crash recovery, real hardware validation and architect approval remain required.
No experiment, hardware compatibility, savings or production-readiness claim is
supported by hardware-free tests of this adapter.
