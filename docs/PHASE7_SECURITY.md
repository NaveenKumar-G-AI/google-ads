# Phase 7 security boundary

This phase deliberately keeps Google credentials outside the repository.

- Never commit the service-account private key, OAuth refresh/access tokens, `google-ads.yaml`, or a legacy developer token if an older deployment still has one.
- Use the minimum Google Ads user role required for the founder-operated account path.
- `login_customer_id` is an authorization root, not the target advertiser. Every target customer is still checked explicitly.
- The read-only sync example cannot mutate Google Ads.
- Mutation execution requires a Phase-5 approved proposal, an exact plan fingerprint, a recent successful `validate_only` receipt, and a post-mutation read-back of the exact Google resource.
- The local filesystem sync store is an accuracy/resume reference implementation, not the production secret store or production multi-tenant database.
- Do not log service-account JSON, OAuth tokens, legacy developer tokens, or full exception metadata that might contain credentials.
