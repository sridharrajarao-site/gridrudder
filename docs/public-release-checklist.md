# Public release checklist

This checklist separates repository publication from claims of hardware or production readiness. Completing it does not certify GridRudder as safe for production.

## Licensing and provenance

- [x] Full Apache-2.0 license is present.
- [x] Open-source and future commercial boundaries are documented.
- [ ] Confirm copyright ownership and provenance for every committed file.
- [ ] Inventory dependency licenses and generated/vendor content.
- [x] Add a `NOTICE` file for project attribution and trademark clarification; revisit it after the provenance inventory.
- [ ] Obtain legal review of license, contribution terms, trademark, privacy, and pilot language.

## Repository sanitation

- [x] Exclude build output, dependency directories, nested repository metadata, editor files, caches, and private run artifacts through `.gitignore`, `.gitattributes`, and the source-package builder.
- [ ] Run secret scanning against the full files and complete history using an approved scanner; record tool/version and findings.
- [x] Scan the staged package for names, email addresses, phone numbers, street addresses, private IPs, GPU UUIDs, approval IDs, private-key markers, and common credential formats.
- [x] Exclude real physical evidence from the public package; retain only the deterministic synthetic demo artifact.
- [ ] Verify no credentials exist in reachable history, release assets, issues, CI logs, or documentation. Rotate any credential ever committed even if later removed.

## Security and safety

- [x] Threat/scope statement and pre-production limitations are documented.
- [x] Simulator/read-only quickstart is separate from the attended hardware harness.
- [x] Document interim private vulnerability and conduct routes through `pilot@gridrudder.com` with distinct subject prefixes.
- [ ] Document a least-privilege deployment profile and supported command allowlist.
- [ ] Complete independent code/security review, dependency scan, static analysis, and fault/recovery tests.
- [ ] Define signed releases, protected branches, required reviews, and artifact provenance.

## Community and interfaces

- [x] Contribution and conduct expectations are documented.
- [ ] Enable and document Developer Certificate of Origin sign-off checks.
- [ ] Add issue and pull-request templates that route security issues privately.
- [ ] Version public audit, intake, and compatibility schemas and define compatibility policy.
- [ ] Publish maintained hardware support and known-limitations matrices.

## Pilot readiness

- [x] Offline intake questionnaire/schema and privacy handling note exist.
- [x] Pilot entry, stop, rollback, evidence, and success criteria exist.
- [ ] Approve a pilot agreement covering authority, access, data, confidentiality, incident handling, liability, and publication consent.
- [ ] Exercise install, stop, restoration, removal, deletion, and evidence-export procedures on each claimed hardware class.

## Sanitation scan recorded 2026-09-12

The initial local pattern scan found no private-key, password, token, address, or phone indicators in the intended core source/document set. It is not a substitute for a history-aware secret scanner.

Release blockers found:

1. The private physical-trial evidence contains a real operator identifier, exact timestamps, approval identifier, and GPU UUID. It is immutable evidence and was not rewritten. The package builder excludes it; publish only a separately generated, consented and sanitized derivative while preserving the original privately.
2. `site/.git/logs/HEAD` and `site/.git/logs/refs/heads/main` matched email-address indicators. Nested `.git` metadata must never be included in a release archive. The site directory was outside this hardening task and was not modified.
3. `site/node_modules/` exists locally. Dependency/build trees must be excluded from source publication; their presence also made filename-only scans report third-party files with words such as “secret” or “credentials.”
4. Private reports route to `pilot@gridrudder.com`. Mailbox access control, primary/backup ownership, and response drills remain operational tasks.
5. No existing Git history is included in the source package. A future hosting repository must begin from the sanitized package or complete a separate history-level credential and PII review before importing history.

## Local publication package

Run `python3 tools/build_public_release.py` from the repository root. It copies only allowlisted source, refuses unsafe source types, scans both source and staging trees, writes `PUBLIC_RELEASE_MANIFEST.sha256`, and creates `dist/gridrudder-public-preview.tar.gz` plus its sidecar checksum. It never rewrites or copies private physical evidence, nested `.git` metadata, dependency trees, build/deployment state, or caches.

## Release decision

Do not publish until every unchecked security, sanitation, provenance, and reporting item required for the chosen preview is assigned and resolved or explicitly accepted in a written release decision. Public repository availability is not permission to run the hardware harness.
