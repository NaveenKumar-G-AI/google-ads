# Search Intent Accuracy Contract

For every query, Phase 3 MUST:

- retain the exact raw query;
- normalize only for comparison, never overwrite the evidence;
- interpret meaning without cost/conversion/performance inputs;
- reference only stable IDs from the business-truth snapshot;
- keep model confidence separate from business-policy certainty;
- preserve multiple material intents rather than flattening them;
- return UNKNOWN for ambiguity, low confidence, unresolved modifiers, or missing policy;
- never infer "not sold" solely from absence in a partial catalog;
- never convert semantic irrelevance directly into a negative keyword action;
- store the business-truth fingerprint used for every business-fit decision.

## Outputs

- `RELEVANT`: high-confidence query meaning maps to confirmed active business truth and
  no unresolved/denied material intent remains.
- `IRRELEVANT`: strong semantic evidence maps to a confirmed explicit non-offer or a
  high-confidence material intent explicitly denied by business truth.
- `CONDITIONAL`: confirmed business policy or mixed evidence requires contextual review.
- `UNKNOWN`: the safe default when evidence is incomplete or contradictory.

`IRRELEVANT` is **not** synonymous with "wasted spend." That financial claim belongs to
Phase 4.
