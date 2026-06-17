# Postmortem — Incident 2026-0207 (Search Outage)

**Severity:** SEV-2   **Status:** Resolved   **Author:** Lindqvist
**Duration:** 2026-02-07 13:58 to 15:46 UTC (1h 48m)

## Impact
The `/rag/search` and `/ask` endpoints returned 503 errors for roughly 1h 48m.
Uploads and deterministic extraction were unaffected. About 410 search requests
failed during the window.

## Timeline (UTC)
| Time  | Event                                                            |
|-------|------------------------------------------------------------------|
| 13:58 | Embedding service starts returning TLS handshake errors          |
| 14:05 | First customer report; on-call paged                             |
| 14:20 | On-call confirms the embedding model endpoint cert is expired    |
| 14:55 | Rotated certificate deployed to staging and verified             |
| 15:30 | Certificate rolled to production                                 |
| 15:46 | Error rate returns to zero; incident closed                      |

## Root cause
The TLS certificate on the internal embedding endpoint expired and auto-renewal
had silently failed three days earlier because the renewal job lost its
credential after an unrelated secret rotation. With no valid certificate, every
embedding call failed, so search and ask could not run.

## What went well
The deterministic pipeline kept uploads working, so no data was lost.

## Action items
| Owner     | Action                                              | Due       |
|-----------|-----------------------------------------------------|-----------|
| Lindqvist | Add a cert-expiry alert at 14 days remaining        | 2026-02-14|
| Okafor    | Make renewal-job failures page on-call              | 2026-02-21|
| Rivera    | Add a retry-with-cached-embeddings fallback to /ask | 2026-03-06|
