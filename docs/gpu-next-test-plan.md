# Next GPU test execution plan

Status: **Prepare locally before renting again. Hardware writes remain NO-GO until the adapter and workload are reviewed.**

## Local progress (2026-09-12)

The injected, hardware-free performance runner now collects repeated baseline,
capped, and restored useful-work windows. Each window reports throughput,
trapezoid-integrated whole-server joules, average watts, and joules per useful
unit. It verifies the restored cap before restored workload collection and
reasserts the original cap in cleanup, including when restored collection fails.
Non-finite cap observations and elapsed meter times fail closed. Authorization
expiry and the workload digest are rechecked immediately before lowering the cap.
These are tested software behaviors, not a new physical experiment or proof of
efficiency. The runner's authorization callback still needs a real verifier.

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

1. Only rent after the local checklist is complete; record rate and a planned termination time.
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
5. Restore, warm up, and collect the same number of unchanged-power useful-work windows; then reassert and verify the original cap. Post-restore health checks remain an adapter requirement.
6. Independent report of throughput, average host watts, host joules/useful-unit, variance, errors, and all limitations.

## Pass conditions

- Original limit is restored and observable.
- No health, workload, audit, identity, or telemetry stop condition fires.
- Baseline and capped windows are comparable and repeated.
- Useful-work impact and energy impact are both reported; utilization is not used as a proxy for throughput.
- The complete primary evidence can be independently recomputed.

## Focused next experiment and report

Use one fixed-input workload whose completed, validated jobs can be counted.
Keep input, batch size, precision, software versions, and warmup identical.
Start with three 60-second windows per phase after 30-second warmups. Configure
the signed authorization window to cover the complete session. These timings
are a starting protocol; qualification must show that the meter cadence is
sufficient and temperatures have settled before approving the final protocol.

For each phase publish completed jobs, elapsed seconds, jobs/second, whole-server
joules, joules/completed job, error count, and per-job latency percentiles if the
workload records them. Compute aggregate throughput as total jobs / total time
and aggregate energy intensity as total joules / total jobs, not an unweighted
average of ratios. Report all individual windows and variability. Do not mix
GPU-board energy with whole-server energy. Compare restored throughput and energy
against baseline to expose drift; a fixed baseline/capped/restored sequence alone
does not eliminate temperature or time-order effects. Repeat full cycles before
claiming a repeatable effect. The current WorkSample interface does not yet
carry job validation, errors, or latency samples; that integration remains open.

## Remaining prerequisites before paying for another session

- Reviewed physical control adapter with pinned executables, range/health checks,
  bounded command timeouts, and independently verified restoration.
- Real signed authorization verifier and durable one-use nonce handling; the
  injected callback and advisory lock are not a complete security boundary.
- Packaged deterministic workload with synchronized GPU timing and validated
  completed-job counts; latency/error evidence and stop conditions.
- Meter/workload acquisition integration, freshness and clock-alignment checks,
  and recomputable persisted primary evidence (including failed attempts).
- Failure tests of those real adapters using fake processes before deployment.
- One scheduled attended session with a confirmed compatible meter, price,
  export location, stop time, and termination plan.

## After the test

Preserve a private evidence packet, create a separately sanitized derivative if authorized, rotate credentials again, and terminate the rental unless the architect explicitly approves another scheduled experiment.
