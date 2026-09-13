# Runbook: first supervised NVIDIA rental test

Owner: GridRudder operator. Frequency: one approved attended experiment at a time.
Updated: 2026-09-13. Last physical run of this workflow: not yet performed.

## Purpose and limits

Qualify one dedicated Linux NVIDIA host, then compare the same fixed jobs at
original, lower, and restored power limits. This is not fleet or grid dispatch
validation. Local tests use simulated GPU/BMC output; harmless process tests
exercise actual termination. Linux kernel-specific tests must pass on the host.

The supervisor is a separate process, not an installed always-on service. A
controller failure triggers group termination and an attended recovery prompt.
Supervisor death uses Linux parent-death signaling to stop controller/worker;
it does NOT establish power restoration. Reboot, supervisor SIGKILL, uninterruptible
kernel tasks, or daemonized descendants require console intervention. Do not
intentionally test those cases in the first cap experiment.

## Prerequisites

- Explicit rental budget, cancellation terms, operator availability and console.
- Dedicated one-GPU Linux host; vendor permits root access and power-limit tests.
- NVIDIA power-limit reads AND writes supported. Root alone is insufficient.
- Root-owned non-group/world-writable pinned NVIDIA and IPMI executables.
- Whole-server BMC power telemetry with understood accuracy, caching/averaging,
  physical boundary, clock behavior, and sampling cadence. Polling frequency is
  not proof of measurement frequency. No whole-server meter means no energy trial.
- Isolated Python environment with CUDA-compatible PyTorch. Record exact versions.
- No unrelated workloads, daemonizing workers, or shared GPUs. Recoverable console.
- Private canonical owner-only run and approval directories, retained across restarts.

## Procedure

### 1. Validate software before touching GPU controls

From the exact reviewed source checkout:

```sh
python3 -m unittest discover -s tests -v
python3 -m gridgpu.rental_execution --help
```

Expected: tests pass, including Linux process tests on the rental host. No GPU
commands are executed by this suite. Failure: stop; do not bypass or alter gates.

### 2. Read-only host qualification

Prepare the host-specific JSON using `docs/read-only-qualification.schema.json`.
Use observed identities and an actual meter assessment, not guessed calibration.

```sh
python3 -m gridgpu.qualification_cli --config /absolute/private/qualification-config.json --output /absolute/private/qualification.json
```

Expected: exact GPU/chassis, acceptable alignment, current command hashes. Review
the packet AND provider metrology information. The `qualified` flag alone does
not prove calibration. Failure: stop the rental if access/capability is unsuitable;
do not relabel a GPU-only measurement as whole-server energy.

### 3. Calibrate fixed work without changing power

Review `gridgpu/cuda_workload_worker.py` and use `FixedCudaWorkload.start/finish`
under containment to determine a finite job count/matrix size/iteration count
that completes within the measured window at both limits with headroom. The
first attempt uses original power only. CUDA startup, result verification and
drain are included. A late job fails the trial; never move its timestamp backwards.
Early completion includes the idle tail in window energy; report it explicitly.
Freeze the recipe before approving the comparison. Do not tune after seeing savings.

### 4. Prepare and approve exact settings

The operator prepares `recipe.json` using `rental_execution.RECIPE_FIELDS`: pinned
worker path/hash, Python/NVIDIA/IPMI paths, job IDs, matrix size/iterations, meter
identity/boundary/epoch, qualification path/file hash and metrology review ID.
SHA-256 of the COMPLETE recipe is `PerformanceTrialConfig.workload_sha256`.
Qualification is checked before work and again before the cap; its default
maximum age is 900 seconds. Regenerate/reapprove if stale or changed.

Use `OperatorAuthorization.bind` for the exact config and `RecoveryIntent` with
the read-only observed original limit. `LocalApprovalAuthority.initialize()`
creates a key once in an existing mode-0700 directory. `issue_trial` signs config,
authorization and intent together. This is local-account HMAC trust, not remote
identity. Never erase key/nonce records to retry. Settings fields are exactly:
`config`, `authorization`, `intent`, `signed`, `authority_directory`,
`run_directory`, `recipe_path`. Run directory must be new and empty.

Expected: independently reviewed settings bound to this host and fixed workload.
Failure: do not sign incomplete/guessed settings. No default cap is provided.

### 5. Launch from the attended console

```sh
python3 -m gridgpu.rental_execution --settings /absolute/private/settings.json --execute-approved-trial
```

Type the exact displayed phrase. The parent feeds that bounded phrase to the
controller; do not invoke hidden controller flags manually. Total authorized
window plus cleanup margin must fit one hour. Baseline, capped and restored phases
run with warmups/repetitions. A durable intent precedes any cap command.

Expected: verified final original limit, closed journal, full evidence archive and
supervisor archive. Per-sample files are fsynced so controller death retains prior
completed observations. The in-flight sample may be absent; incomplete trials are
not valid savings evidence. Measurement includes evidence-export overhead.

### 6. Failure/recovery verification

On telemetry/worker failure, controller aborts and reaps work before restoration.
On controller loss, supervisor kills/drains its inherited group and requests a
fresh typed restoration phrase. It uses a separately signed, single-use approval
for the exact original limit. A failed drain, expired approval, missing/corrupt
journal, or mismatched readback means uncertain state, NOT success.

Expected: original limit independently observed by supervisor after recovery.
Never restart into a directory containing a journal. A closed journal is historical
evidence, not current device state or proof that another process is idle.

## Verification and shutdown

- Confirm exact GPU original limit and no active benchmark worker using console.
- Verify archive hashes with `trial_archive.verify_trial_archive`.
- Preserve sample, final, audit, recovery and supervisor files privately; they may
  contain host identities. Sanitize separately before any public publication.
- Compare correctness, completed work, energy and latency; include uncertainty,
  warmup/startup effects and idle tails. No claimed benefit is also a valid result.
- Export evidence BEFORE terminating rental; confirm billing cancellation.

## Troubleshooting / rollback

| Symptom | Required response |
|---|---|
| Power-limit or BMC access unsupported | Stop; do not bypass capability gates. |
| Job completes outside window | Reject result; drain; create a newly approved recipe. |
| Qualification stale/digest mismatch | No cap; recollect/review and approve new recipe. |
| Controller fails, supervisor alive | Use attended recovery prompt; verify readback. |
| Supervisor dies/reboot/unknown process state | Use provider console; establish idle state, inspect preserved intent, obtain fresh recovery authorization. No automatic restart. |
| Original limit cannot be verified | Treat as critical; stop testing and escalate to operator/provider. |

Rollback is restoration to the recorded original limit on the exact GPU, never a
guessed default. If the host cannot be controlled, isolate/stop the rental through
its console with provider assistance; preserve records and report uncertainty.

## History

2026-09-13: software composition and simulated hardware tests prepared. No physical
energy claim or production recovery certification follows from this runbook.
