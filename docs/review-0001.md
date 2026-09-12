# Architecture Assurance Review 0001

Date: 2026-08-30  
Review type: Read-only code and test review  
Scope: Current simulator, controller, telemetry, NVIDIA shadow adapter, audit, reporting, benchmarks, and CLI  
Decision authority: Chief Architect

## Decision

| Gate | Decision | Rationale |
|---|---|---|
| Gate A — architecture ready for implementation | **PASS, simulator scope only** | ADR-0001 and the council documents establish a supervisory-only boundary, protected-by-default workloads, authoritative meter requirement, deterministic control, no physical writes, and architect authority. Implementation may continue within that boundary. |
| Simulator Gate B | **NO-GO** | The current canonical suite passes, but Gate B requires more than the four happy/edge scenarios presently exercised. A kW/W unit error can admit an invalid power reading, decision/infeasibility evidence is incomplete, and enumerated failure outcomes are not injected or proven. |
| Physical shadow testing | **NO-GO** | There is no independent host/PDU meter adapter or time-alignment path, and the NVIDIA probe does not emit quality/freshness-qualified observations. Read-only physical probing by a developer is acceptable; it must not be represented as a shadow power-validation pilot. |

The code is appropriately incapable of physical GPU writes today. No finding calls for relaxing that safeguard.

## Evidence reviewed

- All Python source under `gridgpu/`.
- All tests under `tests/`.
- `README.md`, `docs/ADR-0001-mvp-architecture.md`, assurance council boundaries, and hardware gate checklist.
- `python3 -m unittest discover -s tests -v`: **41 tests passed**.
- `python3 -m gridgpu benchmark`: all four canonical scenarios reported passed.

Passing tests demonstrate the cases implemented; they do not satisfy the broader Gate B fault matrix.

## P0 — gate blockers

### P0-1: kW telemetry is compared against watt bounds without conversion

Evidence: `gridgpu/telemetry.py:119-135` explicitly accepts both `W` and `kW`, then compares the raw numeric value directly with `MeterSnapshot.minimum_watts` and `maximum_watts`.

Impact: A `100 kW` sample is treated as numeric `100` against watt-based limits. It can be accepted as if it were `100 W`, corrupting envelope decisions and shadow reports by a factor of 1,000. This violates the authoritative-meter invariant.

Required before Gate B:

- Normalize all accepted units to one canonical unit before range checks and consumption.
- Alternatively accept only `W` in the MVP and reject every other unit.
- Add boundary tests proving `1 kW == 1,000 W`, including min/max enforcement.

### P0-2: no independent host/PDU meter ingestion exists

Evidence: `gridgpu/nvml.py` queries only NVIDIA board telemetry. `gridgpu/telemetry.py` defines validation primitives but no physical meter adapter or ingest/time-alignment flow connects them to the NVIDIA probe, CLI, reports, or audit.

Impact: ADR-0001 requires NVML plus an independent host/PDU meter for a physical test. The current program can show GPU telemetry but cannot observe whole-host AC power, identify the physical measurement boundary, or compare aligned signals. A “shadow” run would therefore test only GPU discovery, not grid-to-GPU response.

Required before physical shadow:

- Implement a read-only adapter for the selected physical meter/PDU using its documented interface.
- Include source identity, units, sample time, ingest time/latency, sequence, quality, and clock-sync state.
- Align and export independent-meter and GPU samples without substituting one for the other.
- Test stale, missing, duplicated, reordered, and conflicting readings.

### P0-3: physical shadow telemetry is not decision/evidence qualified

Evidence: `gridgpu/nvml.py:21-125` returns instantaneous values without timestamps, monotonic sequence, quality, ingest latency, or device/host binding beyond the reported UUID. `gridgpu/__main__.py:50-56` prints these values directly. The fail-closed checks in `telemetry.py` are not used by this path.

Impact: A physical observation cannot demonstrate freshness, ordering, synchronized time, or whether GPU and independent meter data refer to the same interval and host. Stale or replayed readings could look current in an evidence packet.

Required before physical shadow:

- Wrap probe results in qualified telemetry records with collection and ingestion times.
- Record exact executable/driver identity, host alias, GPU UUID, command outcome, and quality.
- Fail the shadow evidence run when either required signal is stale, unbound, unsynchronized, or missing.

## P1 — must resolve before active physical work; selected items block Gate B

### P1-1: simulator records interval power after advancing/completing workloads

Evidence: `gridgpu/simulator.py:94-105` advances each workload before recording the sample for that second. `Workload.advance()` can change state to `completed`, causing `power_watts()` to return zero immediately (`domain.py:41-52`).

Impact: A workload that consumed power during a simulated interval can disappear before that interval's sample is recorded. Compliance and energy-over-limit calculations can undercount consumption, especially near completion boundaries.

Required: Define tick semantics explicitly—sample/integrate the power applied during the interval, then advance state—and add completion-boundary energy tests.

### P1-2: durable audit occurs after mutation and does not cover every decision

Evidence: The simulator mutates the cap at `simulator.py:86` and only then calls `_record`; `_record` first appends in memory and subsequently attempts durable append (`simulator.py:35-52`). When the controller recommends no action or cannot meet an envelope, no decision or explicit shortfall record is written.

Impact: An audit write failure can leave state changed without durable evidence. Gate B/ADR-0001 require every decision and action to have a complete record, including infeasible requests. Current tests prove samples/actions are persisted when storage succeeds, not safe behavior when it fails.

Required before Gate B:

- Record proposed plan, validation result, no-action decision, infeasibility/shortfall, approval (when applicable), command intent, result, and recovery.
- Define and test audit-write failure behavior. Simulation must not silently continue with divergent state/evidence.
- For future actuation, persist intent before execution and outcome afterward, with an independently guarded action path.

### P1-3: domain input permits invalid and ambiguous configurations

Evidence: `domain.py` dataclasses and `Simulator.__init__` perform no validation for blank IDs, duplicate workload IDs, non-finite/negative power, zero/negative GPU count, negative work, invalid arrival time, invalid flexibility minimum, negative overhead/cooling, empty envelopes, duplicate envelope times, or zero/negative control interval. `Simulator.__init__:24` silently collapses duplicate IDs into a dictionary.

Impact: A duplicate identifier can silently replace a workload, including a protected one. NaN values can bypass ordered comparisons; zero interval causes division/modulo failure; negative values produce physically meaningless results. Invalid fixtures can falsely pass compliance calculations.

Required before Gate B: Validate every configuration at construction, reject duplicate identity, require finite values and physically meaningful ranges, and add adversarial/property-style tests.

### P1-4: action validation is not total or independently isolated

Evidence: `controller.py:64-76` indexes the workload dictionary before validating identity and assumes `action.value` is a well-behaved finite number. Unknown IDs raise `KeyError`, and NaN compares neither less nor greater and can pass the bound checks. The same controller object both recommends and validates its own actions.

Impact: Malformed or compromised plans can crash validation or inject NaN into simulated power. The architecture calls for independent plan validation.

Required before Gate B:

- Make validation total: reject unknown IDs, non-finite values, invalid types, duplicate/conflicting actions, and invalid transitions as explicit safety violations.
- Move the policy guard behind an interface independent of the recommending controller.
- Fuzz/action-table test every rejected transition.

### P1-5: sequence validation is stateless

Evidence: `telemetry.py:115-116` only checks that `monotonic_sequence` is non-negative. It does not retain the last sequence per source, detect duplicates, or reject regressions.

Impact: A replayed or out-of-order but otherwise fresh sample is decision-eligible. This contradicts the monotonic-sequence field's purpose and the shadow checklist.

Required before physical shadow: Add a source-scoped ingest/reconciliation component that enforces monotonic progression and defines restart/epoch behavior.

### P1-6: the benchmark does not explicitly detect infeasibility

Evidence: `benchmarks.py:152-174` calls infeasibility “detected” whenever the final summary contains an exceedance. No controller or simulator event declares requested, available, and shortfall watts.

Impact: Observing that the model missed the limit is not the promised fail-safe behavior of calculating and reporting shortfall. Operators cannot distinguish known infeasibility from controller failure.

Required before Gate B: Emit an explicit shortfall result with reason and protected constraints; test magnitude and audit evidence.

### P1-7: the Gate B fault matrix is largely untested

Evidence: Canonical scenarios cover a feasible constraint, an infeasible constraint, recovery, and one stale-meter sample. There are no injected optimizer errors, audit failures, meter loss mid-event, scheduler/adapter/database outage, network duplication/reordering, clock jump, restart, split brain, conflicting action, or malformed configuration tests.

Impact: The assurance council requires the specified safe result for every enumerated fault. The current suite cannot justify Gate B despite its 41 passing tests.

Required before Gate B: Build a deterministic fault-injection matrix and make the benchmark command fail if any required scenario is absent or fails.

### P1-8: audit integrity is local and identity is self-asserted

Evidence: `audit.py` correctly documents that tail deletion is undetectable without an external head anchor. It accepts arbitrary non-empty actor/timestamp strings and uses an unkeyed hash chain. Anyone able to rewrite the complete file can rebuild a valid chain.

Impact: This is useful corruption evidence but not yet an immutable security audit. A compromised process or filesystem writer can forge history or remove the tail.

Required before a partner pilot: Bind actors to authenticated service/operator identity, validate timestamps at ingress, restrict permissions, anchor/sign chain heads externally, and test restore/retention behavior. This does not block simulator development if evidence is labeled accordingly.

## P2 — hardening and clarity

### P2-1: shadow adapter accepts semantically invalid numeric values

Evidence: `nvml.py:_optional_float` parses floats but does not reject NaN/infinity, negative power, utilization outside 0–100, inconsistent min/default/max bounds, blank names, or duplicate GPU IDs.

Impact: Malformed driver output can be presented as valid capability/telemetry. Duplicate IDs create ambiguous target identity.

Recommendation: Add semantic validation and duplicate detection; downgrade the entire observation to BAD/unsupported rather than partially trusting it.

### P2-2: capability probing executes an arbitrary configured path without provenance

Evidence: `nvml.py:56-60` accepts an explicit path without checking file ownership, mode, symlink resolution, or expected binary identity, then executes it at `:97`.

Impact: In a privileged future agent, configuration/path compromise could execute an attacker-controlled program. The current CLI should remain unprivileged and read-only.

Recommendation: Use a pinned absolute executable path, record hash/package provenance, reject unsafe ownership/mode, run with a minimal environment, and never run the shadow agent as root.

### P2-3: simulation lifecycle is not explicit

Evidence: `Simulator.run()` appends to existing audit/state but restarts its local `second` counter at zero each call. No guard says an instance is single-use.

Impact: Reusing a simulator produces repeated timestamps against mutated state and can invalidate replay/evidence assumptions.

Recommendation: Make the simulator explicitly single-run or retain a monotonic simulation clock and define reset semantics.

### P2-4: reporting treats an empty sample set as fully compliant

Evidence: `reporting.py:27` returns compliance ratio 1.0 when there are no samples.

Impact: A failed or empty observation period can look perfectly compliant unless callers separately check sample count.

Recommendation: Represent compliance as unavailable/invalid when evidence is absent, or require minimum coverage in every pass decision.

### P2-5: no automated quality gates beyond unit execution

Evidence: Repository evidence contains a standard-library unittest suite but no visible release manifest, pinned build provenance, static/type checks, coverage threshold, secret scan, SBOM, or CI configuration in review scope.

Impact: Regressions and artifact substitution are harder to prevent or reconstruct.

Recommendation: Add reproducible CI, compile/type/static checks appropriate to the standard-library constraint, artifact hashes, and a release evidence manifest before partner deployment.

## Positive findings

- The physical NVIDIA adapter is deliberately read-only and its `set_power_limit` always raises (`nvml.py:127-131`). Tests assert this boundary.
- Subprocess execution uses an argument sequence and `shell=False` behavior, avoiding shell interpolation.
- The controller protects critical/default-inflexible workloads in the covered scenarios.
- The authoritative-meter validator fails closed for stale, future-dated, bad-quality, wrong-source, unsynchronized, non-finite, negative, and excessive-latency samples in current tests.
- Audit records use canonical JSON, chained SHA-256 hashes, durable flush/fsync, and cooperative POSIX locking; tests detect modification, middle deletion, reorder, and incomplete-tail corruption.
- Canonical scenarios and simulator replay are deterministic for the tested inputs.
- The architecture correctly separates GPU telemetry from authoritative facility power and explicitly prohibits physical automatic actuation.

## Required closure plan

### To pass simulator Gate B

All of the following are required:

1. Close P0-1.
2. Close P1-1 through P1-7.
3. Add explicit tests for invalid/non-finite domain inputs and action plans.
4. Add the council's deterministic failure-injection matrix.
5. Demonstrate complete audit reconstruction for decisions, shortfalls, actions, and outcomes, including audit failure.
6. Re-run the full suite and canonical benchmark from a version-identified artifact.

P1-8 may remain as a documented simulator limitation if the audit is not described as adversary-proof or immutable.

### To begin physical shadow testing

In addition to Gate B or an architect-approved shadow-only exception:

1. Close P0-2 and P0-3.
2. Close P1-5 and the relevant parts of P1-8.
3. Close P2-1.
4. Pass Hardware Gates 1 and 2 in read-only mode with the exact host, GPU, driver, and independent meter.
5. Demonstrate that no physical write path or write credential exists in the deployed shadow artifact.
6. Label results as engineering observations, not dispatch, settlement, or flexible-capacity proof.

## Final assurance statement

Gate A passes because the chosen architecture is conservative, coherent, and appropriately narrow. Simulator Gate B does not pass because current successful tests do not establish the architecture's declared safety and evidence invariants under malformed data and faults. Physical shadow testing is also a no-go until a qualified independent meter path is implemented and synchronized with the read-only NVIDIA observations.

The correct next step is not to enable GPU writes. It is to close the telemetry-unit defect, make decision/audit/failure semantics explicit, and build the independent read-only measurement path.
