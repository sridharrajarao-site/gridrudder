# GridRudder open-source strategy

## Decision

Release this repository under the Apache License 2.0 and build GridRudder as an open-core product. The software installed beside customer GPUs must be inspectable, usable without a hosted service, and safe to remove. The commercial product should earn its value at fleet scale rather than by hiding local hardware commands.

This document describes a product boundary, not a promise that every future feature will be open source. Each repository and release must carry its own license.

## Open source in this repository

- The local node agent and read-only NVIDIA and power collectors.
- The deterministic simulator, scenarios, benchmarks, and replay tools.
- Workload contracts, bounded safety guards, restoration behavior, and the
  hardware-free attended performance-trial contract. Physical adapters require
  a separate hardware-gate review.
- Local policy evaluation and single-host control primitives that can operate without a GridRudder cloud account.
- The JSONL audit schema, verification tools, compatibility probes, test fixtures, and documented interfaces.
- Documentation needed to build, test, inspect, and self-host those components.

These components are licensed under Apache-2.0. That permits commercial use, modification, and redistribution subject to the license. It does not grant rights to GridRudder names or logos.

## Future commercial product

The following are intended for a separately licensed, hosted fleet control plane and are not implied to exist in this repository today:

- Multi-tenant fleet inventory, identity, access control, and centralized policy rollout.
- Cross-cluster scheduling and fleet-level power optimization.
- Managed telemetry retention, dashboards, alerting, reporting, and service-level operations.
- Utility, demand-response, carbon, energy-market, and enterprise platform integrations.
- Compliance evidence packages, approval workflows, support, and managed deployments.
- Proprietary optimization models trained from aggregated operational results, subject to customer data agreements.

Open formats are deliberate: customers should be able to export their data and verify a decision even when using the commercial service. The hosted service may use the open agent, but deploying the agent does not enroll a machine or transmit telemetry without explicit configuration.

## Safety and claims policy

Current GridRudder software is lab-stage, simulator-first software. It is not an electrical protection system, a replacement for facility controls, or certified for unattended production operation. Public language must use terms such as “supervised pilot,” “attended hardware trial,” and “measured result on tested hardware.” It must not claim autonomous data-center control, universal hardware support, guaranteed savings, or production readiness.

Write actions must remain opt-in, bounded, attributable, auditable, and reversible. Independent power telemetry is required to claim a physical power response. GPU telemetry alone is not proof of whole-server or facility impact.

## Business rationale

Opening the machine-side layer reduces a design partner’s security and lock-in concerns, makes hardware compatibility work reproducible, and lets operators contribute adapters. The defensible commercial value is the accumulated compatibility knowledge, integrations, fleet coordination, operational reliability, and evidence that optimization respects workload constraints.

## Governance before a public release

Before accepting outside contributions:

1. Confirm ownership of all committed code and documentation and remove material without compatible provenance.
2. Add contribution guidelines, a code of conduct, a security reporting route, and a lightweight Developer Certificate of Origin process.
3. Define versioned compatibility and audit schemas, release signing, and a supported-hardware matrix.
4. Run secret, dependency, license, and security scans and publish known limitations.
5. Obtain legal review of the open-core structure, trademark use, privacy terms, pilot agreement, and any telemetry collection. This document is not legal advice.

## Decision checkpoints

Revisit the boundary after three design-partner pilots. Keep interfaces and verification formats open. Move a capability into the commercial layer only when its primary value is operating a shared fleet service—not merely to make the local agent less useful.
