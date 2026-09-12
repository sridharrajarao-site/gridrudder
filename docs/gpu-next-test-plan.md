# Next GPU test execution plan

Status: **NO-GO for another write today. GO for read-only qualification.**

## Objective

Measure whether a bounded NVIDIA GPU power cap reduces independently measured server energy while preserving useful workload throughput, and prove restoration, repeatability, and evidence integrity.

## Work now, without touching the rental

1. Implement a narrowly scoped physical adapter for the reviewed `performance_trial` boundary.
2. Pin absolute `nvidia-smi` and meter executables by regular-file identity, ownership, mode, and SHA-256; revalidate around collection and actuation.
3. Parse one exact GPU UUID and its supported power-limit range, driver, health, ECC/throttle state, and MIG mode.
4. Bind meter samples to acquired BMC chassis/serial identity, source, timestamps, and stable sensor name.
5. Add a signed, expiring, one-use authorization document bound to host, GPU, workload digest, cap, meter, repetitions, and time window.
6. Package one deterministic workload that reports useful units, duration, errors, and digest.
7. Add adapter failure tests for partial command success, timeout, stale meter, identity drift, executable replacement, workload mutation, and failed restoration observation.

## Read-only rental qualification

No power-limit write occurs in this phase.

1. Confirm the server is still active and record its current billing state.
2. Rotate any credential that appeared in interactive history.
3. Record OS, physical-host evidence, NVIDIA inventory, driver, GPU UUID, power range, MIG, health, and throttling state.
4. Record BMC/DCMI identity and at least 60 seconds of timestamped power samples.
5. Verify GPU and meter clocks can be aligned and the BMC source remains stable.
6. Run the packaged workload at the unchanged original limit and retain useful-work plus meter evidence.

Failure of identity, provenance, health, meter freshness, clock alignment, or workload digest ends qualification without actuation.

## Attended write sequence after architect GO

1. Two or more baseline repetitions after warmup.
2. One conservative cap step inside the device/provider-approved range.
3. Two or more capped repetitions with the identical workload artifact.
4. Immediate restoration of the original cap in every exit path.
5. Post-restore health, power-limit, workload-digest, and meter verification.
6. Independent report of throughput, average host watts, host joules/useful-unit, variance, errors, and all limitations.

## Pass conditions

- Original limit is restored and observable.
- No health, workload, audit, identity, or telemetry stop condition fires.
- Baseline and capped windows are comparable and repeated.
- Useful-work impact and energy impact are both reported; utilization is not used as a proxy for throughput.
- The complete primary evidence can be independently recomputed.

## After the test

Preserve a private evidence packet, create a separately sanitized derivative if authorized, rotate credentials again, and terminate the rental unless the architect explicitly approves another scheduled experiment.
