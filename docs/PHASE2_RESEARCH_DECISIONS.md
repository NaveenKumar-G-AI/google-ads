# Phase 2 research decisions

Research date: 2026-10-15.

## Decisions grounded in current Google documentation

### Search terms are evidence, not complete truth
Google's search terms report contains actual searches that triggered ads, but low-volume queries can be omitted for privacy. Phase 1 already handles coverage limits. Phase 2 therefore does not infer business truth from the set of observed queries.

### Negative keyword recommendations require business-specific truth
Google explicitly describes using search-term reports to identify searches that are related but not what the advertiser sells, and warns that negative match behavior differs from positive keywords. We therefore model what the business sells/doesn't sell explicitly before generating exclusions.

### Current geo settings are not business truth
Google Ads supports presence-or-interest and presence-only location behavior. The default/broad behavior can reach people who show interest in an area. A local-service business and a destination business therefore need different business truth, even if they currently use identical Google settings.

### Conversion configuration must be interpreted against business outcomes
Google distinguishes primary conversion actions (generally used for bidding/reporting) from secondary observation actions. A Google Ads conversion setting is configuration, not proof that the underlying event is actually valuable to the business. Phase 2 records business outcomes independently; later phases compare Google conversion actions against them.

## Deliberate non-decisions

Phase 2 does not:

- classify any search term;
- call an LLM;
- calculate wasted spend;
- generate a negative keyword;
- mutate Google Ads;
- trust a website extraction without confirmation;
- assign arbitrary numeric confidence to business facts.

Those belong to later phases after this truth layer is stable.
