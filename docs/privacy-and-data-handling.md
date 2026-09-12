# Privacy and data handling

## Current local behavior

The open-source simulator and local tools are intended to run locally. The repository does not document or promise a hosted ingestion service, and installing the local agent must not enroll a host or enable telemetry upload. Any future network collection requires a separate, explicit configuration and privacy review.

The public pilot-intake form stores name, work email, organization, environment category, goal, and submission time solely to evaluate and respond to the request. The retention target is 90 days. The current implementation removes older records when a new submission is stored; the operations procedure also calls for a monthly cleanup. There is no confirmed scheduled deletion job enforcing a strict 90-day maximum, so low submission traffic or a missed manual cleanup can leave records longer. Applicants may request earlier deletion by emailing `pilot@gridrudder.com` and are instructed not to submit credentials, IP addresses, or other secrets. Public retention wording must reflect these limits until scheduled cleanup is implemented and verified.

## Data the tools may produce

Depending on the command and environment, artifacts may contain timestamps, GPU model and UUID, host or BMC identifiers, power readings, workload labels or guardrails, operator/approval identifiers, command outcomes, software versions, audit hashes, and file paths. These fields can reveal identity, infrastructure topology, capacity, schedules, or operational behavior even when they contain no password.

## Handling rules

- Collect only fields required for a declared test and document their purpose.
- Use role or pseudonymous actor identifiers in shareable evidence; keep the identity mapping separately access-controlled.
- Treat GPU UUIDs, hostnames, IP addresses, BMC identifiers, paths, and raw traces as sensitive infrastructure metadata.
- Never write passwords, private keys, tokens, payment data, customer payloads, or unrestricted command output into audit records.
- Store raw evidence with least-privilege access, encryption appropriate to the partner, and a defined retention/deletion date.
- Provide the partner an export and honor deletion obligations, subject to explicitly agreed legal or integrity requirements.
- Sanitize artifacts before committing, attaching to an issue, publishing, or using in a demonstration.
- Do not combine partner datasets, train models on them, publish results, or use customer names/logos without separate written permission.

## Design-partner agreement inputs

Before collection, record approved fields, controller/processor roles, storage region, access roles, subprocessors if any, retention, deletion verification, incident contact, export format, and permitted aggregate/public use. Legal counsel should review the resulting agreement and applicable privacy obligations; this document is not legal advice.

## Public examples

Prefer deterministic synthetic data. A real trial artifact requires a documented consent and sanitation decision. Removing a name alone may be insufficient because device UUIDs, exact timestamps, workload patterns, and rare hardware combinations can re-identify an environment.
