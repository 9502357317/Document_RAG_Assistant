# Q3 Planning Meeting — Notes

**Date:** 2026-06-02   **Time:** 10:00-11:15   **Location:** Conf Room B / remote
**Facilitator:** Okafor   **Scribe:** Tran

## Attendees
Rivera, Okafor, Lindqvist, and Tran attended. Patel was invited but sent regrets
and will review the recording.

## Summary
The team reviewed roadmap priorities for the third quarter and agreed to focus on
reliability before shipping new features. The address-registry RAG work was
explicitly deprioritized to Q4 so the team can stabilize the ingestion pipeline
first. No postal addresses were discussed in this meeting.

## Decisions
- Freeze new feature work for the first three weeks of the quarter.
- Adopt a weekly error-budget review every Monday.

## Action items
| Owner      | Action                                             | Due       |
|------------|----------------------------------------------------|-----------|
| Rivera     | Write integration tests for the upload pipeline    | 2026-06-20|
| Okafor     | Draft the on-call rotation and circulate it        | 2026-06-13|
| Lindqvist  | Benchmark the vector store under 10k documents     | 2026-06-27|
| Tran       | Publish these notes and book the Q4 kickoff        | 2026-06-04|

## Parking lot
Reranker cost, a possible move to FAISS, and a customer request for SSO export
were noted but deferred to the Q4 kickoff.
