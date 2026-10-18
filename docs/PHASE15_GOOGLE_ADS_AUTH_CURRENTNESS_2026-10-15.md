# Google Ads authentication/access currentness note — 2026-10-15

This file records the platform change that caused the Phase-15 staging gate to be corrected before any live validation.

## Verified current behavior

1. Google Ads developer tokens were sunset on **2026-09-09**. Sending the legacy header is currently optional/ignored, and Google says a future major API version will reject developer tokens.
2. Google Ads API access level is now attached to the **Google Cloud project** that owns the OAuth/service-account credentials.
3. For the service-account workflow, the service-account email must have access to the target Google Ads account or a manager in its hierarchy.
4. `login_customer_id` is required when the call is made through a manager hierarchy; the target advertiser remains the `customer_id`.
5. A new Cloud project begins with Test access. Reading a production advertiser requires an access level that allows production accounts: Explorer, Basic, or Standard.
6. Google Ads API v26 requires the Python client library `google-ads >= 34.0.0`.

## Product consequence

`GOOGLE_ADS_DEVELOPER_TOKEN` is no longer a required Phase-15 variable. It remains accepted as optional legacy input so an old deployment does not break immediately, but preflight warns when it is present. The live read probe is the authoritative check that the Cloud project, service account, manager hierarchy, and target advertiser permissions are actually usable.
