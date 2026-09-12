# Threat model and scope

## System boundary

The open repository contains a simulator, policy and safety logic, audit tooling, read-only collectors, and a separately gated attended GPU hardware harness. It may observe GPU and independent whole-server power data and, only in the attended harness, request a bounded NVIDIA GPU power-limit change. Facility control equipment is outside the system boundary.

## Protected assets

- Workload availability, correctness, performance guardrails, and job priority.
- GPU and host health and the ability to restore original state.
- Operator authorization and the integrity of device/bounds selection.
- Credentials and administrative access used by operators.
- Telemetry confidentiality, integrity, freshness, ordering, and time alignment.
- Audit completeness, ordering, attribution, and tamper evidence.
- Customer identity, topology, workload metadata, and hardware identifiers.

## Trust boundaries and assumptions

- The operating system, NVIDIA driver/tooling, BMC or PDU, time source, and privileged operator are external dependencies and may fail or lie.
- GPU telemetry and the independent server meter are distinct sources; neither is assumed infallible.
- Root access is highly privileged. GridRudder does not make a compromised host trustworthy.
- Local audit hashing can reveal modification but does not by itself provide durable external timestamping, signer identity, or protection from deletion by root.
- Physical electrical protection, thermal protection, firmware safety, and facility interlocks remain authoritative.

## Threats considered

- Malicious or accidental commands targeting the wrong GPU or exceeding approved bounds.
- Command or argument injection through identifiers, paths, configuration, or subprocess output.
- Stale, missing, replayed, forged, unit-confused, or time-misaligned telemetry causing an unsafe decision.
- Partial failure after a write, including process termination, network loss, reboot, and restoration failure.
- Concurrent operators or controllers issuing conflicting requests.
- Audit suppression, reordering, modification, secret inclusion, or ambiguous actor identity.
- Privilege escalation, insecure credential storage, overbroad file permissions, and unintended network egress.
- Denial of service through high-cardinality input, excessive polling, full disks, or slow external commands.
- Privacy leakage through hostnames, IP addresses, GPU UUIDs, operator names, workload labels, or raw traces.

## Required mitigations

- Simulation/read-only defaults and physical writes isolated behind explicit enablement.
- Exact device identity, allowlisted command construction, validated numeric bounds, least privilege, and no shell interpolation.
- Independent-meter freshness and alignment checks; fail closed when evidence is missing or contradictory.
- Pre-state capture, bounded action, timeouts, idempotent restoration attempts, post-state verification, and operator stop procedures.
- Append-only, sequenced, attributable audit records with integrity verification and sanitized export.
- No default telemetry upload; any future egress must be explicit, authenticated, encrypted, documented, and disableable.
- Fault-injection coverage for collector, command, process, restart, and storage failures.

## Explicitly out of scope

- Direct control of switchgear, breakers, UPS, cooling, generators, PDUs, BMC firmware, clocks, or voltage.
- Defense after root, driver, firmware, BMC, or meter compromise.
- Autonomous production operation, universal GPU/server support, electrical-code compliance, or guaranteed energy savings.
- Security of a future hosted control plane, multi-tenant service, utility integration, or proprietary optimizer until those components exist and receive separate threat models.

## Open risks before public release

The repository has not yet documented a least-privilege deployment profile, completed an independent security review, or demonstrated durable off-host audit anchoring. Vulnerability reports use the interim private route documented in `SECURITY.md`. The release checklist treats these gaps honestly rather than implying they are solved.
