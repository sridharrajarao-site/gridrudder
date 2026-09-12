# Architecture Assurance Review 0002

Date: 2026-08-30  
Reviewer: Independent Architecture Assurance Council  
Scope: Complete current project after the reported Gate B GO  
Authority: Chief Architect

## Independent decisions

| Decision | Result | Meaning |
|---|---|---|
| Mechanical Gate B evaluator | **GO reproduced** | The current release runner produced 21 uniquely named, formally complete result mappings and `evaluate_gate_b` returned GO. |
| Simulator Gate B, assurance judgment | **NO-GO** | The release gate primarily verifies producer-supplied booleans and field presence. Several fault scenarios assert containment without exercising an integrated control path, and the release does not bind the tested source artifact or retain the underlying traces. The reported GO is structurally valid but not yet sufficient evidence of the declared Gate B invariants. |
| Physical read-only shadow | **NO-GO** | The physical NVIDIA adapter is safely read-only, and meter replay/alignment are useful abstractions. However, there is no qualified NVIDIA observation pipeline into alignment, no live or provider-export meter implementation selected, no exact hardware/provider permission, and no synchronized physical evidence in this environment. Offline replay and `probe-nvidia` remain authorized; a physical shadow claim does not. |

This review does **not** authorize GPU power-limit writes. It found no physical write implementation in the current production modules.

## Verification performed

- Read all current source, tests, architecture/council documents, prior review, Gate B specification, hardware checklist, provider shortlist, and release-evidence documentation.
- Ran `python3 -m unittest discover -s tests -v`: **146 tests passed** during the final review run.
- Ran `python3 -m gridgpu benchmark`: all four standard benchmark results reported passed.
- Ran a fresh `run_gate_b_release` in a new empty directory: **21/21 received, GO, no reasons**.
- Inspected the generated decision, audit chain, and representative retained raw result (`audit_failure.json`).
- Ran `python3 -m gridgpu probe-nvidia`: no NVIDIA executable/hardware was present; capability correctly reported telemetry unavailable and writes false.
- Searched production and test code for power-limit paths. The only implementations are the simulated adapter and the physical shadow adapter that always raises `ReadOnlyAdapterError`.

## Why the mechanical GO is not an assurance GO

The release pipeline is internally consistent:

```text
scenario producer
  -> producer metrics/invariants
  -> canonical summary JSON
  -> local audit append
  -> Gate B schema/presence checks
  -> GO
```

The missing independent step is deriving the claimed invariants from retained primary observations at the gate boundary. `evaluate_gate_b` checks that required invariant names equal `True`; it does not independently evaluate metric thresholds or reconstruct facts from raw traces. The same scenario producer determines behavior, derives its invariants, declares `passed`, and supplies the evidence consumed by the gate.

This is particularly important for fault scenarios. For example:

- Meter loss calls `ControlSession.enter_safe_hold` directly rather than causing a running orchestration path to detect loss (`fault_benchmarks.py:104-126`).
- Scheduler and adapter failures exercise a standalone injected dependency probe with no scheduler, workload, command, or state mutation attached (`fault_benchmarks.py:145-164`).
- Audit failure triggers an injector and returns the labels `NO_MUTATION` and `intent_not_executed`; it does not invoke the real `AuditLog` or simulator transaction in the release scenario (`fault_benchmarks.py:167-172`). Separate unit tests exercise simulator audit failure, but those primary traces are not the release scenario evidence.
- Optimizer timeout constructs a `HeuristicController` and labels it selected; it neither runs fallback planning nor proves that a partial plan cannot execute (`fault_benchmarks.py:216-228`).
- Manual precedence and lease fencing test pure helpers, not the session/command path where a conflicting action would occur (`fault_benchmarks.py:203-213`).

These are valuable deterministic unit-contract tests. They are not yet end-to-end failure scenarios at the supervisory-controller boundary described by the Gate B specification.

## P0 — blocking findings

### P0-1: Gate B accepts self-attested semantics

Evidence:

- `gates.py` validates that `passed is True`, findings are empty, required metric names exist, values are finite, and required invariant names are exactly true.
- It does not enforce semantic predicates such as `maximum_exceedance_watts <= tolerance`, `accepted_fault_count == 0`, `unfenced_command_count == 0`, or `fault_count == 1`.
- `fault_benchmarks.py:309-406` derives metrics and invariants from its own safe-state enum and evidence strings. A scenario returning the expected labels becomes its own proof.

Impact: A producer bug can emit `passed=True`, required invariants true, and physically incorrect but finite metrics; the independent gate still returns GO. This defeats the gate's role as a separate decision boundary.

Required for Simulator Gate B:

- Put executable metric predicates and cross-field consistency rules in the gate requirement, independent of producers.
- Derive required invariants at the gate/evidence verifier from retained event traces, or verify producer assertions against those traces.
- Add negative release tests where every required field is present and true but metrics contradict the claim; these must return NO-GO.
- Version and hash the gate predicate set in the release evidence.

### P0-2: the default release identity does not identify the tested artifact or inputs

Evidence: When callers omit identities, `release.py:121-131` hashes generic labels such as `{"component":"gridgpu","gate":"B"}`, scenario-name lists, and required-ID lists. It does not hash the Python source, tests, runtime version, dependency manifest, actual scenario configuration, seeds, or fixture contents.

Impact: Two different codebases can produce the same `artifact_version`, `configuration_digest`, and `input_digest`. The evidence cannot establish what software actually received GO.

Required for Simulator Gate B:

- Make a real artifact manifest mandatory: path, size, and SHA-256 for every released source/test/spec file plus Python/runtime identity.
- Hash serialized scenario definitions, controller parameters, fixtures, seeds, Gate requirements, and test command.
- Reject placeholder/default identities in an official release.
- Include the manifest itself in retained and audited evidence.

### P0-3: “raw evidence” contains derived summaries, not the primary traces

Evidence: `evidence.py:205-215` writes only scenario ID, passed flag, findings, metrics, and invariant booleans. The inspected `audit_failure.json` contained two zero/one metrics and three true invariants, but no injected event, attempted operation, state transition, command history, exception, or audit failure trace.

Impact: An independent reviewer cannot recompute the result or distinguish observed containment from optimistic derivation. The raw file is canonical and hashed, but canonical hashing preserves whatever is supplied; it does not make a summary primary evidence.

Required for Simulator Gate B:

- Retain actual simulator audit rows, session events, fault injections/consumption, dependency calls, inputs, expected/observed states, and assertion calculations.
- Bind each result digest to its primary trace digest.
- Provide a replay verifier that recomputes metrics/invariants and fails on unused injections or unaccounted state changes.

### P0-4: no end-to-end qualified GPU-plus-meter physical observation path exists

Evidence:

- `NvidiaSmiShadowAdapter` returns `AcceleratorDevice` values without observation timestamp, ingestion timestamp, sequence/epoch, quality, host identity, or provenance (`nvml.py:76-166`).
- `GpuPowerObservation` has timestamps and quality, but no adapter converts NVIDIA output to it and quality defaults to GOOD (`alignment.py:12-18`).
- The meter implementation is file replay, not a selected live/BMC/PDU/provider export integration (`meter.py`).
- The current machine has no `nvidia-smi`, GPU, or physical meter data.

Impact: The pieces cannot yet prove that GPU and independent host/PDU readings came from the same machine and interval. Manually constructing a `GpuPowerObservation` would self-assert freshness and quality.

Required before physical read-only shadow:

- Implement a read-only NVIDIA observation collector that stamps collection/ingest times, source epoch/sequence, host identity, GPU UUID, command/driver provenance, and quality based on command outcome.
- Select and implement the exact independent meter export/replay format with immutable provider/device provenance.
- Bind host/meter/GPU identities and run the alignment pipeline from actual exports.
- Pass Hardware Gates 1 and 2 read-only prerequisites with written provider/site permission.

## P1 — material residual risks

### P1-1: fault tests are component demonstrations, not integrated supervisory failures

The release matrix covers every required fault ID, but most scenarios do not run a common orchestration loop with meter ingest, session authorization, policy guard, planner, audit intent, adapter/scheduler action, observation, and recovery. Consequently, the tests do not demonstrate atomic containment across boundaries.

Required: Create a deterministic supervisory harness that executes the same flow for normal and faulted cases, inject faults at named boundaries, records all state mutations, and asserts no post-fault command/state change except the approved safe-state transition.

### P1-2: replay/sequence protection is not integrated into execution authorization

`ControlSession.authorize_execution` checks stateless meter eligibility (`session.py:368-421`) but does not consume a `SourceSequenceReconciler`. Sequence replay/regression is tested separately in the fault matrix. A fresh, GOOD duplicate sample may authorize a different execution ID if the caller bypasses an external reconciler.

Required: Make reconciled/epoch-qualified meter ingestion a mandatory typed input to authorization, or have the session own sequence reconciliation.

### P1-3: independent workload policy is not the simulator's action gate

`FlexibilityPolicyGuard` has useful tenant/operator/event checks, but the simulator calls `HeuristicController.validate` directly. The planner therefore still validates its own output in the canonical simulator path, and the stronger independent policy/authorization context is not exercised by standard benchmarks.

Required: Route action plans through the independent guard with a versioned authorization context before intent recording/mutation, and retain its decision as primary evidence.

### P1-4: meter alignment trusts construction and uses a questionable confidence model

`align_power_signals` checks time awareness, age, quality, GPU finiteness, coverage, skew, and latency, which is a useful abstraction. However:

- It does not re-run authoritative-source, unit, clock-sync, range, or sequence checks on arbitrary `MeterObservation` objects; it assumes they came through replay validation.
- `GpuPowerObservation` has no construction validation or provenance and defaults to GOOD.
- Confidence penalizes the absolute difference between whole-host/PDU power and GPU-board power (`alignment.py:162-169`). That difference normally includes CPU, memory, PSU losses, fans, and cooling and is not measurement error. A valid physical boundary can therefore appear low-confidence for the wrong reason.

Required: Accept only validated/provenanced observation types, add GPU provenance/sequence validation, and separate temporal alignment confidence from the expected host-minus-GPU power model.

### P1-5: release evidence is tamper-evident only within the local, unanchored packet

Positive: canonical JSON, exclusive creation, `fsync`, raw digests, hash-chained audit, and overwrite/traversal protections are implemented and tested.

Residual limitations:

- The unkeyed audit can be rebuilt by an attacker able to rewrite the directory, and clean tail deletion is not locally detectable; documentation acknowledges this.
- Default actors are strings, not authenticated identities.
- The final `gate-b-decision.json` is written after the last audit record and is not itself appended, signed, or externally anchored.
- Per-scenario `audit_head_hash` values are historical intermediate heads; the final decision carries the final head, but no independent verifier command validates the entire packet and all raw digests from disk.

Required before partner reliance: append/hash the final decision, produce an offline packet verifier, sign or externally anchor the final head, and bind actors to authenticated build/service identities.

### P1-6: the physical shadow deployment gates have not been satisfied

No evidence shows exact host/GPU/driver inventory, provider permission, independent meter boundary, time-sync validation, security/data-flow review, operator runbook, or hardware-gate signatures. This is an external readiness gap even if the software abstractions are improved.

## P2 — hardening and clarity

### P2-1: NVIDIA executable provenance remains unverified

An explicit executable path is run without checking ownership, mode, package/file digest, or symlink target (`nvml.py:89-93,123-135`). It is invoked without a shell, which is good. Keep the probe unprivileged; pin and record executable/driver provenance for evidence.

### P2-2: empty reporting remains “100% compliant”

`reporting.py` returns compliance ratio 1.0 for no samples. Gate scenarios separately require sample evidence in important cases, but downstream callers can still mistake absent data for perfect compliance. Prefer unavailable/invalid plus a coverage requirement.

### P2-3: meter replay provenance is supplied by the replay file

`physical_boundary`, `meter_id`, and `source_system` are required, but they are strings inside the file being evaluated. Preserve the original provider export, hash it before parsing, and bind provenance from deployment configuration or a signed manifest rather than trusting only record contents.

### P2-4: release decision portability and retention

Raw references are absolute paths. Moving the evidence packet makes references stale even though the files remain valid. Prefer paths relative to a packet root plus a manifest digest.

### P2-5: no physical observation was possible in this environment

`probe-nvidia` correctly failed closed because `nvidia-smi` was absent. This is not a code defect, but it means this review cannot validate real driver output, board bounds, timestamp cadence, provider permissions, or independent meter accuracy.

## Positive findings

- **No physical write path found.** `NvidiaSmiShadowAdapter.set_power_limit` always raises, and `probe-nvidia` reports `power_limit_writable=false`. No production command invokes `nvidia-smi -pl` or `--power-limit`.
- Physical/facility controls remain explicitly outside scope. The generic adapter write is implemented only by the in-memory simulated adapter.
- Domain and plan validation now reject malformed identities, duplicate/conflicting actions, non-finite values, invalid bounds, and invalid simulator configuration.
- The simulator records interval power before completion mutation and has intent/outcome audit handling with rollback tests.
- Explicit shortfall evidence is materially better than inferring infeasibility from an exceedance.
- Telemetry unit normalization, freshness, source identity, clock state, and sequence/epoch primitives fail closed in their tested boundaries.
- Session reconstruction is conservative: execution commands are not replayed and operator resume is required.
- Meter replay is read-only, retains physical-boundary metadata, and rejects stale/bad/duplicate/reordered evidence in its tests.
- Alignment rejects absent, stale, misaligned, low-coverage, and excessive-latency evidence.
- Evidence packaging resists path traversal, overwrite, symlink-target creation, NaN/infinity, and duplicate result IDs.
- The project remains standard-library-only and deterministic in the reviewed test suite.

## Closure criteria

### Simulator Gate B may pass when

1. P0-1 through P0-3 are closed.
2. Required fault scenarios run through a shared supervisory harness rather than asserting safe-state labels at isolated helper boundaries.
3. Gate predicates independently evaluate metric thresholds and recompute invariants from retained primary traces.
4. The release binds actual code/runtime/scenario artifacts and records those manifests.
5. A clean release packet can be independently verified from disk and still returns GO.

### Physical read-only shadow may begin when

1. P0-4 is closed and the exact NVIDIA/meter collectors feed the alignment path.
2. P1-2, P1-4, and P1-6 are closed for the selected site.
3. The deployed artifact provably contains no physical write implementation or credentials and runs unprivileged.
4. Provider/site permission, exact inventory, meter boundary, clock synchronization, operator stop procedure, and data handling are documented.
5. Initial mode is observation-only; no workload, scheduler, GPU cap, or facility state can be changed.

Offline replay of provider/meter files and read-only `probe-nvidia` discovery do not require this physical-shadow authorization, provided results are labeled engineering observations rather than dispatch or flexible-capacity proof.

## Final assurance statement

The project has advanced substantially since Review 0001: the code is safer, validation is stronger, simulator audit semantics are improved, the fault catalog is complete by ID, and release packaging is disciplined. The reported Gate B GO is reproducible.

Nevertheless, assurance depends on what was actually proved, not merely on a green evaluator. Today the gate accepts producer-derived true/false assertions and hashes summaries that are not primary traces, under a default artifact identity that does not identify the code. Therefore Simulator Gate B remains **NO-GO** under independent assurance review.

Physical read-only shadow also remains **NO-GO** until actual, qualified GPU and independent meter observations are integrated and the site-specific hardware gates are signed. The absence of a physical write path is necessary and verified; it is not by itself sufficient to authorize a physical shadow claim.
