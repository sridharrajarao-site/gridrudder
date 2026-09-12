# Compute and Product Council Proposal: Simulator-First Grid-to-GPU MVP

Status: Council consensus proposal for Chief Architect review  
Authority: The Chief Architect has final authority over all decisions in this document.  
Council personas: Product Architect, Distributed Systems Engineer, GPU Engineer, Kubernetes/Slurm Engineer, Data Engineer, Optimization Engineer

## 1. Consensus product definition

The MVP is a deterministic, simulator-first cluster power-envelope controller.

Its promise is:

> Given a time-varying cluster power limit, keep simulated or real GPU-cluster consumption within the limit, protect declared critical workloads, minimize lost useful work, and produce an auditable explanation of every action.

The first customer is a GPU cluster operator constrained by a facility power ceiling. Utility dispatch, energy-market settlement, cooling control, batteries, and multisite migration are future integrations rather than MVP requirements.

The council unanimously recommends this entry point because it produces standalone value before a utility relationship exists and isolates the central technical hypothesis: job-aware control can turn GPU load into predictable, measurable flexibility.

## 2. Product scope

### MVP capabilities

1. Simulate heterogeneous GPU nodes, workloads, meters, and time-varying power envelopes.
2. Submit workloads with priority, deadline, resource, and flexibility declarations.
3. Estimate each workload's power and progress response to permitted actions.
4. Choose deterministic actions to stay inside the envelope.
5. Initially support these control levers:
   - defer queued jobs;
   - block new admissions;
   - allocate per-job/per-node GPU power caps;
   - checkpoint and pause explicitly interruptible simulated jobs;
   - resume work gradually after constraint relief.
6. Preserve hard invariants for critical workloads.
7. Compare requested, predicted, and observed power.
8. Record decisions, commands, acknowledgements, outcomes, and workload impact in an append-only audit log.
9. Replay any simulation from seed, configuration, workload trace, and event stream.
10. Run in recommendation-only and automatic-control modes; recommendation-only is the default.

### Explicit non-goals

- A replacement for Kubernetes or Slurm.
- Direct control of breakers, UPSs, batteries, generators, cooling, or protective equipment.
- Wholesale electricity-market bidding or settlement.
- Automated geographic migration.
- Training-framework-independent checkpointing of arbitrary real jobs.
- Supporting every accelerator vendor in the first release.
- Using an LLM in the real-time control or safety path.
- Claiming utility-grade demand-response performance from simulated results.

## 3. Success metrics and safety invariants

### Primary metrics

- Power-envelope compliance: percentage of controlled intervals at or below the limit plus tolerance.
- Target error: time-weighted absolute difference between target and observed power.
- Response latency: time from envelope change to compliant measured power.
- Useful work: normalized training progress or completed inference units.
- Critical-workload SLO violations.
- Deferred GPU-hours and deadline misses by priority class.
- Rebound overshoot after a constrained event.
- Prediction calibration: error between predicted and observed action response.
- Decision reproducibility under identical inputs.

### Non-negotiable invariants

1. The optimizer may invoke only actions declared safe by the workload contract.
2. Critical inference capacity and minimum power allocations cannot be preempted by optimization.
3. Stale telemetry, lost command acknowledgement, or controller uncertainty triggers a defined safe mode.
4. The controller never substitutes for hardware protection or facility safety systems.
5. Every actuation is attributable to a policy version and input snapshot.
6. Recovery is rate-limited; an event ending cannot cause an uncontrolled restart surge.
7. An operator can disable automatic control and restore configured defaults.

## 4. Architecture

```text
Workload trace / scheduler adapter       Envelope source
                 |                              |
                 v                              v
          State ingestion  <--- time ---> Event normalizer
                 |                              |
                 +------------+-----------------+
                              v
                       State estimator
                   (power, progress, headroom)
                              |
                              v
                     Flexibility planner
             (constraints + deterministic optimizer)
                              |
                      proposed action plan
                              v
                    Policy/safety validator
                         |             |
                    reject/explain   approve
                                       |
                                       v
                              Actuation manager
                              |              |
                     simulator adapter   hardware/scheduler
                                           adapters later
                              |              |
                              +------+-------+
                                     v
                              Meter/telemetry
                                     |
                       +-------------+-------------+
                       v                           v
                 Closed-loop update       Audit/event store
```

### Component responsibilities

#### Simulator

A discrete-time simulator with configurable tick size (default one second) models:

- node/GPU idle and active power;
- power-cap-to-throughput curves;
- workload arrival, progress, deadline, and checkpoint behavior;
- host and facility overhead;
- measurement noise and delay;
- actuator latency and failure;
- cooling overhead using a simple configurable function;
- faults such as missing telemetry or rejected commands.

It exposes the same adapter interfaces as future hardware, so the controller does not contain simulator-specific logic.

#### State estimator

Produces a versioned cluster snapshot from potentially delayed observations. It estimates baseline load, controllable load, response uncertainty, and available flexibility. All data carries event time, ingestion time, source, quality, and units.

#### Flexibility planner

Computes a finite-horizon action plan. It treats the power envelope and workload safety declarations as hard constraints and useful-work loss, action churn, and deadline risk as costs.

#### Policy/safety validator

Independently checks that proposed actions satisfy workload contracts, bounds, ramp limits, telemetry freshness, and authorization. Planner correctness is never the sole safety boundary.

#### Actuation manager

Uses idempotent commands, unique command IDs, explicit acknowledgements, deadlines, retry rules, and compensating actions. It prevents a late acknowledgement from applying a superseded plan.

#### Audit and replay

Stores normalized inputs, state snapshots, decisions, commands, outcomes, policy/configuration hashes, and random seeds. A replay run must reproduce the same decisions or identify a version mismatch.

## 5. Interfaces and data models

The logical API is transport-neutral. The first implementation may use local process calls plus JSON/JSONL; network services are unnecessary until deployment boundaries require them.

### Core entities

```yaml
Workload:
  workload_id: string
  tenant_id: string
  kind: training | batch_inference | online_inference | synthetic
  priority: critical | high | normal | opportunistic
  requested_gpus: integer
  compatible_gpu_types: [string]
  arrival_time: timestamp
  deadline: timestamp | null
  estimated_work_units: number
  minimum_service:
    min_gpus: integer
    min_throughput: number | null
    max_latency_ms: number | null
  flexibility:
    may_defer: boolean
    may_power_cap: boolean
    min_power_watts_per_gpu: number | null
    may_checkpoint_pause: boolean
    max_pause_seconds: integer
    checkpoint_interval_seconds: integer | null
    max_interruptions: integer | null
  state: queued | running | checkpointing | paused | completed | failed
```

```yaml
PowerEnvelope:
  envelope_id: string
  source: operator | facility | grid_simulator
  effective_at: timestamp
  expires_at: timestamp | null
  max_cluster_power_watts: number
  ramp_down_watts_per_second: number | null
  ramp_up_watts_per_second: number | null
  tolerance_watts: number
  precedence: integer
```

```yaml
TelemetrySample:
  source_id: string
  metric: string
  value: number
  unit: string
  event_time: timestamp
  ingestion_time: timestamp
  quality: good | estimated | stale | invalid
  sequence: integer
```

```yaml
Action:
  action_id: string
  plan_id: string
  target_type: workload | node | gpu | scheduler
  target_id: string
  action_type: admit | defer | set_power_cap | checkpoint_pause | resume
  parameters: object
  earliest_at: timestamp
  expires_at: timestamp
  expected_power_delta_watts: number
  expected_work_impact: number
  reason_codes: [string]
  preconditions: [object]
```

```yaml
ActionResult:
  action_id: string
  status: accepted | rejected | applied | failed | superseded
  observed_at: timestamp
  observed_power_delta_watts: number | null
  error_code: string | null
```

```yaml
DecisionRecord:
  decision_id: string
  policy_version: string
  optimizer_version: string
  configuration_hash: string
  state_snapshot_id: string
  envelope_id: string
  proposed_plan: [Action]
  validation: approved | rejected
  rejection_reasons: [string]
  objective_breakdown: object
  created_at: timestamp
```

### Adapter contracts

`SchedulerAdapter`

- `list_workloads()`
- `get_workload_state(id)`
- `apply_admission_policy(policy, command_id)`
- `checkpoint_pause(id, command_id)`
- `resume(id, command_id)`

`AcceleratorAdapter`

- `list_devices()`
- `read_power(device_ids)`
- `read_utilization(device_ids)`
- `get_power_cap_bounds(device_id)`
- `set_power_cap(device_id, watts, command_id)`
- `restore_default_power_cap(device_id, command_id)`

`MeterAdapter`

- `read_interval(start, end)`
- `subscribe(samples_callback)`
- samples must declare whether values are instantaneous or interval averages.

`EnvelopeAdapter`

- `list_active_envelopes()`
- `subscribe(events_callback)`
- conflicting envelopes resolve through explicit precedence, then the most restrictive valid limit.

### Operator API

- `POST /v1/workloads`
- `POST /v1/envelopes`
- `GET /v1/state`
- `POST /v1/plans:recommend`
- `POST /v1/plans/{id}:approve`
- `POST /v1/control:disable`
- `POST /v1/control:restore-defaults`
- `GET /v1/events/{id}/report`
- `POST /v1/replays`

Mutating calls require idempotency keys. Production adapters must authenticate callers and enforce role-based authorization; simulation may use a local development identity.

## 6. Control and optimization approach

### Recommended progression

#### Stage A: deterministic heuristic baseline

At each control interval:

1. Calculate projected excess power over the finite horizon.
2. Reserve minimum allocations for critical and non-flexible work.
3. Rank legal actions by expected watts reduced per unit of weighted useful-work loss.
4. Apply the least harmful actions until predicted power is below the envelope with an uncertainty margin.
5. Validate the plan independently.
6. Observe response and update action-effect estimates.

The action order initially is:

1. defer not-yet-started opportunistic jobs;
2. reduce caps on power-cap-permitted opportunistic jobs;
3. reduce caps on normal jobs within declared bounds;
4. checkpoint/pause explicitly interruptible opportunistic jobs;
5. use higher-impact actions only when configured and operator-approved.

This yields an understandable reference policy and a fallback when the optimizer fails.

#### Stage B: constrained optimization

Implement model-predictive control using a mixed-integer linear or convex approximation, depending on supported actions.

Objective:

```text
minimize
    weighted unfinished work
  + deadline-risk penalty
  + interruption/checkpoint cost
  + power-cap throughput loss
  + action-churn penalty
  + envelope tracking error
  + rebound-risk penalty
```

Subject to:

- cluster power <= envelope - uncertainty reserve;
- device cap bounds;
- workload minimum service and allowed-action contracts;
- accelerator capacity and placement;
- checkpoint state transitions;
- ramp-rate and recovery limits;
- action cooldowns;
- critical workload protections.

The optimization has a strict solve-time budget. Timeout, infeasibility, or invalid output falls back to the validated heuristic. Exact optimality is less important than bounded, predictable behavior.

### Power-response learning

Use explicit parametric profiles first:

```text
facility_power = fixed_overhead
               + host_power
               + sum(gpu_power)
               + cooling_function(IT_power, ambient_state)
```

Each workload/hardware profile maps power cap and allocated GPUs to throughput. Online calibration may update bounded coefficients from observations, but unbounded black-box learning cannot directly authorize safety-critical actions. Predictions include confidence intervals; the controller holds a reserve proportional to uncertainty.

### Recovery policy

When an envelope relaxes, restore workloads through a token-bucket or ramp-budget mechanism:

- raise caps in bounded increments;
- admit/resume jobs by priority and aging;
- wait for measured response before the next increment;
- preserve configurable headroom;
- stop or reverse recovery if the meter approaches the limit.

## 7. Milestones

### M0 — Architecture contract and fixtures (week 1)

- Approve terminology, invariants, schemas, adapter contracts, units, and clock semantics.
- Produce two canonical traces: normal operation and a constrained event.
- Record Chief Architect decisions on unresolved points.

Exit: all components can be tested against shared fixtures without implementation coupling.

### M1 — Reproducible simulator (weeks 2–3)

- Discrete-time engine, workload lifecycle, GPU/power models, meter model, envelope events, deterministic seeds.
- JSONL event output and replay command.

Exit: identical inputs yield identical event streams; energy is conserved within modeled tolerances.

### M2 — Observable heuristic controller (weeks 4–5)

- State estimator, heuristic planner, policy validator, recommendation mode, audit log.
- Basic operator CLI/API and event report.

Exit: canonical constraint scenario meets envelope without violating critical workload contracts.

### M3 — Closed-loop actuation and recovery (weeks 6–7)

- Idempotent actuation, acknowledgements, failures, delayed telemetry, automatic mode, recovery ramp.
- Fault injection and safe-mode behavior.

Exit: controller remains safe under the defined fault matrix.

### M4 — Optimization and calibrated models (weeks 8–9)

- Finite-horizon optimizer, heuristic fallback, objective reporting, confidence reserve, trace-driven power profiles.

Exit: optimizer improves useful work against the heuristic on a benchmark suite without weakening constraints.

### M5 — Scheduler/GPU adapter boundary (weeks 10–12)

- Choose one scheduler first: Kubernetes or Slurm, based on the first design partner.
- Implement read-only discovery, then admission control in a test environment.
- Add an NVML-backed accelerator adapter behind a feature flag when hardware becomes available.

Exit: the same controller passes simulator conformance and small-cluster shadow-mode tests.

## 8. Acceptance test suite

### Core product acceptance

1. **Thirty-minute dispatch:** For a changing power limit, measured simulated power remains at or below limit + 5% tolerance for at least 99% of post-response intervals; it becomes compliant within 60 seconds of each feasible reduction request.
2. **Critical workload protection:** Zero critical SLO violations attributable to controller action across the canonical suite.
3. **Action legality:** Zero actions outside workload-declared flexibility or device bounds.
4. **Useful-work preservation:** Controller completes more weighted work than an indiscriminate equal-throttling baseline under the same envelope.
5. **No rebound:** Recovery does not exceed the active limit + 5% and respects configured ramp rates.
6. **Auditability:** Every command maps to a decision, snapshot, policy version, expected impact, acknowledgement, and observed outcome.
7. **Replay:** Same code/configuration/seed/input reproduces decisions exactly; changed versions are reported.

### Fault acceptance

1. Stale or missing meter data enters recommendation-only safe mode and emits an alert.
2. A rejected/failed cap command is not counted as delivered flexibility; the plan is recomputed.
3. Duplicate commands are idempotent.
4. Out-of-order samples do not corrupt current state.
5. Controller restart reconstructs state from the event log and reconciles actual adapter state.
6. Optimizer timeout uses the heuristic fallback within the control deadline.
7. Infeasible envelope produces an explicit shortfall estimate instead of violating protected workloads.

### Model acceptance

- Power predictions report error distributions by hardware/workload profile.
- On held-out traces, aggregate action-response mean absolute percentage error is <=10% before automatic real-hardware control is enabled.
- Units, timestamp semantics, and interval aggregation pass contract tests.

### Hardware readiness gate

Before controlling a rented GPU, shadow mode must run for at least one representative workload trace, all commands must have configured safe bounds, and restore-default behavior must be verified manually. Real-hardware acceptance criteria will be approved separately by the Chief Architect and safety/reliability council.

## 9. Persona positions, disagreements, and resolution

### Product Architect

Position: prioritize a demonstrable operator outcome and postpone utility-market complexity. Require an event report that a nontechnical operator can understand.

### Distributed Systems Engineer

Position: favor a modular monolith and stable adapter interfaces over microservices. Require idempotency, event time, explicit state machines, reconciliation, and replay from day one.

### GPU Engineer

Position: begin with device power caps and admission control. Arbitrary checkpoint/pause is framework-specific and should remain simulated until a supported workload template exists. GPU telemetry is not equivalent to facility-meter response.

### Kubernetes/Slurm Engineer

Position: do not build a scheduler. Integrate through existing priority, queue, admission, suspend/resume, and job metadata mechanisms. Supporting Kubernetes and Slurm simultaneously would slow the first validation.

### Data Engineer

Position: time alignment, units, data quality, lineage, and immutable raw events are product requirements, not later observability work. Store event-time and ingestion-time separately.

### Optimization Engineer

Position: build a heuristic benchmark first, then finite-horizon constrained optimization. Avoid reinforcement learning in the control path until there is extensive real-world data and an independently enforced safety envelope.

### Disagreement 1: optimizer-first versus heuristic-first

- Optimization argued that a formal constrained model better represents deadlines, ramp limits, and heterogeneous workloads.
- Distributed systems and product argued that optimizer complexity would obscure basic state and actuation bugs.
- **Council resolution:** ship a deterministic heuristic as executable specification and fallback; add formal optimization only after closed-loop telemetry and actuation tests pass. Both remain benchmarked.

### Disagreement 2: Kubernetes versus Slurm first

- Kubernetes offers broader cloud-native adoption and admission controls.
- Slurm is common in training/HPC environments and exposes explicit queued jobs and power-aware scheduling hooks.
- **Council resolution:** keep a scheduler-neutral domain model; choose exactly one initial adapter based on the first credible design partner. No speculative dual integration. Chief Architect makes the final selection.

### Disagreement 3: direct GPU control versus scheduler-only control

- GPU engineering favored power caps for fast, continuous response.
- Scheduler engineering favored queue and workload actions that preserve infrastructure boundaries.
- **Council resolution:** use both as distinct levers. Admission control is the lowest-risk energy lever; bounded power caps provide faster response. The policy validator enforces workload and device permissions. Scheduler integration never assumes a GPU command succeeded, and GPU telemetry never substitutes for the facility meter.

### Disagreement 4: database and deployment topology

- Data engineering preferred durable analytical storage early.
- Distributed systems preferred minimal operational dependencies for reproducibility.
- **Council resolution:** use append-only JSONL/columnar artifacts for the simulator and a repository abstraction for state/event persistence. Select a production database only when multi-process or multi-site deployment requires one. The schema contract, not a database vendor, is authoritative.

### Disagreement 5: automatic control in the MVP

- Product wanted visible autonomous behavior for a compelling demonstration.
- GPU and distributed systems raised safety and reconciliation concerns.
- **Council resolution:** automatic control exists only in simulation at first. Real hardware begins in shadow/recommendation mode, moves to operator approval, and reaches bounded automation only after Chief Architect approval of a hardware readiness gate.

### Disagreement 6: power target interpretation

- Optimization initially treated the target as IT/GPU power for simpler modeling.
- Product and data argued customer and utility value is measured at the facility or billing meter.
- **Council resolution:** the authoritative target is a declared meter boundary. The simulator models GPU, host, cooling, and fixed loads separately. GPU-only targets may be used in lab tests but cannot be presented as facility flexibility.

## 10. Chief Architect decision requests

The council recommends approval of the overall proposal and asks the Chief Architect to decide or ratify:

1. The initial scheduler adapter after a design partner is identified.
2. Default simulator tick and control intervals; council default is 1-second simulation ticks and 5-second planning intervals.
3. Initial automatic-control tolerance; council proposes max(limit + 5%, limit + declared meter uncertainty).
4. Whether checkpoint/pause remains simulator-only through M4; council recommends yes.
5. The production language and repository layout after reviewing the reliability/security council constraints.
6. The exact hardware readiness and operator-approval gates.

Until ratified, this document is a council recommendation. In any conflict among persona preferences, the safety invariants remain binding and the Chief Architect's decision is final.
