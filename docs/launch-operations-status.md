# Launch operations status — 2026-09-12

## Verified

- Both GPU Mart orders were terminated/cancelled; no active rental remained.
- Site database retrieval works through the Sites database tools. `pilot_requests`
  contained one synthetic QA record and no real requests when checked today.
- Intake validates fields and consent, stores requests, and removes records older
  than 90 days when another request is submitted.
- The form currently has no email-notification integration. Database storage is
  not evidence that an operator received a notification.

## Needs completion

- Cloudflare sign-in is required to inspect the forwarding rule and verified
  destination for `pilot@gridrudder.com`.
- Confirm end-to-end delivery using an authorized test message. No new message
  was sent during this check; an empty Gmail search is inconclusive.
- Establish an authenticated lead-review and notification path before outreach.
- Assign monthly retention review and a deletion execution path. Opportunistic
  cleanup on inserts alone does not enforce retention during quiet periods.
- Conduct the next GPU trial only after the integrated runner, authorization,
  workload, telemetry and restoration behavior pass review.

## First partner evaluation

Ask for the host class, available independent power telemetry, workload goal and
test window. Never request passwords or production secrets through intake.
Return a compatibility decision and proposed evidence plan first. A later
hardware test requires separate operator approval. Measure completed valid jobs,
latency/errors, whole-server energy per job, and baseline-to-restored drift.
