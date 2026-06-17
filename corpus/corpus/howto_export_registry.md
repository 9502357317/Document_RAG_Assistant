# How To: Export the Address Registry

This guide explains how to pull a snapshot of the live address registry.

## Quick export
To export every live address as a spreadsheet, call the export endpoint:

    GET /export?format=csv

The endpoint streams a CSV download containing all addresses that are **not
deleted** and **not merged**. Merged duplicates resolve to their surviving
record, so you never get the same physical address twice.

## Filtering the export
The export respects any filters currently applied. Combine query parameters to
narrow the result:

| Parameter | Example          | Effect                                  |
|-----------|------------------|-----------------------------------------|
| `city`    | `city=Riverside` | Only addresses in that city             |
| `state`   | `state=CA`       | Only addresses in that state            |
| `zip`     | `zip=92522`      | Exact ZIP match                         |
| `q`       | `q=main+street`  | Free-text search across the street line |

Example: `GET /export?format=csv&state=CA&city=Riverside` returns only the
Riverside, California rows. Open the downloaded file in any spreadsheet app.

## Notes
JSON output is available with `format=json`. Exports are rate-limited to 5 per
minute per user to protect the database.
