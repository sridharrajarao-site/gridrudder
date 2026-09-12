# Assurance Council Charter and MVP Boundaries

Status: Initial council position for architect review  
Scope: Simulator-first grid-to-GPU power-envelope controller  
Authority: The Chief Architect has final decision authority. Any exception to a MUST requirement below requires a written architecture decision record (ADR) naming the owner, rationale, compensating controls, expiration date, and rollback plan.

## 1. Council decision

The Reliability Engineer, Security Engineer, Test Engineer, Field Engineer, and Technical Product Manager agree that the first product must be a **supervisory, bounded controller**, not a safety system and not an electrical protection system.

Its initial promise is:

> Given a declared cluster power ceiling or simulated dispatch request, recommend and then execute only pre-authorized compute actions, keep protected workloads within their stated service constraints, measure the result, and restore capacity without an unsafe rebound.

The MVP may control simulator workloads and, later, a small isolated GPU test cluster. It must not directly control utility breakers, protective relays, switchgear, generators, UPS transfer logic, batteries, pumps, chillers, or other safety-critical facility equipment. Facility integrations are read-only until a separately approved production phase.

Council non-negotiables:

1. Local hardware and facility protections always outrank this service.
2. Loss of the orchestrator must not stop critical workloads or leave equipment in an undefined state.
3. Every actuation must be authenticated, authorized, bounded, attributable, and reversible.
4. Recommendations and automatic actions must use deterministic policy and optimization code; an LLM must not be in the control loop.
5. Claims are based on meter-observed behavior, not scheduler intent or GPU telemetry alone.
6. The product starts human-approved. Automatic dispatch is earned through staged evidence.
7. No pilot is allowed until rollback and kill paths work independently of the primary controller.

## 2. Responsibility boundaries

### Product controls

The MVP may:

- Accept a power ceiling, event duration, ramp limit, and recovery limit.
- Observe simulated meter, GPU, host, job, queue, and checkpoint telemetry.
- Classify jobs using operator-supplied flexibility policies.
- Hold or release queued jobs.
- Recommend or apply bounded GPU power caps where supported.
- Pause and resume only explicitly opted-in, checkpoint-safe test workloads.
- Produce an immutable event record and an operator-readable report.

The MVP must not:

- Infer that an unlabeled workload is interruptible. Unknown means protected.
- modify firmware, overclock hardware, bypass vendor limits, or disable thermal controls.
- Promise utility settlement accuracy before the baseline and meter path are independently validated.
- Claim availability, savings, carbon reduction, or flexible MW beyond measured pilot evidence.
- Become a required dependency for workload execution. Critical jobs must continue if it is unavailable.
- Initiate cross-site migration, utility market bids, or autonomous facility-equipment control.

### System boundary

The trusted control plane contains policy evaluation, optimization, command authorization, actuation adapters, telemetry normalization, audit logging, and operator approval. Kubernetes, Slurm, NVML/vendor tooling, meters, facility systems, identity providers, and grid-signal sources are external dependencies and must be treated as potentially stale, unavailable, misconfigured, or compromised.

## 3. Threat model

### Assets to protect

- Workload availability, confidentiality, integrity, priorities, and deadlines.
- GPU and host health.
- Site power-envelope and ramp-rate commitments.
- Control credentials, signing keys, API tokens, and operator identity.
- Telemetry, audit records, baselines, and verification reports.
- Tenant isolation and commercially sensitive job metadata.
- Operator trust and the ability to regain manual control.

### Adversaries and failure actors

- An external attacker reaching an exposed API or supply-chain dependency.
- A malicious or compromised tenant attempting to mark another tenant's work flexible.
- A compromised operator account or insider abusing dispatch privileges.
- A spoofed grid signal or replayed valid command.
- A compromised scheduler, node agent, meter gateway, or telemetry producer.
- Accidental operator error, bad policy, clock drift, malformed input, and software defects.
- Resource exhaustion, denial of service, dependency outage, network partition, and certificate expiry.

### Principal abuse cases

| Abuse or fault | Required mitigation |
|---|---|
| Forged or replayed dispatch | Mutual authentication, signed requests where available, nonce/event ID, timestamp window, idempotency, source allowlist |
| Unauthorized workload interruption | Deny-by-default policy, tenant-scoped RBAC, protected-job default, two-person approval for policy expansion |
| Excessive or unsafe power cap | Adapter-enforced vendor minimum/maximum, configured per-device floor, rate limit, duration limit, local expiry |
| Telemetry poisoning | Source identity, schema/range checks, freshness checks, redundant observations, confidence flag; inhibit actuation on disagreement |
| Audit tampering | Append-only signed/hash-chained events, separate retention path, restricted deletion, time synchronization |
| Credential theft | Short-lived workload identity, secrets manager, rotation, no secrets in logs or images, break-glass procedure |
| Control-plane compromise | Network segmentation, least privilege, signed artifacts, pinned dependencies, SBOM, isolated actuator identity |
| Multi-tenant data leak | Store minimal metadata, tenant isolation, encrypted transit/storage, redact reports and logs |
| Command storm or oscillation | Global/per-adapter rate limits, monotonic event state machine, hysteresis, cooldown, one active controller lease |
| Compromised adapter | Narrow action API, sandboxed process/container, allowlisted targets, egress restriction, independent watchdog |

### Security acceptance baseline

Before any external pilot, the system must have documented data flows, asset inventory, least-privilege roles, mutual TLS or equivalent for service communication, encrypted secrets, immutable audit records, dependency and container scanning, an SBOM, vulnerability triage, backup/restore testing, and an incident-response runbook. Internet exposure is forbidden unless explicitly approved by the architect and protected by strong identity, rate limiting, monitoring, and a penetration test.

## 4. Fail-safe and control behavior

### Safe state

For the simulator, safe state means no new automatic action, preservation of critical jobs, retention of the last valid evidence, and an operator alert.

For physical GPU tests, safe state means:

- Stop issuing new scheduling or power-cap actions.
- Never kill, pause, or evict protected workloads.
- Let vendor, host, and facility safety controllers remain authoritative.
- Expire temporary controls according to a declared policy: either retain an explicitly safe cap or restore a validated default gradually. The choice is site-specific and must be approved before deployment.
- Require operator confirmation before resuming automatic control after an integrity or safety fault.

There is no universal safe GPU power value. The field configuration must specify permitted bounds and restoration behavior for every hardware type.

### Mandatory interlocks

- Stale critical telemetry, clock uncertainty, meter disagreement, lost controller lease, or ambiguous workload policy inhibits new actuation.
- Every event has maximum magnitude, maximum duration, ramp-down rate, ramp-up rate, and cooldown.
- A site-level ceiling and hardware-specific bounds cannot be overridden by optimization output.
- The optimizer proposes actions; an independent policy guard validates them before an adapter can execute them.
- Each command has a unique ID, expiry, desired state, reason, actor, and rollback/recovery instruction.
- Adapter commands are idempotent and their observed result is reconciled with desired state.
- Only one controller holds an active site lease. Split-brain behavior is tested.
- Emergency stop is locally available, documented, access-controlled, and independent of the normal control path.
- Recovery is staged and observes a separate rebound ceiling.

### Failure response matrix

| Failure | Controller response |
|---|---|
| Meter missing/stale | Freeze new actuation; keep or expire existing actions per approved site policy; alert |
| Scheduler unavailable | Do not pause or start jobs; power-cap actions only if independently authorized and observable |
| GPU telemetry missing | Exclude affected device from new actions; treat its consumption conservatively |
| Optimizer timeout/error | Use no-action fallback, never an unreviewed partial plan |
| Database/audit sink unavailable | Reject new automatic events; manual observation may continue |
| Network partition | Actuator obeys local command expiry and bounds; central system marks result unverifiable |
| Control-plane restart | Reconstruct state from audit log and observed systems; no automatic replay of expired commands |
| Conflicting manual action | Manual/site control wins; automatic event cancels and records conflict |
| Target cannot be met | Protect workloads and equipment; report shortfall rather than exceeding approved actions |

## 5. Observability and evidence

Telemetry must use a common monotonic event timeline plus synchronized wall-clock time. Sources must expose timestamp, collection time, source identity, quality/freshness, units, and relevant target identifiers.

### Required signals

- Meter/site or simulated aggregate real power, target ceiling, baseline, and delivered reduction.
- Per-host and per-GPU power, utilization, temperature, power cap, and throttling reason where available.
- Workload identity alias, tenant, priority, flexibility class, deadline/SLO, checkpoint state, and lifecycle state.
- Controller decisions, rejected alternatives, constraints, predicted impact, approvals, commands, acknowledgements, and observed effects.
- Adapter, queue, database, clock, certificate, and controller-lease health.
- Inference latency/error rate or training progress for protected workloads.

### Minimum dashboards and alerts

- Actual power versus target, error band, ramp rate, remaining event duration, and telemetry confidence.
- Available flexibility by action type and workload class.
- Protected workload health and current/predicted SLO risk.
- Commands pending, applied, failed, expired, and rolled back.
- Recovery/rebound progress.
- Data freshness, missing series, clock skew, and adapter/controller health.

Page or inhibit automation on: target breach, protected-workload SLO breach, telemetry staleness, command failure, split-brain/lease loss, audit-write failure, abnormal thermal signal, unexpected device count, credential/certificate expiry, and recovery overshoot.

### Evidence retention

Every test and event report must include configuration version, software/artifact version, policy version, input signal, baseline method, action timeline, measured response, workload impact, failures, operator actions, and raw-data reference. Retention and deletion periods are pilot-contract decisions; reports must minimize tenant data.

## 6. Testing strategy

Testing proceeds from deterministic models toward hazardous reality. No later layer may compensate for an unpassed earlier gate.

### Level 0: Static and unit assurance

- Unit, schema, property, boundary, and numerical-stability tests.
- Policy guard tests for every prohibited transition and device bound.
- Deterministic optimizer tests with fixed seeds and reproducible fixtures.
- Authentication/authorization, tenant-isolation, replay, expiry, idempotency, and audit tests.
- Dependency, secret, license, container, and infrastructure-as-code scanning.

### Level 1: Simulator

- Nominal load follow, overload, ramp, event extension/cancel, and recovery.
- Heterogeneous GPUs, non-linear power/performance, cooling lag, measurement noise, and missing telemetry.
- Protected, flexible, unknown, and misclassified workloads.
- Scheduler/meter/adapter/database failures, packet loss, delay, duplication, reordering, clock skew, restart, and split brain.
- Property-based invariants: protected jobs are never interrupted; bounds are never exceeded; expired commands are never applied; recovery ceiling is respected.
- Monte Carlo scenarios and worst-case/adversarial traces.

Initial simulator acceptance target, subject to architect ratification:

- For feasible events, remain within ±5% of requested power target after the declared settling window for at least 95% of controlled intervals.
- Zero protected-workload interruption caused by the controller.
- Zero policy-bound or hardware-bound violations.
- Zero uncontrolled rebound; recovery remains within its configured ceiling.
- Complete, internally consistent audit record for 100% of actions.
- Correct fail-safe outcome for every enumerated injected failure.

These are engineering thresholds, not utility-settlement claims.

### Level 2: Software/hardware-in-the-loop

- Real scheduler API and actuator adapter against emulated jobs/devices.
- Meter and telemetry gateway protocol emulation.
- Network partitions, stale data, expired credentials, version mismatch, and rollback.
- Load and soak testing at 10x expected event/telemetry volume.
- Upgrade/downgrade and backup/restore tests.

### Level 3: Isolated physical GPU lab

- One GPU, then multiple GPUs, with validated host/PDU measurement.
- Characterize power-cap-to-meter response and workload throughput across allowed bounds.
- Verify thermal behavior, vendor-limit enforcement, job admission, checkpoint/resume, gradual recovery, emergency stop, controller loss, and machine restart.
- Run supervised only; no production tenant work.

### Level 4: Shadow pilot

- Observe a partner environment and generate recommendations without actuation.
- Compare predicted versus measured power, workload states, and counterfactual actions.
- Resolve telemetry gaps and site-specific safe-state policy.
- Complete security, operations, data, liability, and change-management reviews.

### Level 5: Limited active pilot

- Small, explicitly bounded capacity; opted-in noncritical workloads only.
- Human approval per event, staffed monitoring, maintenance window, and tested rollback.
- Start with admission control and bounded GPU caps; checkpoint/pause requires a separate gate.
- Increase magnitude only after evidence review and architect/site approval.

## 7. Pilot deployment constraints

Pilot prerequisites:

- Named executive sponsor, site operations owner, workload owner, security owner, and incident commander.
- Written scope, success metrics, maximum power/action bounds, test window, excluded systems, data handling, liability, and stop criteria.
- Approved network/data-flow diagram and exact inventory of targets.
- Dedicated service identities, staging environment, version-pinned adapters, configuration review, and signed release artifact.
- Independent meter or PDU reference adequate for engineering validation.
- Protected workload and opted-in flexible workload lists, with unknown workloads protected.
- Validated manual override, emergency stop, restore procedure, and contact tree.
- No write access to facility electrical or cooling controls.
- Change freeze during controlled events except incident response.
- Operator training and tabletop exercise completed.
- Rollback tested from the exact release and configuration used by the pilot.

Deployment should default to an on-premises or site-local control component with outbound-only central connectivity where practical. Latency-sensitive enforcement and command expiry remain local. Cloud loss must not compromise site safety or protected workloads.

## 8. Risk register

| ID | Risk | Likelihood | Impact | Primary mitigation | Owner persona | Gate |
|---|---|---:|---:|---|---|---|
| R1 | Wrong workload is paused or delayed | Medium | Critical | Protected-by-default metadata, tenant RBAC, independent policy guard, human approval | Security / Product | Simulator, pilot |
| R2 | Meter response differs from GPU prediction | High | High | Meter-in-loop calibration, confidence bounds, conservative action reserve | Test / Field | Lab |
| R3 | Recovery creates rebound peak | Medium | High | Separate recovery ceiling, staged release, hysteresis, soak tests | Reliability | Simulator, lab |
| R4 | Stale/poisoned telemetry drives unsafe action | Medium | Critical | Freshness/quality gates, redundant sources, inhibit on disagreement | Security / Reliability | HIL |
| R5 | Split-brain controllers issue conflicting commands | Low | Critical | Single lease, fencing token, idempotent adapter, partition tests | Reliability | HIL |
| R6 | Power cap harms stability or performance commitments | Medium | High | Vendor-supported bounds, workload characterization, SLO guardrail | Field / Product | Lab |
| R7 | Scheduler/API change breaks integration | High | Medium | Version pinning, compatibility tests, feature detection, rollback | Test / Field | Release |
| R8 | Control credential compromise | Medium | Critical | Workload identity, short-lived credentials, segmentation, rotation, audit | Security | Pilot |
| R9 | Incomplete audit makes event unverifiable | Medium | High | Append-only local buffer and remote retention; inhibit automation if unavailable | Security / Test | Simulator |
| R10 | Pilot customer expects utility-grade settlement | Medium | High | Explicit engineering-validation scope and claims review | Product | Contract |
| R11 | Human operator cannot stop system promptly | Low | Critical | Independent local kill path, drills, staffed event window | Field / Reliability | Pilot |
| R12 | Tenant metadata leaks through telemetry/reports | Medium | High | Data minimization, aliasing, tenant isolation, retention controls | Security | Pilot |
| R13 | Optimization oscillates or fails to converge | Medium | High | Deterministic fallback, hysteresis, rate limits, watchdog | Reliability / Test | Simulator |
| R14 | Simulator fidelity produces false confidence | High | High | Calibration with physical measurements, declare model limits, staged claims | Test / Product | Lab |
| R15 | Facility or vendor forbids power-cap changes | Medium | High | Written approval, compatibility matrix, admission-control fallback | Field | Site selection |
| R16 | Component outage stops production workloads | Low | Critical | Out-of-band supervisory design; critical workloads independent | Reliability | Architecture |
| R17 | Supply-chain dependency compromise | Medium | High | SBOM, signatures, scanning, pinned builds, provenance verification | Security | Release |
| R18 | Liability from direct facility control | Low initially | Critical | No facility write control in MVP; separate future safety case | Product / Architect | Scope |

Risks rated Critical may not be accepted informally. Residual acceptance belongs to the Chief Architect plus the accountable site owner; security/privacy risks also require the security owner.

## 9. Go/no-go gates

### Gate A — Architecture ready for implementation

Go only if:

- Scope and non-goals are signed off by the architect.
- State machine, authority hierarchy, safe states, action bounds, and data flows are documented.
- Threat model and risk owners are accepted.
- Simulator invariants and evaluation dataset are defined before tuning.

No-go if the controller is on the critical path for protected workloads, facility write control is included, or unknown workloads can be treated as flexible.

### Gate B — Simulator accepted

Go only if:

- Level 0 and Level 1 tests pass in repeatable CI.
- Acceptance thresholds in Section 6 pass on held-out and adversarial traces.
- All injected failures reach the specified safe outcome.
- Audit replay reconstructs every event and command.
- Known model limitations and residual risks are documented.

No-go for unexplained target violations, any protected-workload interruption, policy-bound violation, non-deterministic safety decision, or incomplete evidence.

### Gate C — Physical lab authorized

Go only if:

- HIL tests pass and exact hardware/vendor bounds are recorded.
- Independent metering is installed and time-aligned.
- Emergency stop, controller-loss behavior, and gradual restore are tested first at zero/low load.
- Workloads are synthetic or explicitly expendable.
- Site/operator safety approval is recorded.

No-go without permission to change power caps, without an independent local stop path, or if thermal/hardware alarms cannot be observed.

### Gate D — Shadow pilot authorized

Go only if:

- Lab characterization demonstrates repeatable meter response.
- Site inventory, integration versions, protected workloads, data agreement, and operational runbooks are complete.
- Security review has no unmitigated critical finding.
- Rollback and incident tabletop succeed.
- Claims and success criteria state that the phase is non-actuating.

### Gate E — Limited active pilot authorized

Go only if:

- Shadow predictions meet agreed accuracy over representative conditions.
- Human approval, staffed monitoring, strict magnitude/duration limits, and stop criteria are configured.
- Admission control and GPU-cap actions have passed site-specific tests.
- Pilot release is signed, pinned, recoverable, and observed end to end.
- Site owner, workload owner, security owner, and Chief Architect sign off.

Immediate stop conditions include protected-workload impact, policy or hardware-bound violation, loss of trustworthy meter/telemetry, audit failure, uncommanded action, security incident, inability to stop/restore, abnormal thermal condition, or rebound-ceiling breach.

### Gate F — Automatic dispatch consideration

Automation is out of MVP scope. It may be considered only after multiple supervised events demonstrate target accuracy, zero controller-caused protected-workload violations, reliable failover/rollback, stable recovery, complete audit evidence, and acceptable security operations. The architect must approve a new safety case and reduced action envelope before any unattended operation.

## 10. Council disagreements resolved for MVP

The Product Manager favors rapid proof of customer value; Reliability, Security, Test, and Field Engineering favor conservative control authority. The council resolves this tension as follows:

- Recommendations first, supervised actions second, automation later.
- Admission control and bounded power caps precede checkpoint/pause.
- Simulator success is necessary but never sufficient for physical claims.
- Product claims remain narrower than technical capability until independently measured.
- Speed is achieved by limiting scope, not by removing interlocks or evidence requirements.

If commercial timing conflicts with a safety, security, or evidence boundary, the issue is escalated to the Chief Architect. The system remains in its last approved stage until the architect records a decision.

## 11. Definition of pilot-ready

The council will call the system pilot-ready only when a new site can be deployed from versioned artifacts and documented configuration; its authority and network access can be explained precisely; all workloads default to protected; the operator can preview, approve, observe, stop, and recover an event; a controller or dependency failure produces a known safe result; and the resulting power/workload evidence can be reproduced from the audit record.

Pilot-ready does not mean utility-certified, production-autonomous, or safe to control facility electrical equipment.
