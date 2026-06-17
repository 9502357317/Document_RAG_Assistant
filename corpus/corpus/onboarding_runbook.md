# New Engineer Onboarding Runbook

Welcome. Follow these steps in order on your first day. Most blockers come from
doing them out of order, so do not skip ahead.

## Step 1 — Identity
Your manager files an access request that provisions your single sign-on (SSO)
identity. **Everything else depends on SSO**, so confirm you can log in to the
SSO portal before doing anything else. If login fails, email the support team.

## Step 2 — Repository access
Once SSO is active, request the `address-registry` repository through the access
portal and select the **read/write (contributor)** role. Read-only is the default
and will block you from pushing branches, so choose contributor explicitly.

## Step 3 — Local environment
| Tool        | Version  | Notes                                  |
|-------------|----------|----------------------------------------|
| Python      | 3.11+    | Use a virtual environment, not system  |
| Docker      | latest   | For the local Postgres and Chroma      |
| pre-commit  | latest   | Run `pre-commit install` after cloning |

## Step 4 — Secrets
Request a Vaultwarden collection invite. Never paste secrets into code, tickets,
or chat. A leaked secret must be reported to support within one hour.

## Step 5 — First task
Pick a ticket labeled `good-first-issue`, open a pull request, and request review.
Your onboarding is complete when that PR is merged.
