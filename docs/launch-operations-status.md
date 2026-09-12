# Launch operations status — 2026-09-12

## Verified

- Both GPU Mart orders were terminated/cancelled; no active rental remained.
- Site database retrieval works through the Sites database tools. `pilot_requests`
  contained one synthetic QA record and no real requests when checked today.
- Intake validates fields and consent, stores requests, and removes records older
  than 90 days when another request is submitted.
- Cloudflare reports the pilot forwarding rule active and its Gmail destination
  verified. A synthetic email test was sent; Cloudflare's activity log reported
  Forwarded. A separately visible Gmail inbox copy was not established.
- A daily read-only lead check is configured in the owner's local app, reporting
  new real leads here. This is not a site-native email notification integration
  or an always-on hosted service. Database storage alone is not notification.
- Restricted `/ops` and `/api/ops/pilots` surfaces now support current-request
  review and explicitly confirmed deletion of records older than 90 days. They
  reject all access until `PILOT_OPERATOR_USER_ID` matches the authenticated
  site-specific owner ID. Authorization is not inferred from sign-in alone.

## Needs completion

- Owner identity is configured outside source. Live owner sign-in reaches the
  operations page; anonymous API access returns 403 with private/no-store.
  Validate authorized record rendering after the final UI publication.
- Scheduled deletion is not configured. The operator cleanup action and
  opportunistic insert cleanup do not guarantee retention during quiet periods.
- Validate notifications on a real scheduled run; keep the local app available.
- Conduct the next GPU trial only after the integrated runner, authorization,
  workload, telemetry and restoration behavior pass review.

## First partner evaluation

Ask for the host class, available independent power telemetry, workload goal and
test window. Never request passwords or production secrets through intake.
Return a compatibility decision and proposed evidence plan first. A later
hardware test requires separate operator approval. Measure completed valid jobs,
latency/errors, whole-server energy per job, and baseline-to-restored drift.
