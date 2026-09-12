# ADR-0001: Simulator-first supervisory power-envelope controller

Status: Accepted by Chief Architect, 2026-08-30

## Decision

The initial product is a supervisory, modular Python monolith that keeps a simulated GPU cluster within a declared facility-meter power envelope while maximizing useful work and protecting workload contracts.

The Chief Architect ratifies the three council proposals with these decisions:

1. Python 3.9+ standard library is the initial runtime. Stable domain and adapter interfaces matter more than service boundaries.
2. Simulation ticks are one second. Control decisions occur every five seconds.
3. The authoritative constraint is measured facility/host power, not GPU-board telemetry.
4. Workloads are protected unless an authorized contract explicitly permits deferral, power capping, or checkpoint/pause.
5. The first executable controller uses a deterministic heuristic. Formal optimization follows only after the heuristic, audit, recovery, and fault behavior pass.
6. Automatic actuation is allowed only in simulation. Physical hardware begins in shadow mode and later requires human approval.
7. Checkpoint/pause remains simulated until a supported training framework and site policy are selected.
8. Simulated batteries and other DER are excluded from the first demo.
9. Facility systems are read-only through the MVP and early pilot.
10. The initial scheduler adapter will be selected from Kubernetes or Slurm only after a credible design partner supplies requirements.
11. A physical GPU test requires NVML plus an independent host/PDU meter. NVML alone cannot support a facility-power claim.
12. Loss of control inhibits new actions. Temporary caps are held conservatively until an operator-approved, rate-limited unwind; there is no universal safe cap.

## Safety invariants

- Facility and hardware protection always outrank orchestration.
- Critical and unknown workloads cannot be interrupted or capped below their declared minimum.
- Plans are independently validated before actuation.
- Stale authoritative telemetry prevents new actuation.
- Every command is bounded, attributable, idempotent, expiring, and auditable.
- Recovery uses a separate ramp budget and cannot create a rebound violation.
- Infeasible requests produce a shortfall; they never authorize unsafe action.
- No LLM participates in the real-time control or safety path.

## Initial acceptance targets

- Feasible reductions become compliant within 60 simulated seconds.
- Post-settling power is no higher than the envelope plus 5% tolerance for at least 99% of controlled intervals in the canonical trace.
- Zero protected-workload violations.
- Zero device- or policy-bound violations.
- Recovery remains under the active envelope and configured ramp.
- Every decision and action has a complete audit record.
- Identical seed, input and version produce identical decisions.

## Consequences

This architecture favors evidence and safe integration over feature breadth. It postpones wholesale-market participation, direct facility control, multisite migration, batteries, and autonomous physical dispatch. Those are separate architecture decisions after simulator, lab, and shadow-pilot gates pass.
