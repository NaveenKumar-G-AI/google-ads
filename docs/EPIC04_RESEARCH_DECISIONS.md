# Epic 4 — Research Decisions

Version: 0.23.0

Research was anchored to current Google Ads documentation and to the product's accuracy-first financial contract.

## Google Ads geography

Google exposes multiple geography concepts that must not be conflated:

- `location_view` represents performance associated with targeted location criteria.
- `user_location_view` represents physical user-location reporting.
- `geographic_view` can provide presence/interest location-type context.
- geo target constants provide canonical location metadata such as name, canonical name, country code and target type.

Decision: Recovery OS uses `user_location_view` for physical user-location evidence. Campaign target settings are not used as proof that a user was physically outside the service area.

## Device / daypart / network

Google Ads supports device, day-of-week, hour and ad-network segmentation on compatible resources.

Decision:
- persist campaign performance segments as independent evidence;
- do not infer device/daypart waste from query rows;
- do not treat zero conversions or a weak ratio as sufficient evidence of waste;
- network may display already-supported query mismatch financial evidence as a dimension, but that money is not additive to query-family totals.

## Search-only V1 boundary

Epic 4 continues the Search/Search Partners V1 boundary. It does not claim complete Performance Max or cross-channel leakage coverage.

## Privacy boundary

The Search Intelligence rule remains unchanged: privacy-hidden/unobserved query demand is not reconstructed into individual queries or waste families.
