# Address Normalization Spec

The normalizer converts free-text addresses into a canonical postal form so that
duplicates collapse to one record. This is the contract the deduper relies on.

## Canonical rules
1. Uppercase the entire address.
2. Trim repeated whitespace to a single space.
3. Replace common street-suffix words with their USPS standard abbreviation
   (see table). Apply this only to the suffix position, never inside a name.
4. Drop trailing punctuation (periods, commas) from each line.

## USPS suffix abbreviations
| Full word | Abbreviation |
|-----------|--------------|
| Street    | ST           |
| Avenue    | AVE          |
| Boulevard | BLVD         |
| Drive     | DR           |
| Lane      | LN           |
| Parkway   | PKWY         |

So "3900 Main Street" normalizes to "3900 MAIN ST", which is why the Riverside
letter and the address-update notice collapse to the same record even though one
is written long-form and the other abbreviated.

## What it does NOT do
The normalizer does not correct misspellings. "3900 MIAN ST" stays misspelled and
will NOT match "3900 MAIN ST"; fixing transcription typos is a separate,
human-reviewed step. It also never invents a ZIP+4 that was not present.
