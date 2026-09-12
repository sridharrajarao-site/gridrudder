# GridRudder launch-readiness ledger

Date: 2026-09-12

This ledger reconciles the commitments made during the prototype, hardware-validation, open-source, website, and go-to-market work with artifacts that exist now. “Done” means evidenced, not production-ready. Repository-publication status was refreshed after the original review on 2026-09-12.

## Executive state

GridRudder has a credible simulator-first safety core, a single-host physical mechanism result, an Apache-2.0 repository public at [github.com/sridharrajarao-site/gridrudder](https://github.com/sridharrajarao-site/gridrudder), and a design-partner website/intake implementation. It does not yet have a repeatable supported hardware integration, validated workload-performance results, a design partner, or a hosted fleet control plane. The honest market offer remains a supervised design-partner evaluation.

## Priority 0 — must resolve before accepting public submissions or hardware pilots

| Commitment or claim | Evidence now | State | Required closure |
| --- | --- | --- | --- |
| Keep applicant data no more than 90 days and delete earlier on request | Website form and D1 schema store intake records; privacy text makes the promise | **Gap** | Implement and test scheduled deletion, deletion-request execution, access ownership, and deletion evidence—or remove the time-bound claim before collecting data. |
| Private security/conduct contact | `SECURITY.md` and `CODE_OF_CONDUCT.md` route subjects to `pilot@gridrudder.com` | **Partial** | Verify mailbox delivery, restrict access, name primary/backup responders, and run response drills. Do not invent an unconfigured `security@` address. |
| Safe, repeatable physical integration | `gridgpu/performance_trial.py` binds authorization, host/GPU/workload/meter identity, uses repeated samples and locking, and verifies restoration; tests cover major failure paths | **Partial** | Build and review concrete NVIDIA and BMC adapters, an operator runbook, install/removal procedure, and exercise this new boundary on hardware. The prior physical artifact came from an earlier harness and does not validate the new boundary. |
| Public claims trace to evidence | Private audit records 156.22→124.37 GPU W, 291→260 host W, 175→125→175 W limit, and restoration on one trial | **Partial** | Keep raw evidence private. Produce a consented sanitized evidence packet. Do not claim application throughput, identical useful work, fleet savings, or production safety. GPU model and utilization require a separate preserved source because they are absent from this audit. |

## Priority 1 — required for a credible public preview

| Commitment | Evidence now | State | Required closure |
| --- | --- | --- | --- |
| Release open components under Apache-2.0 | `LICENSE`, `NOTICE`, open-core boundary, contribution/security/conduct docs, safe quickstart, and the [public repository](https://github.com/sridharrajarao-site/gridrudder) | **Published** | Legal/provenance review and signed release provenance remain. Public source availability does not imply production support or that future hosted components are open source. |
| Publish a sanitized repository | The sanitized source is public at [github.com/sridharrajarao-site/gridrudder](https://github.com/sridharrajarao-site/gridrudder); `.gitignore`, `.gitattributes`, and `tools/build_public_release.py` exclude private evidence, nested Git state, dependencies, build output, deployment metadata, and caches | **Published** | Continue history-aware secret/provenance review and verify each release manifest. Do not import unscanned nested history or private evidence. |
| Consistent public name and domain | ADR-0003 accepts GridRudder; README and active launch docs use it; site canonical uses `https://gridrudder.com` | **Partial** | Verify registration, DNS, TLS, production routing, and formal trademark clearance externally. Historical naming ADRs remain intentionally unchanged. |
| Accurate automated-test claim | The site no longer publishes a volatile numeric suite count. The 209-test result below is a dated 2026-09-12 record, not a current total or hardware claim. | **Closed in site copy** | Keep dated test records immutable; derive any future current count during release rather than hard-coding it in marketing copy. |
| Website release verification | The production proof-brief source has GridRudder-specific rendered assertions for evidence qualifiers, control boundaries, intake/privacy, and metadata; its promotion build, lint, and rendered tests passed locally | **Passing locally** | Require the same checks in CI and re-run them against the deployed production artifact. |
| Installable open-source product | Repository runs from source with Python 3.9+ and no core third-party packages | **Partial** | Add packaging metadata, versioning, reproducible installation, upgrade/removal docs, release signing, and CI. There is no supported daemon/service package yet. |

## Priority 2 — required before broader go-to-market claims

| Commitment | Evidence now | State | Required closure |
| --- | --- | --- | --- |
| Recruit 3–5 design partners and offer a free supervised trial | Website form, offline intake schema, pilot stages, success/stop criteria | **Not started externally** | Approve commercial/legal pilot terms, qualify partners, and conduct outreach only with authorization. No design partner is evidenced locally. |
| Validate heterogeneous hardware | One RTX 2060 Super-class trial was described; private audit proves one GPU/device and one independent BMC response | **Not enough** | Test multiple NVIDIA generations, at least two server/BMC implementations, a multi-GPU host, and a partner-controlled environment. Publish exact compatibility, not extrapolation. |
| Approximately 100 hours of fault/recovery testing | Extensive deterministic software fault tests exist | **Not done on hardware** | Define the protocol and complete sustained supervised hardware fault/recovery testing. Simulator tests do not substitute for elapsed physical testing. |
| Protect useful workload, not utilization alone | New performance-trial boundary measures useful units, duration, energy, and joules per unit | **Implemented but unvalidated physically** | Run representative applications with latency/throughput/error guardrails and comparable repeated baselines. The first trial did not measure useful work. |
| Choose Kubernetes or Slurm integration from partner need | Scheduler-neutral architecture documented | **Deferred correctly** | Select exactly one after a credible partner supplies requirements; do not build speculative dual adapters. |
| Offer a commercial hosted fleet control plane | Open-core boundary describes multi-tenant fleet policy, optimization, dashboards, integrations, compliance, and support as future commercial scope | **Not built** | Customer discovery, service architecture, tenancy/security/privacy threat models, operations, billing, and product validation remain. Do not present future scope as available software. |

## Delivered artifacts

- Deterministic simulator, policy/safety logic, replay, audit verification, fault matrices, release evidence, and a historical record of 209 passing Python tests on 2026-09-12. This is not the current suite total.
- Read-only NVIDIA probe and disabled legacy hardware-trial CLI.
- Library-level attended performance boundary with scoped authorization and restoration safeguards.
- One private physical audit artifact proving a bounded change and independent host-watt response on one trial.
- Apache-2.0 license and open-core strategy.
- Contribution, security, conduct, privacy, threat-model, quickstart, design-partner intake, and pilot documents.
- GridRudder website source, intake API/schema, and local hosting configuration.
- Fail-closed local public-source package builder and hash manifest.

## Explicit non-deliveries

- No signed immutable public release or supported binary distribution exists; source is public at [github.com/sridharrajarao-site/gridrudder](https://github.com/sridharrajarao-site/gridrudder).
- No design-partner outreach was performed in this workstream.
- No production or autonomous control system exists.
- No facility-equipment control path exists.
- No fleet-wide savings, workload-neutrality, compatibility, or production-readiness claim is supported.
- No hosted commercial fleet control plane exists.

## Next decision sequence

1. Close intake retention and mailbox operations before collecting public submissions.
2. Produce a reviewed, consented public evidence packet without reintroducing a volatile test-count claim.
3. Continue provenance/legal/trademark review of the public repository and establish signed release artifacts.
4. Productize and run the new performance boundary on the current lab host, then one partner-controlled host.
5. Use partner requirements to choose one scheduler integration and define the smallest paid hosted-control-plane slice.
