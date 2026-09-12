# Power & Controls Council Design

Status: proposed for Chief Architect review. The Chief Architect has final authority over conflicts with compute, product, security, or reliability designs.

Council personas: Power Systems Engineer, Controls Engineer, Facility Integration Engineer, Utility Integration Engineer.

## 1. MVP boundary and assumptions

The simulator-first MVP proves one narrow capability:

> Given a time-varying site power ceiling, keep simulated meter power within that envelope by requesting bounded compute actions, while protecting critical workloads and producing an auditable event record.

Assumptions:

- Phase 1 controls simulated compute only. Facility electrical and cooling systems are observed, not commanded.
- The authoritative constraint is active power at the point of common coupling (PCC), expressed in kW. GPU-board power is an input, not the settlement measurement.
- The facility's protective relays, UPS, generators, battery management, BMS, and emergency controls remain independent and always take precedence.
- The orchestration service is an optimization layer, never a protection system or life-safety controller.
- A scheduler adapter owns workload actions. The power controller never talks directly to arbitrary job processes.
- Workloads are critical, firm, or flexible. Only explicitly opted-in flexible work may be paused or terminated. Firm work may receive pre-authorized power-cap reductions. Critical work is never interrupted by this MVP.
- Time is UTC, synchronized, monotonic for control calculations, and tagged with source quality. Simulator default cadence is 1 second; control decisions default to 5 seconds.
- The first external use case is a facility demand ceiling, not ancillary-frequency regulation. Response target is minutes, not milliseconds.
- All actuator magnitudes, ramp rates, minimum dwell times, and restore behavior are configured per site and validated before enablement.

## 2. Authority and operating modes

Authority order, highest first:

1. Electrical protection and equipment-local safety controls
2. Facility emergency stop and operator command
3. Static interconnection/site limit
4. Utility or aggregator dispatch accepted by the site
5. Workload SLAs and customer constraints
6. Cost and throughput optimization

Modes:

- `OBSERVE`: ingest telemetry, forecast, and recommend; no commands.
- `SUPERVISED`: create a plan; authorized operator approves execution.
- `AUTOMATIC_BOUNDED`: execute only pre-approved actions within a signed site policy.
- `SAFE_HOLD`: stop issuing new workload changes; hold or unwind according to the last known safe policy.
- `RECOVERY`: gradually restore compute under an explicit recovery envelope.

Every mode transition is authenticated, authorized, timestamped, and recorded. Loss of supervisory software must not remove existing electrical protections or increase the site ceiling.

## 3. Control model

### 3.1 Signals

At time `t`:

- `P_pcc(t)`: measured real power at the PCC
- `P_it(t)`: measured/simulated IT power
- `P_cooling(t)`: cooling and heat-rejection power
- `P_other(t)`: remaining facility load
- `P_der(t)`: net onsite resource contribution, positive when serving facility load
- `L_site(t)`: immutable or operator-approved site ceiling
- `L_event(t)`: accepted event ceiling, if present
- `L_effective(t) = min(L_site(t), L_event(t)) - reserve(t)`
- `reserve(t)`: uncertainty and contingency margin
- `headroom(t) = L_effective(t) - P_pcc(t)`

Power balance for the simulator:

`P_pcc = P_it + P_cooling + P_other - P_der + measurement_noise`

Cooling is modeled as delayed load, not a fixed PUE multiplier. The first-order default is:

`tau_c * dP_cooling/dt = target_cooling(P_it, ambient) - P_cooling`

This captures the fact that a GPU reduction may not immediately appear one-for-one at the PCC.

### 3.2 Two-loop design

The system uses hierarchical model-predictive control with deterministic guardrails:

- **Planner loop (30-60 seconds):** forecasts load and chooses a least-cost action portfolio over a 15-60 minute horizon. It considers deadlines, checkpoint status, predicted kW response, action latency, rebound risk, and uncertainty.
- **Envelope loop (5 seconds):** compares filtered PCC power against the effective limit and requests bounded corrections from approved actuators.

The optimization objective is lexicographic:

1. Never violate safety invariants.
2. Protect critical and firm SLAs.
3. Meet the power envelope with confidence.
4. Minimize lost useful work and restart cost.
5. Minimize action churn and recovery rebound.

The MVP action order is:

1. Block or defer queued flexible jobs.
2. Lower pre-authorized GPU power caps within hardware/site bounds.
3. Checkpoint and pause opted-in flexible jobs.
4. Request optional simulated DER dispatch.

Termination, critical-workload interruption, generator starts, breaker operation, UPS-mode changes, and direct cooling control are prohibited.

### 3.3 State machine

`IDLE -> PREPARE -> RAMP_DOWN -> SUSTAIN -> RAMP_UP -> SETTLE -> COMPLETE`

- `PREPARE`: validate event signature, telemetry quality, actuator availability, predicted flexibility, SLAs, and operator/site policy.
- `RAMP_DOWN`: follow the event ramp, prioritizing reversible low-risk actions.
- `SUSTAIN`: maintain target plus reserve; avoid oscillation using deadbands and minimum dwell times.
- `RAMP_UP`: restore gradually under a separately calculated ceiling.
- `SETTLE`: verify no rebound violation and close deferred-work accounting.
- Any state can enter `ABORT` or `SAFE_HOLD` on an invariant breach.

Defaults for simulation, subject to architect approval: 2% deadband around the ceiling, three consecutive valid samples before non-emergency reversal, 60-second minimum action dwell, and restoration limited to the smaller of 5% of site limit per minute or configured facility ramp rate.

## 4. Telemetry contract

Every sample includes `timestamp_utc`, `monotonic_sequence`, `source_id`, `value`, `unit`, `quality`, and `ingest_latency_ms`.

Required simulator/MVP telemetry:

| Domain | Minimum signals | Nominal cadence |
|---|---|---:|
| PCC | kW, kVA, power factor, frequency, cumulative kWh | 1 s |
| Facility | IT kW, cooling kW, other kW, site limit, ramp limit | 1-5 s |
| Compute | per-GPU power, cap, utilization; host power; job ID/class/state | 1 s |
| Workload | priority, deadline, interruptibility, checkpoint age/cost, SLA | event + 5 s |
| DER simulation | available kW, state of charge, ramp, duration, local constraints | 1 s |
| Grid event | issuer, event ID, requested kW/ceiling, start/end, ramp, program | event |
| Control | proposed action, approval, command, acknowledgement, observed effect | event |

Meter/PCC telemetry is authoritative for envelope compliance. GPU telemetry is used for attribution and prediction. Data quality states are `GOOD`, `SUSPECT`, `STALE`, and `BAD`; only `GOOD` may support automatic dispatch. The initial stale threshold is 5 seconds for PCC data and 15 seconds for compute data.

Clock skew between authoritative meter and controller must be below 250 ms in the simulator and below 1 second for a demand-response pilot. All raw and derived event data is immutable for the configured retention period.

## 5. Baseline and measurement & verification

Two measurements must not be conflated:

- **Envelope compliance:** Did `P_pcc` remain below the contractual ceiling? This is directly measured and does not require a counterfactual baseline.
- **Demand reduction:** How many kW were reduced relative to what would otherwise have occurred? This requires a program-approved baseline.

For the simulator, store ground-truth counterfactual power by replaying the same workload seed without control. Report both ground truth and estimated reduction.

For early pilots:

1. Prefer a facility-ceiling test with a nominated pre-event operating level, because it is easier to verify.
2. For demand-response estimation, use the utility/aggregator's approved method; do not invent a settlement baseline after the event.
3. Candidate research method: weather- and schedule-matched historical baseline using selected non-event days, with a limited pre-event adjustment and exclusions fixed before dispatch.
4. Quantify uncertainty and report a conservative lower confidence bound for delivered flexibility.

An event report includes request, accepted commitment, baseline method/version, meter provenance, target and actual time series, response time, mean/maximum delivered reduction, limit exceedance energy (`kWh_over_limit`), SLA effects, actuator actions, deferred GPU-hours, rebound peak, data gaps, and cryptographic audit identifiers.

No commercial claim is settlement-grade until the serving utility/aggregator approves the meter, telemetry path, baseline, interval, and calculation version.

## 6. Safety invariants

These are hard constraints, not optimization preferences:

1. Never command above a site's immutable electrical limit or outside an actuator's validated range/ramp.
2. Never interrupt or power-cap a workload beyond its explicit flexibility policy.
3. Never directly operate switchgear, relays, generators, UPS transfer, battery protection, or life-safety/cooling protection in MVP phases.
4. Never execute an unsigned, expired, replayed, conflicting, or unauthorized grid event.
5. Automatic control requires fresh authoritative meter data, healthy command channels, synchronized clocks, and an approved action budget.
6. A telemetry or control fault cannot trigger an increase in power demand. Unknown state fails to `SAFE_HOLD`, followed by a bounded operator-defined unwind.
7. Local equipment and scheduler safety limits always override orchestration commands.
8. Recovery may not exceed the recovery envelope or create a second site-limit violation.
9. Commands are idempotent and carry event, policy-version, expiry, sequence, and correlation identifiers.
10. Every executed action is attributable to a principal and reproducible from versioned inputs, policy, and controller code.
11. The controller reserves headroom for forecast error and cooling lag; it may not sell or promise that reserve.
12. One control authority is active per actuator at a time; conflicts force arbitration or `SAFE_HOLD`.

## 7. Integration protocols

Use adapters behind a canonical internal API; do not embed vendor protocols in control logic.

- Grid/aggregator: HTTPS webhooks/REST initially; OpenADR 2.0b/3 where required. IEC 62746-10-1 mapping is evaluated per partner.
- Facility read-only telemetry: Modbus TCP, BACnet/IP, OPC UA, SNMP, Redfish, or vendor APIs through an edge gateway.
- Metering: revenue-grade or pilot-approved meter via facility historian/gateway; retain signed raw intervals.
- Compute: Kubernetes and Slurm adapters; NVIDIA NVML/DCGM for telemetry and permitted power-cap operations.
- Events/telemetry: authenticated message bus with durable ordering, schema versioning, deduplication, and backpressure.
- Time: NTP for MVP and demand response; PTP only if a future subsecond service requires it.

Security minima: mutual TLS, short-lived workload identity, least-privilege RBAC, separate read/control credentials, allowlisted commands and bounds at the edge, signed dispatch messages, tamper-evident audit log, network segmentation, and manual local override. No inbound utility connection is allowed directly to a GPU or facility controller.

## 8. Failure modes and required responses

| Failure | Detection | Required response |
|---|---|---|
| PCC telemetry stale/bad | quality/heartbeat | Stop automatic changes; `SAFE_HOLD`; alert; do not claim performance for gap |
| Scheduler/API unreachable | timeout/failed ack | Remove unavailable flexibility; choose another approved action or under-delivery alert |
| Command acknowledged but no kW effect | response model residual | Do not repeat blindly; mark actuator degraded; replan within action budget |
| Power exceeds limit | filtered meter + fast threshold | Apply pre-approved emergency compute reduction; block starts; alert operator |
| Controller crash/restart | watchdog/lease | Edge guard retains conservative cap; new leader reconciles state before commands |
| Duplicate/out-of-order event | event ID/sequence | Idempotently ignore or supersede per signed priority rules |
| Grid event conflicts with site/operator limit | policy engine | Apply stricter limit; reject excess commitment and record reason |
| Clock drift | time monitor | Disable settlement claims and automatic event start; maintain static site ceiling |
| Forecast/model error | residual thresholds | Expand reserve, derate available flexibility, fall back to rule-based control |
| Rebound after release | recovery forecast/meter | Halt restoration; re-enter sustain/recovery; stagger job starts |
| Network partition | heartbeat/lease | Site edge remains authoritative; conservative local envelope; cloud cannot command |
| Malicious/unauthorized command | signature/RBAC/rate anomaly | Reject, isolate channel, alert, preserve evidence |
| Cooling/thermal alarm | facility status | Freeze power increases; scheduler drains affected capacity per facility policy |
| Simulator numerical instability | bounds/assertions | Fail test, preserve seed and trace; never treat run as acceptance evidence |

## 9. Acceptance thresholds

### Simulator exit criteria

Across at least 1,000 deterministic scenarios, including step/ramp events, noisy meters, cooling lag, workload arrivals, missing telemetry, actuator failures, and controller restart:

- Zero safety-invariant violations.
- 99% of feasible events reach the requested ceiling within 60 seconds; 100% within the contractual response time configured for the scenario.
- Steady-state absolute tracking error at or below 2% of requested reduction or 1% of site limit, whichever is larger.
- `kWh_over_limit` at or below 0.1% of event energy for feasible events; every exceedance reported.
- Zero critical-workload interruptions and zero unauthorized firm/flexible actions.
- Recovery peak never exceeds the recovery envelope; no more than 2% overshoot in test-only transient metrics.
- 100% of commands and state transitions traceable in the audit log.
- Controller restart recovers consistent state within 30 seconds without issuing duplicate actions.
- Estimated reduction error median below 5% and 95th percentile below 10% against simulator counterfactual.
- Infeasible requests are identified before acceptance or explicitly under-delivered with reason; the system never silently promises unavailable kW.

### Small-cluster supervised pilot criteria

- Meter/power telemetry completeness at least 99.9% during events.
- At least 20 supervised events across multiple workload mixes.
- 95% of feasible events reach target within 60 seconds and remain within the effective envelope for at least 99% of event intervals.
- Mean delivered reduction within +/-5% of commitment; no critical SLA breach attributable to control.
- Zero unsafe commands, electrical protection interactions, or uncontrolled rebound violations.
- Operator can abort and return to the approved safe state in every drill.

These are engineering targets, not utility settlement promises; partner requirements override them when stricter.

## 10. Phased utility integration

### Phase U0: synthetic dispatch

Signed simulator events; counterfactual replay; no external control or market claims.

### Phase U1: facility power-envelope pilot

Operator sets a local ceiling. Read one approved meter, control one cluster in `SUPERVISED`, and produce event reports. No utility dependency.

### Phase U2: shadow utility/aggregator integration

Receive real signals via API/OpenADR but recommend only. Compare predicted, available, and meter-observed flexibility; utility validates telemetry and baseline.

### Phase U3: supervised demand-response pilot

Partner performs enrollment and settlement. Site operator accepts each event. The product controls compute only and submits auditable M&V data.

### Phase U4: bounded automatic demand response

Automatic acceptance only inside pre-negotiated kW, duration, frequency, workload, and recovery bounds. Independent edge guard, security review, incident drills, and operator override are mandatory.

### Phase U5: flexible interconnection / multisite

Only after repeatable U4 evidence: utility-recognized operating envelope, formal availability/telemetry SLAs, conservative capacity accreditation, multisite coordination, and optional DER participation. Faster ancillary services remain a separate product and certification path.

## 11. Architect decisions requested

The council recommends the Chief Architect resolve these cross-team contracts first:

1. Canonical workload flexibility schema and who may modify it.
2. Exact ownership boundary between power planner, scheduler adapter, and local edge guard.
3. Event and telemetry schemas, time-series retention, and audit-log implementation.
4. Whether simulated DER is included in the first demo; council preference is optional and disabled by default.
5. Initial control cadence, site scale, and response-time product claim.
6. Whether the first hardware test uses an external host meter in addition to NVML; council strongly recommends yes.
7. Policy for safe unwind after controller loss. The council recommends holding conservative caps until operator confirmation rather than automatically restoring full demand.

## 12. Council consensus

All four council personas agree on the following MVP shape:

- Start with a measurable site power ceiling, not wholesale-market complexity.
- Use deterministic optimization with hard policy constraints, not an LLM in the control path.
- Make the PCC/host meter authoritative and treat GPU telemetry as explanatory.
- Begin read-only at the facility layer and supervised at the compute layer.
- Treat recovery and rebound control as part of every grid event, not an afterthought.
- Build utility credibility through predeclared M&V, conservative commitments, and an immutable event record.

The Chief Architect may amend this proposal, but any change to a safety invariant requires an explicit written decision and replacement control.
