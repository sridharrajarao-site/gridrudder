# Hardware Gate Checklist

Owner: Assurance Council  
Decision authority: Chief Architect and accountable site owner  
Purpose: Prevent simulator confidence from being mistaken for authorization to control physical GPUs.

No unchecked item is implicitly waived. A waiver requires an ADR stating the risk owner, rationale, compensating control, expiration, and rollback. Any stop condition overrides a prior go decision.

## Gate 0 — Read-only rental qualification

This gate permits telemetry collection only. It does not permit a GPU power-limit
or persistence-mode write.

- [ ] Rental owner confirms the machine is dedicated bare metal and identifies the authorized host.
- [ ] Expected DMI host identity, BMC FRU chassis serial, GPU UUID, BMC meter ID, and physical measurement boundary are recorded out of band.
- [ ] NTP/chrony reports synchronized time; maximum accepted skew and ingest latency are approved.
- [ ] Absolute `nvidia-smi` and `ipmitool` paths are regular, root-owned, executable, not group/world writable, and their SHA-256 digests are recorded.
- [ ] Collector service identity has read-only BMC access and no facility-equipment credentials.
- [ ] At least three NVIDIA and BMC observations pass freshness, quality, ordering, host/meter binding, and alignment validation.
- [ ] Raw command outputs and the qualification packet are retained without credentials or customer workload data.
- [ ] The deployed qualification artifact contains no reachable GPU write command.

Decision: **GO / NO-GO for read-only qualification only**  
Architect: ____________________ Date: __________  
Rental owner: _________________ Date: __________

## Gate 1 — Hardware-in-the-loop readiness

Required before connecting an actuator adapter to physical GPU hardware:

- [ ] Simulator acceptance suite passes on nominal, adversarial, and injected-failure traces.
- [ ] Protected workloads are the default; unknown or incompletely labeled workloads cannot be actuated.
- [ ] Independent policy guard rejects actions outside device, site, event-duration, ramp, and recovery bounds.
- [ ] Adapter commands are authenticated, idempotent, expiring, rate-limited, and attributable.
- [ ] Controller lease/fencing prevents two controllers from commanding the same target.
- [ ] Loss of meter, GPU telemetry, scheduler, database, network, or controller reaches the documented safe state.
- [ ] Exact vendor-supported power-cap range is documented for each intended GPU model.
- [ ] Restore behavior is explicit: validated safe cap or gradual return to validated default.
- [ ] Emergency stop works independently of the primary controller path.
- [ ] Audit chain records request, approval, decision, command, observation, failure, and recovery.
- [ ] Rollback and backup/restore have been tested from the intended build artifact.

Decision: **GO / NO-GO**  
Architect: ____________________ Date: __________  
Assurance owner: ______________ Date: __________

## Gate 2 — Isolated physical lab

Required conditions:

- [ ] Hardware is isolated from production tenants and runs only synthetic or explicitly expendable workloads.
- [ ] Site/hardware owner gives written permission to observe telemetry and change GPU power caps.
- [ ] Independent host/PDU meter is installed, calibrated for engineering use, and time-aligned with GPU telemetry.
- [ ] GPU temperature, throttling reason, device health, host health, and meter power are visible during every test.
- [ ] Local operator is present, trained, and able to invoke emergency stop and manual restore.
- [ ] Network targets and service identities are allowlisted and least-privileged.
- [ ] Release artifact, configuration, policy, adapter, and dependency versions are pinned and recorded.
- [ ] Maximum initial action is the smallest observable cap change, on one GPU, for a short bounded duration.
- [ ] No write access exists to breakers, relays, switchgear, UPS transfer logic, batteries, generators, cooling, or BMS.

Required demonstrations, in order:

- [ ] Read-only telemetry matches the independent reference closely enough for declared engineering tolerances.
- [ ] Dry-run recommendation produces no hardware change.
- [ ] One supervised cap action stays within the vendor/site bound and expires correctly.
- [ ] Observed meter response and workload effect are recorded and compared with prediction.
- [ ] Controller loss, network partition, stale telemetry, scheduler outage, and adapter restart produce safe outcomes.
- [ ] Emergency stop and manual restoration work during an active bounded action.
- [ ] Multi-GPU actions preserve policy bounds and do not oscillate.
- [ ] Gradual recovery remains under the configured rebound ceiling.
- [ ] Soak test completes without unexplained actuation, audit gaps, memory/resource leak, or device-health degradation.

Immediate lab stop conditions:

- Uncommanded actuation or action on the wrong GPU.
- Vendor/hardware bound, site limit, thermal limit, or recovery ceiling violation.
- Protected-workload interruption or unexplained workload corruption.
- Loss of trustworthy meter/telemetry during actuation.
- Audit-write failure or inability to identify who/what issued a command.
- Emergency stop or restore path does not work immediately as designed.
- Abnormal temperature, error counter, driver reset, host instability, smoke, odor, or facility alarm.

Decision: **GO / NO-GO**  
Chief Architect: _______________ Date: __________  
Site owner: ____________________ Date: __________  
Security owner: _________________ Date: __________

## Gate 3 — Shadow pilot readiness

Shadow mode is observational: the system may read approved telemetry and issue recommendations, but it has no actuator credentials.

- [ ] Lab characterization is repeatable and documents prediction confidence and limits.
- [ ] Named sponsor, site operations owner, workload owner, security owner, and incident commander exist.
- [ ] Pilot scope names site, cluster, data sources, target workloads, dates, success metrics, exclusions, and stop criteria.
- [ ] Data-flow/network diagram and exact target inventory are approved.
- [ ] Tenant data is minimized/aliased; retention, access, export, and deletion terms are agreed.
- [ ] Service identities, certificates, secret rotation, segmentation, logging, and incident response pass security review.
- [ ] Site-specific protected/flexible workload classifications are reviewed by workload owners.
- [ ] Meter source, sampling, time synchronization, quality flags, and baseline method are documented.
- [ ] Recommendation logic includes magnitude, duration, predicted effect, confidence, constraints, and recovery plan.
- [ ] Operator dashboards show target, observed power, telemetry freshness, workload/SLO health, and recommendation status.
- [ ] Deployment, upgrade, rollback, outage, credential-expiry, and contact runbooks are exercised in a tabletop.
- [ ] Contract and communications call this engineering validation, not utility settlement or autonomous control.

Shadow exit criteria:

- [ ] Representative observation period includes normal peaks, troughs, workload changes, and dependency degradation.
- [ ] Power predictions meet the architect/site-approved error threshold on held-out events.
- [ ] Recommendations never select protected or unknown workloads.
- [ ] Telemetry confidence correctly inhibits recommendations when evidence is stale or inconsistent.
- [ ] Every recommendation is reproducible from its versioned inputs, policy, and audit record.
- [ ] Residual risks and model limitations are accepted by named owners.

Decision: **GO / NO-GO**  
Chief Architect: _______________ Date: __________  
Site owner: ____________________ Date: __________  
Workload owner: ________________ Date: __________  
Security owner: _________________ Date: __________

## Gate 4 — Limited active pilot consideration

This gate is included to bound the shadow phase; passing it requires a separate architect decision and is not granted by this checklist alone.

- [ ] Shadow exit criteria pass under representative conditions.
- [ ] Actuation is restricted to explicitly opted-in, noncritical workloads and allowlisted GPUs.
- [ ] Human approval is required for every event.
- [ ] Admission control and bounded power caps are the only initial actions.
- [ ] Checkpoint/pause remains disabled until separately characterized and approved.
- [ ] Event magnitude, duration, ramp down/up, cooldown, and recovery ceiling are site-configured and independently guarded.
- [ ] Staffed monitoring, change freeze, local emergency stop, incident commander, and rollback window are confirmed per event.
- [ ] The exact release is signed, pinned, recoverable, penetration/security reviewed, and observed end to end.
- [ ] Liability, insurance, data use, public claims, and incident notification obligations are agreed in writing.
- [ ] Chief Architect, site owner, workload owner, and security owner sign the specific active-pilot plan.

Automatic or unattended dispatch, facility-equipment write control, utility settlement claims, and production critical-workload interruption remain **NO-GO**.

## Evidence packet

Attach to each decision:

- [ ] Architecture decision and current risk register.
- [ ] Release/SBOM identifiers and signed build provenance.
- [ ] Configuration, policy, target inventory, and identity/permission export.
- [ ] Test report with raw-data references and known limitations.
- [ ] Meter/time-synchronization calibration evidence.
- [ ] Threat model, security findings, exceptions, and remediation status.
- [ ] Failure-injection, emergency-stop, restore, and rollback evidence.
- [ ] Runbooks, contact tree, training/tabletop record, and signed approvals.
