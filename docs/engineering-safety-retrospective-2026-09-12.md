# Engineering and safety retrospective — 2026-09-12

Scope: evidence available in this repository after the first rented-server
experiment. This is an engineering ledger, not a Hardware Gate authorization.
The Chief Architect owns the final gate decision.

## Evidence rule

`Verified` means reproducible from retained code/tests or a hash-chained local
artifact. `Reported` means stated during the operating session but not fully
reproducible from repository evidence. `Open` means required work remains.

## Delivery and miss ledger

| Area | Intended or claimed outcome | Status | Repository evidence / miss |
|---|---|---|---|
| Architecture | Supervisory grid-to-GPU control; protected-by-default workloads; no facility writes | Verified for modeled scope | `ADR-0001`, policy guard, session and supervisor tests. Production physical adapter remains intentionally absent. |
| Simulator | Deterministic envelope control and recovery | Verified | Canonical traces and independent verifier cover four standard scenarios. |
| Fault coverage | Audit, dependency, telemetry, split-brain, manual precedence, restart and protected-workload failures fail safe | Verified for deterministic models | Seventeen fault scenarios plus semantic trace verification. Review 0003 explicitly says this is not real distributed-process fidelity. |
| Simulator Gate B | GO | Verified for simulator only | Review 0003 and release/offline-verifier tests. It does not authorize shadow operation or physical actuation. |
| Read-only NVIDIA path | Qualified GPU telemetry with executable provenance | Verified locally in hardware-free tests | `gpu_observer.py`; no retained real-server qualified observation packet. |
| Independent meter path | Fresh, ordered, authoritative meter data and GPU/meter alignment | Partially verified | Replay and alignment logic are tested. No retained integrated, qualified real-server shadow packet closes Review 0003 P0. |
| Rental procurement | Dedicated RTX 2060-class server, root and BMC access | Reported | No vendor order, host inventory, invoice, lifecycle, or termination record is stored here. Current rental/billing state is unknown from local evidence. |
| Physical host identity | Bare metal/no hypervisor | Reported | Session statement only; physical trial artifact does not bind DMI/board/chassis identity. |
| Physical cap actuation | Lowered one GPU from 175 W to 125 W and restored it | Verified as retained operator evidence, not independently replayable | `artifacts/physical-trial-2026-09-12.jsonl` records intent/completion and `restored=true`. It contains no raw command transcript or restoration observation. |
| Physical power response | GPU and server watts fell under cap | Verified only as two recorded observations | Artifact records GPU 156.22→124.37 W and host 291→260 W. Earlier conversational numbers 155→125 and 282→266 are inconsistent with this retained artifact and must not be used as canonical evidence. |
| Useful-work performance | Quantify throughput and joules/useful-unit at baseline versus cap | Open physically; implemented hardware-free | `performance_trial.py` now defines warmup, repeated windows, timestamped multi-sample energy integration and restoration. No real run has populated it. The first experiment cannot establish performance impact or energy efficiency. |
| Workload identity | Same executable/workload in both phases | Closed locally, open physically | Hardened path hashes a regular non-symlink workload artifact before and after the run. No workload hash exists in the first physical artifact. |
| Authorization | Exact host/GPU/action/workload/chassis binding, expiry, nonce and attended confirmation | Closed in boundary contract, open in credential implementation | Hardened path binds these fields and rejects reused nonce in its audit log. A cryptographically authenticated `verify_authorization` implementation and durable cross-log nonce registry remain absent. |
| Audit before mutation | Durable intent before a GPU write | Verified in local tests; incomplete in first physical proof | Hash-chain audit fsync and fail-closed tests exist. First artifact contains intent, but no external head anchor; tail deletion remains possible. |
| Restoration | Original state restored on success/failure and restoration failure is critical | Verified in hardware-free fault tests | Both legacy and performance seams test partial mutation, restore failure and unobservable restoration. First physical artifact lacks raw post-restore telemetry. |
| Mutual exclusion | One writer per exact host/GPU | Closed for hardened performance path | Non-blocking host/GPU advisory lock is tested. It cannot fence unrelated tools or administrators; OS-level least privilege remains required. |
| GPU preflight | Exact UUID, unique inventory, healthy device, MIG-safe, multi-GPU-safe | Closed as injected contract, open in physical adapter | Hardened path rejects duplicate/missing UUID, unhealthy status and MIG. A pinned physical collector supplying these facts remains to be built. |
| Executable provenance | Pin root-owned `nvidia-smi`/meter executable and detect replacement | Partially closed | Read-only observer hashes and pins `nvidia-smi`; hardened performance contract records a supplied executable hash. No approved physical write adapter reuses it yet. `ipmitool` provenance remains open. |
| Chassis/meter identity | Power samples belong to the authorized independent chassis boundary | Closed as evidence validation, open at acquisition | Every benchmark sample must retain one authorized source and chassis ID. A physical BMC adapter must obtain/verify those identities rather than accepting caller labels. |
| Legacy direct actuator | Prevent weaker path bypassing stronger controls | Closed at supported CLI | `python -m gridgpu hardware-trial` exits before audit or mutation. `hardware_lab.run_hardware_trial` remains only as a deprecated historical test seam and must not be imported by deployment code. |
| Tests | All local tests green | Verified | 203 tests pass after hardening. Earlier “186/186” was true only for an earlier repository state and is not the current count. Hardware-free tests do not prove vendor/hardware behavior. |
| Open source | Apache-2.0/open-core recommendation and repository licensing | Verified as project decision | `LICENSE`, `NOTICE`, and `open-source-strategy.md`. Trademark, contributor governance, release provenance and secret scan still gate a public release. |
| Design partners | Supervised trial materials | Drafted, not executed | Intake and pilot documents exist. No retained partner approval, deployment, or result. |
| Website/domain | New public website and domain | Outside this engineering evidence ledger | Site source exists, but deployment, DNS ownership and registration must be evidenced by the website/procurement track. |

## Remaining physical P0/P1 gates

1. Build one narrowly scoped physical adapter that pins and verifies root-owned
   NVIDIA and BMC executables, obtains real host/chassis/GPU identities, records
   raw responses, and exposes only the hardened attended interfaces.
2. Implement authenticated approvals (signed manifest or trusted local verifier)
   and a durable nonce registry independent of a caller-selected audit file.
3. Run a read-only qualified shadow collection first and close Review 0003's
   physical-alignment blocker.
4. Have the Chief Architect approve the exact host, workload hash, target,
   minimum limit, duration, meter boundary, rollback and stop conditions.
5. Run the performance protocol attended; retain raw baseline/capped/restored
   samples, workload output, command acknowledgements, executable provenance,
   audit chain and an externally anchored final hash.
6. Verify rental termination and final billing separately after evidence is
   copied and integrity-checked.

Until these gates close, permissible claims are limited to a simulator Gate B
GO and one measured, attended single-server cap experiment. Production,
autonomous, fleet-wide, savings, workload-safety and universal-compatibility
claims remain unsupported.
