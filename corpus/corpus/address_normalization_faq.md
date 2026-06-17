# Address Normalization — Frequently Asked Questions

## Why does "3900 Main Street" and "3900 MAIN ST" show as the same record?
The normalizer uppercases all text and replaces the full street-suffix word with
its USPS abbreviation. "Street" becomes "ST", so both forms collapse to the same
canonical string "3900 MAIN ST". This is intentional — it prevents duplicate
records for the same physical address written in different styles.

## Why does "3900 MIAN ST" NOT match "3900 MAIN ST"?
The normalizer does not correct spelling errors. "MIAN" is a transcription typo
and the system treats it as a different string. A human reviewer must correct the
typo manually before the records will merge.

## What happens if I include a suite or unit number?
Suite and unit numbers are preserved as written but uppercased. "Suite 4" becomes
"SUITE 4". Two records with different unit numbers will not merge even if the
street line is identical.

## Does the normalizer handle PO Boxes?
Yes. "P.O. Box 441" normalizes to "PO BOX 441". The dots and the space are
stripped, and the whole string is uppercased.

## What is the USPS abbreviation for Parkway?
PKWY. So "1000 Innovation Parkway" normalizes to "1000 INNOVATION PKWY".

## What abbreviation is used for Drive?
DR. "45 Riverside Drive" normalizes to "45 RIVERSIDE DR".

## Can I look up other USPS suffix abbreviations?
The full table is in the address normalization spec. That document is the
authoritative reference; this FAQ only covers the most common questions.

## Why does the normalizer uppercase everything?
Consistent casing eliminates a common source of near-duplicates. Systems that
store "Main Street", "main street", and "MAIN STREET" as three different records
accumulate noise quickly. Uppercasing everything at ingest means the deduper only
has to compare one canonical form.
