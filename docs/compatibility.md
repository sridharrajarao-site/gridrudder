# Compatibility and support status

This matrix reports what has been exercised; it is not a production hardware certification or support contract.

| Surface | Environment | Evidence | Status |
| --- | --- | --- | --- |
| Simulator, audit, policy, replay, fault matrices | Python 3.9+ standard library | Automated test suite and deterministic release tooling | Development-supported for safe local evaluation |
| NVIDIA discovery | Host with `nvidia-smi` | Read-only adapter tests plus environment-dependent probe | Read-only, capability reported fail-closed |
| Attended performance-trial contract | Injected control, workload, authorization, and meter adapters | Automated normal/failure/restoration tests | Hardware-free contract implemented; concrete physical adapters not supported |
| Historical physical mechanism observation | One rented NVIDIA RTX 2060 Super-class bare-metal host with independent BMC watts | Private, identifying audit evidence records a 175→125→175 W limit sequence, GPU 156.22→124.37 W, BMC host 291→260 W, and restoration | One observed configuration only; not a supported hardware class |
| Multi-GPU, MIG, clusters, schedulers, AMD, utility/facility equipment | None | No qualifying physical evidence | Unsupported and unclaimed |

## What “development-supported” means

Maintainers intend to keep documented simulator and verification commands working on declared Python versions and to fix reproducible defects as capacity permits. It does not include an SLA, warranty, production suitability, remote operation, or hardware actuation.

## Adding a compatibility observation

Use the compatibility issue template with model families and software versions only. Do not publish GPU UUIDs, serial numbers, asset tags, hostnames, IP addresses, credentials, customer/workload identifiers, or raw production traces. A maintainer must review provenance, authorization, independent-meter quality, workload evidence, and restoration before changing this matrix.

## Hardware support graduation

A hardware class cannot be labeled supported merely because `nvidia-smi -pl` succeeds. Graduation requires a reviewed adapter and least-privilege procedure, exact device and meter binding, representative useful-work guardrails, repeated independent whole-server measurements, fail-safe fault/restart testing, verified restoration/removal, and a written architect decision.

See [`design-partner-pilot.md`](design-partner-pilot.md) and [`hardware-gate-checklist.md`](hardware-gate-checklist.md).
