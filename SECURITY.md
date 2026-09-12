# Security policy

## Current support status

GridRudder is pre-production, lab-stage software. No released version is currently designated for production or unattended operation. Until a public versioning policy is published, only the current default branch is eligible for security fixes.

## Reporting a vulnerability

Do not open a public issue for a vulnerability, suspected credential exposure, unsafe control path, or method to bypass approval, bounds, audit, or restoration behavior.

Email `pilot@gridrudder.com` with a subject beginning `[SECURITY]`. Do not put credentials, personal data, customer telemetry, or weaponized exploit material in the initial message. Ask for an access-controlled transfer method if sensitive attachments are necessary. If the mailbox does not acknowledge the report, do not disclose it publicly merely to get attention.

Do not test against systems you do not own or lack explicit authorization to assess. Do not include credentials, personal data, customer telemetry, or exploit details beyond what is necessary to reproduce safely.

## High-priority security boundaries

Reports are especially useful when they concern:

- GPU write execution without explicit operator enablement or attributable approval.
- Wrong-device selection, power limits outside approved bounds, or failed restoration.
- Acceptance of stale, forged, misaligned, or conflicting telemetry.
- Audit-chain tampering, omission, replay ambiguity, or secret leakage.
- Command injection, privilege escalation, unsafe subprocess handling, or excessive permissions.
- Unexpected network transmission or collection beyond documented data handling.

## Disclosure

Maintainers will coordinate remediation and disclosure with reporters through the reporting channel. This file offers no bug bounty, safe-harbor agreement, service-level commitment, or permission to access third-party systems.
