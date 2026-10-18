# Epic 14 — Research Decisions

Version: 0.33.0

## Google Ads production access

Recovery OS treats Google Ads production API access and restricted OAuth verification as external launch evidence. A staging/test account can prove integration behavior but cannot prove real serving economics; the final production acceptance therefore requires a read-only probe against a non-test account and forbids mutation as part of the probe.

## Razorpay go-live

Public launch requires live merchant activation and a verified live webhook path as external evidence. Browser checkout success remains non-authoritative; existing server-side provider reconciliation continues to control entitlement.

## Terms and Privacy identity

The active legal policy versions are backend configuration, not frontend configuration. This avoids a deployment where the browser shows one policy version while the API records another. Public production readiness requires HTTPS legal URLs and explicit non-empty version identifiers.

## Public signup abuse controls

The launch gate requires separate evidence that production signup-abuse controls are configured and exercised. Recovery OS does not label the existence of authentication alone as abuse protection. Provider-level controls such as rate limits/CAPTCHA must be verified in the deployed environment and captured as external evidence.

## Launch is reversible without deleting customers

Closing launch means stopping creation of new workspaces. It does not destroy existing tenants or revoke their access. Consequential product writes remain governed by their independent tenant kill switches and provider reconciliation contracts.
