# Architecture Assurance Review 0003

Date: 2026-08-30  
Reviewer: Independent Architecture Assurance Council  
Scope: Simulator Gate B after primary-trace, semantic-gate, manifest, and offline-verifier integration  
Authority: Chief Architect retains final authority

## Independent decisions

| Decision | Result | Boundary of the decision |
|---|---|---|
| Simulator Gate B | **GO** | The deterministic simulator release meets the Review 0002 Gate B closure criteria. This approves the simulator evidence milestone only. |
| Physical read-only shadow | **NO-GO** | P0-4 and site/provider Hardware Gate prerequisites remain open. Offline replay and an unprivileged read-only NVIDIA probe remain permissible engineering activities, but they are not a physical-shadow pilot. |
| Physical actuation | **NO-GO** | Not evaluated or authorized. No physical power-limit write implementation was found in the reviewed adapter. |

The simulator GO does not establish electrical accuracy, deployability at a site, utility-grade measurement, production workload safety, or authorization to connect to physical infrastructure.

## Verification performed

- Inspected the current gate predicates, standard and integrated fault trace producers, independent trace verifier, evidence packager, artifact manifest, release runner, offline verifier, supervisory harness, session/reconciler boundary, policy guard, NVIDIA adapter, alignment abstraction, and hardware checklist.
- Ran `python3 -m unittest discover -s tests -v`: **178 tests passed**.
- Produced a fresh official release with `run_gate_b_release` in `/private/tmp/review-0003-xy22u0rl/release`.
- Fresh release result: **GO**, 21 required/21 received, no reasons.
- Ran `verify_release_packet` using the retained packet: **valid**, offline gate evaluation **GO**, no verification reasons.
- Inspected the release packet: 51 source/test/spec files in the manifest, 21 retained raw scenario files, 23 audit records, and a final audited decision.
- Inspected representative standard, audit-failure, and optimizer-timeout raw files. Each retained its complete primary trace, verifier identity, independently derived metrics/facts, and a trace digest matching the verifier digest.

## Review 0002 closure audit

### P0-1 — Gate B accepted self-attested semantics: **CLOSED**

`ScenarioRequirement` now owns executable semantic predicates. The gate independently rejects, among other contradictions, zero fault count, nonzero forbidden effects, nonzero feasible-envelope exceedance, stale-meter decision eligibility, and a shortfall that does not match observed exceedance. Negative tests show that producer `passed=true` and all producer invariants set true cannot override contradictory metrics.

Required invariants must be present both as producer assertions and as independently verified trace facts bound to the same `primary_trace_digest`. The official release constructs its result metrics and facts from `verify_primary_trace`; it does not use benchmark producer `passed`, `metrics`, or `invariants`. The offline verifier repeats that derivation from retained raw traces before reevaluating Gate B.

The gate predicate definitions and trace-verifier source are included in the artifact snapshot; predicate IDs/descriptions are also serialized in the gate-requirement manifest.

### P0-2 — Release identity did not identify the artifact or inputs: **CLOSED for Simulator Gate B**

Official release callers can no longer substitute placeholder identities. The release creates a mandatory manifest containing path, size, and SHA-256 for product source, tests, and binding specifications, plus Python/runtime identity, scenario definitions, controller parameters, gate requirements, and the declared test command. Files are copied into the self-contained packet and verified offline. Actual primary-trace inputs/configuration are retained inside each trace and included in its digest.

Residual limitation: this is local build provenance, not a signed or reproducible-build attestation. The manifest snapshots files after modules have been loaded and scenarios run; it does not prove, against a hostile build host or concurrent source replacement, that the exact snapshotted bytes were those interpreted by Python. That limitation is acceptable for this local simulator milestone but remains material before partner or production reliance.

### P0-3 — Raw evidence contained summaries instead of primary traces: **CLOSED**

All 21 raw files now retain primary traces. Standard traces include scenario inputs, configuration, trace rows, mutation ledger, and raw facts. Fault traces include exact supervisory trace rows, injection and mutation ledgers, scenario inputs, session/audit evidence, cursor state, and workload before/after state.

`verify_primary_trace` recomputes the exact Gate B metrics and facts without reading producer pass claims or invariants. It fails closed on schema/identity mismatch, noncanonical or nonfinite values, missing/extra/reordered rows, discontinuous ledgers, duplicate/missing/unused injection, count contradictions, unexplained mutation, contradictory state, and scenario-specific trace tampering. The offline packet verifier re-runs it and compares the retained derivation and digest.

### P1-1 — Faults were isolated component demonstrations: **CLOSED for the simulator assurance boundary, with residual fidelity limits**

The official release no longer uses `fault_benchmarks` summaries as its evidence source. It uses integrated primary traces produced through a common `SupervisoryHarness` containing meter reconciliation and eligibility, session authorization, planning/fallback, independent policy validation, durable intent, scheduler/adapter boundaries, mutation observation, and safe hold. Boundary, audit, optimizer, meter, and protected-workload failures are exercised in that path, with independently reconciled injection and mutation ledgers.

Some special scenarios remain deterministic models rather than high-fidelity distributed-system simulations: split brain uses the lease-fence primitive before entering hold; manual conflict uses the precedence primitive; interrupted recovery drives explicit state transitions; dependency adapters are injected probes rather than real services. Their traces now honestly prove the modeled contract, but not real network/process concurrency. This is not a blocker for the simulator milestone; it is a required expansion before a physical or multi-process claim.

### P1-2 — Sequence protection was not integrated with execution: **CLOSED in the release supervisory path**

`SupervisoryHarness.run_cycle` assesses and accepts source sequence/epoch state before calling `ControlSession.authorize_execution`. Duplicate and regressed samples reach safe hold before authorization, and the retained cursor proves it did not advance. The official fault release exercises this path.

Residual API risk: `ControlSession.authorize_execution` itself still accepts a `MeterSnapshot` and can be called directly without a reconciler. Production architecture must make the supervisory facade mandatory or introduce a reconciled typed token so future callers cannot bypass sequence enforcement.

### P1-3 — Independent policy guard was not the simulator action gate: **PARTIALLY CLOSED; remains P1**

The integrated supervisory path now calls both controller validation and `FlexibilityPolicyGuard.validate_actions` with an authorization context before audit intent and mutation. The protected-mislabel trace demonstrates fail-closed behavior through that boundary.

However, the three stateful standard simulator scenarios still run `Simulator` with `HeuristicController.validate` as the direct action gate. Their primary traces therefore establish the deterministic simulator's controller bounds, not independent tenant/operator policy authorization. This does not invalidate their narrow envelope/rebound calculations or the present simulator Gate B, but it prevents claiming that one production-equivalent policy path has been tested end to end across every canonical scenario.

## Simulator Gate B basis

The five Review 0002 simulator closure conditions are satisfied:

1. P0-1 through P0-3 are closed.
2. Fault evidence is generated within the shared supervisory harness and retains boundary state and ledgers; remaining simplified fault models are explicitly bounded.
3. Gate predicates and trace-derived invariant verification are independent of producer booleans.
4. The release contains and hashes real source/runtime/scenario/configuration artifacts instead of placeholder labels.
5. A clean, self-contained packet independently verifies from disk and returns GO.

Accordingly, **Simulator Gate B is GO**. This decision should be invalidated and rerun whenever source, trace schema, verifier version, gate predicates, scenario definitions, controller configuration, or runtime changes.

## Physical read-only shadow decision

Physical read-only shadow remains **NO-GO**. Review 0002 P0-4 is not closed:

- `NvidiaSmiShadowAdapter` returns device values but still does not create a qualified `GpuPowerObservation` with collection/ingest timestamps, source epoch/sequence, host identity, GPU UUID binding, command/driver/executable provenance, and derived quality.
- No selected live host/PDU/provider meter collector is connected to the same host and interval as NVIDIA observations.
- The alignment API can compare caller-constructed observations, but construction is still the trust boundary; it does not establish provenance or identity binding.
- Alignment confidence still penalizes normal host-minus-GPU power as if it were measurement error, conflating temporal confidence with an expected physical-boundary delta.
- No exact provider permission, host/GPU/driver inventory, meter boundary/calibration, clock-synchronization result, security review, operator stop procedure, or signed site gate exists in the reviewed evidence.
- This environment supplied no real NVIDIA or independent-meter observation with which to validate the physical path.

Hardware Gate 3 describes shadow mode as requiring prior lab characterization. If the intent is to start with a strictly observation-only qualification exercise before an active lab, the chief architect and site owner should record a narrower Gate 0/1 read-only exception. It must still have no actuator credentials and must satisfy written permission, identity binding, provenance, clock, meter, security, data handling, and stop/runbook prerequisites. No such exception is granted by this review.

## Residual findings

### P0 — physical blocker

- **P0-4 remains open:** no end-to-end qualified GPU-plus-independent-meter observation path or site authorization exists.

### P1 — material before physical/partner use

- **P1-3 remains partially open:** standard simulator actions do not traverse the independent policy/authorization guard.
- **Sequence enforcement can be bypassed by API use:** `ControlSession.authorize_execution` does not require proof of reconciliation; production callers must be structurally unable to bypass the supervisory boundary.
- **Physical observation provenance/alignment remains inadequate:** close Review 0002 P1-4 with validated observation types and separate temporal confidence from the host-minus-GPU energy model.
- **Release trust remains local:** the packet is internally tamper-evident and offline-verifiable, but its unkeyed local chain and unsigned manifest can be coherently rebuilt by a host-level attacker. Add signed build provenance or an external transparency/attestation anchor before relying parties consume it.
- **Special fault fidelity:** exercise real multi-process lease contention, manual cancellation, service timeouts/rejections, and recovery interruption before claiming distributed-system or physical equivalence.
- **Site readiness remains unfulfilled:** all applicable permission, security, inventory, metering, time-sync, runbook, ownership, and signed checklist items remain open.

### P2 — hardening

- The standard trace verifier accepts extra top-level standard-packet fields while the integrated-fault verifier requires an exact schema. Version and validate both schemas consistently.
- The artifact discovery list is curated rather than generated from a dependency/SBOM graph; add dependency completeness and reproducible-build evidence.
- The release records the test command but does not retain a signed test transcript or execute the snapshotted artifact in a clean environment.
- NVIDIA executable ownership, symlink target, digest, driver version, and command provenance remain unverified.
- Empty reporting still represents zero observations as fully compliant.
- Provider-supplied meter provenance remains data inside the replay file rather than externally authenticated metadata.

## Final assurance statement

Review 0003 changes the Simulator Gate B decision from NO-GO to **GO** because the release now retains primary observations, independently recomputes scenario semantics, rejects contradictory evidence, identifies the code/configuration/runtime, audits the final decision, and verifies the complete packet offline. The result is meaningful for the deterministic simulator boundary described by the current scenarios.

Physical read-only shadow remains **NO-GO**. The missing qualified GPU-plus-meter collection path and unsigned site/provider prerequisites are independent of simulator quality and cannot be waived by a green Gate B packet. Physical writes and active pilot activity remain outside this decision.
