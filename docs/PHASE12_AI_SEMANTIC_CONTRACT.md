# Candidate AI semantic contract

A model may interpret query meaning. It may **not**:

- see spend, clicks, impressions, conversions, conversion value, CPA, ROAS, revenue or budget;
- decide whether spend is waste;
- propose or execute a negative keyword;
- invent a business offer/non-offer ID;
- override Business Truth policy;
- use external tools/grounding;
- turn uncertainty into an exclusion simply to maximize coverage.

The downstream order remains:

`AI semantic assessment -> deterministic BusinessFitEvaluator -> Phase 4 evidence -> Phase 5 safety -> human approval`.

A candidate model is not production-authorized until the Phase-11 release gate passes on the
exact candidate configuration.
