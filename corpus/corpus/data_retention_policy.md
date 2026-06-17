# Data Retention & Deletion Policy (v2.3)

Effective 2026-01-01. Supersedes v2.1. Owner: Platform & Compliance.

## Scope
This policy applies to records stored in the address registry and its audit log.
It does NOT cover marketing data, which lives in a separate system under its own
schedule.

## Retention schedule
| Record type                  | Retention period | After period      |
|------------------------------|------------------|-------------------|
| Active address record        | While account is open | Reviewed annually |
| Soft-deleted address record  | 90 days          | Hard-purged nightly |
| Merged duplicate (tombstone) | 1 year           | Anonymized        |
| Upload/extraction audit log  | 18 months        | Aggregated, raw rows dropped |
| RAG query log (rag_log)      | 30 days          | Deleted           |

A "soft delete" only sets a flag; the row is still on disk and recoverable until
the 90-day window closes, at which point the nightly purge job removes it
permanently. There is no recovery after a hard purge.

## Legal hold
If a record is placed under legal hold, all timers above are suspended for that
record until the hold is lifted. Holds are applied by Compliance only.

## Deletion requests
A verified account holder may request early deletion of their address records.
Honored requests are completed within 30 days and logged in the audit trail
(the log entry itself is retained per the schedule above).
