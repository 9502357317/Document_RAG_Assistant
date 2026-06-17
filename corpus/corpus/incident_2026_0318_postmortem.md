# Postmortem — Incident 2026-0318 (Slow Export)

**Severity:** SEV-3   **Status:** Resolved   **Author:** Rivera
**Duration:** 2026-03-18 09:12 to 11:40 UTC (2h 28m)

## Impact
The `/export` endpoint returned correct results but with response times of
45–90 seconds instead of the normal 2–4 seconds. No data was lost or corrupted.
Approximately 60 export requests were affected.

## Timeline (UTC)
| Time  | Event                                                              |
|-------|--------------------------------------------------------------------|
| 09:12 | Export response times spike; first user report                     |
| 09:25 | On-call paged; confirms slowness but not a full outage             |
| 09:50 | Database query plan inspection reveals a missing index             |
| 10:30 | Index added to staging; query time drops to 1.8 seconds            |
| 11:20 | Index deployed to production                                       |
| 11:40 | Response times return to normal; incident closed                   |

## Root cause
A migration deployed on 2026-03-17 added a `deleted_at` column to the address
table but did not add the corresponding index. The export query filters on
`deleted_at IS NULL`, which became a full table scan once the column existed.
Under normal load this added roughly 40 seconds to every export.

## What went well
The deterministic pipeline and RAG search endpoints were unaffected.
On-call identified the root cause quickly once database query plans were inspected.

## Action items
| Owner   | Action                                                    | Due       |
|---------|-----------------------------------------------------------|-----------|
| Rivera  | Add index lint rule to migration CI check                 | 2026-03-25|
| Tran    | Add export p95 latency alert at 10-second threshold       | 2026-03-25|
| Okafor  | Review all recent migrations for missing indexes          | 2026-04-01|
