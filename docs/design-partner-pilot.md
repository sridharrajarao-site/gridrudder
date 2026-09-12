# GridRudder supervised design-partner pilot

## Pilot objective

Determine whether GridRudder can reduce or bound measured server power on a partner’s supported NVIDIA GPU host while respecting a declared workload contract and leaving an independently verifiable audit trail.

This is an attended evaluation, not a production deployment or autonomous data-center control service. It does not control switchgear, cooling, UPS equipment, breakers, or other facility equipment.

## Ideal partner and test host

A useful design partner operates NVIDIA GPU infrastructure and can provide one non-production or maintenance-window host with:

- Root or equivalent approved administrative access.
- A GPU/driver combination on which NVIDIA power-limit changes are supported.
- Timestamped, machine-readable whole-server power from IPMI, Redfish, or a metered PDU.
- A representative, interruptible test workload and an owner who can define its protection limits.
- An operator present for approval, observation, and immediate stop or rollback.

Production credentials should remain under the partner’s control. GridRudder should receive the least privilege needed for the agreed test.

## Entry criteria

The pilot begins only after all of the following are recorded:

1. Exact server, BMC, GPU, driver, OS, and workload configuration.
2. An approved test window, named operator, emergency stop, rollback steps, and backup or recovery expectations.
3. Baseline health checks and confirmation that independent server-power readings are available.
4. A declared workload contract with measurable guardrails such as latency, throughput, error rate, completion time, or job priority.
5. Agreed power-cap bounds; the tool may not exceed the original cap or go below the approved minimum.
6. Agreement on telemetry fields, retention, access, deletion, and permitted use. No cross-customer training or publication without separate consent.

If any entry criterion is missing, run the simulator or a read-only probe instead of a write trial.

## Execution

1. Capture an idle and loaded baseline using GPU telemetry and the independent server meter.
2. Run a read-only compatibility probe and archive its results.
3. Obtain an explicit, attributable approval for the bounded trial.
4. Apply one conservative power-limit step while the test workload runs.
5. Observe power, workload guardrails, hardware health, and telemetry freshness.
6. Stop and restore immediately on a guardrail breach, stale or conflicting data, operator request, agent failure, or unexpected host behavior.
7. Restore the original GPU state, verify workload and host health, and cryptographically preserve or otherwise protect the audit artifact from accidental modification.
8. Review results jointly before considering any longer or broader experiment.

## Evidence and success criteria

A successful pilot requires all of these outcomes:

- Original GPU settings and relevant service state are restored and verified.
- The independent meter shows a repeatable change in whole-server watts relative to a comparable baseline; GPU-reported watts are supporting evidence only.
- The declared workload guardrails remain satisfied during the evaluated interval.
- Every proposed and applied action records timestamp, host/GPU identity, inputs, policy decision, approval identity, result, and restoration outcome.
- Fault-injection tests demonstrate safe behavior for stale telemetry, collector failure, command failure, agent interruption, and restart.
- The partner can remove the agent and retain/export the audit evidence.

Power reduction, workload impact, and response time must be reported as measured ranges with the test configuration and sample size. A single successful host proves only that configuration. It does not establish fleet-wide savings or production readiness.

## Stop criteria

Stop the write trial and restore state if workload protection is breached, independent telemetry becomes unavailable or stale, the requested state differs from the approved bounds, hardware health degrades, rollback cannot be verified, or the partner asks to stop. An unresolved restoration failure ends the pilot and requires operator remediation before any further test.

## Pilot stages

- **Stage 0 — simulator:** replay partner-shaped workloads without hardware writes.
- **Stage 1 — read only:** validate collectors, clocks, identity, audit output, and baseline variance.
- **Stage 2 — attended single host:** one bounded step and immediate restoration.
- **Stage 3 — extended supervised host:** repeated trials and fault recovery over an agreed test window.
- **Stage 4 — limited multi-host evaluation:** only after Stage 3 passes on each hardware class and a separate review approves the expansion.

No stage automatically authorizes the next one.

## What the partner receives

- The Apache-2.0 local agent, simulator, safety logic, audit formats, and verification tooling available in this repository.
- A compatibility report and a joint pilot report containing configuration, method, results, limitations, incidents, and unresolved risks.
- Exportable raw evidence and a removal/rollback procedure.
- A written proposal before any paid hosted-control-plane or support engagement.

## What GridRudder learns

With explicit permission, GridRudder may record adapter gaps, non-sensitive hardware compatibility facts, aggregate performance ranges, and operator workflow feedback. Customer identifiers, workloads, credentials, raw telemetry, and commercial terms remain confidential unless the partner separately agrees otherwise.

## Readiness beyond the first host

One server is sufficient to demonstrate the mechanism, not to go to market as production-ready software. Before broader claims, target validation across at least two server/BMC implementations, multiple NVIDIA GPU generations, one multi-GPU host, one partner-controlled environment, and sustained fault/recovery testing. These are planning targets rather than certifications; results and remaining gaps must be published honestly.
