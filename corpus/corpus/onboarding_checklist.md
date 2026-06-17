# New Engineer Onboarding Checklist

A companion to the onboarding runbook. Use this to track your progress through
the first week. Mark each item complete before moving on.

## Day 1
- [ ] Confirm SSO login works
- [ ] Request `address-registry` repository access (contributor role)
- [ ] Clone the repository and run the test suite locally
- [ ] Complete the mandatory security awareness module in the learning portal
- [ ] Attend the new-starter briefing with your manager

## Day 2
- [ ] Request Vaultwarden collection access from your manager
- [ ] Set up the local development environment (Python, Docker, pre-commit)
- [ ] Run `pre-commit install` in the repository root
- [ ] Confirm you can start the local stack with `docker compose up`

## Day 3–5
- [ ] Read the architecture overview in ARCHITECTURE.md
- [ ] Shadow a code review for an open pull request
- [ ] Pick a `good-first-issue` ticket and create a branch
- [ ] Open a draft pull request and request early feedback

## Access you should have by end of week 1
| System            | Access level        | How to request              |
|-------------------|---------------------|-----------------------------|
| GitHub repo       | Contributor         | Access portal               |
| Vaultwarden       | Team collection     | Ask your manager            |
| CI dashboard      | Read-only           | Automatic on repo access    |
| Staging environment | Developer         | Access portal, same as repo |

## Common blockers
If your `pre-commit` hooks fail on the first run, make sure you activated your
virtual environment before running `pre-commit install`. The hooks require the
dev dependencies to be installed.

If Docker fails to start the Postgres container, check that port 5432 is not
already bound on your machine. Stop any locally installed Postgres service first.
