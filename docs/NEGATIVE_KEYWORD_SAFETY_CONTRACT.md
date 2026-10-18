# Negative Keyword Safety Contract

The product must never equate "irrelevant search term" with "safe broad negative."

A negative action is allowed to reach `READY_FOR_APPROVAL` only if all of the following
hold:

1. Phase 4 classified the scoped evidence as `POTENTIALLY_AVOIDABLE`.
2. The evidence bundle is declared complete for the exact action scope.
3. All findings use the same Business Truth fingerprint and currency.
4. The proposal is negative exact at the source ad group.
5. No effective existing negative already covers the query.
6. No supplied protected/valuable query is blocked by the candidate.
7. No current positive keyword text collides with the candidate.
8. The candidate fits Google Ads keyword text limits.
9. A human approves the immutable proposal fingerprint.
10. Google Ads validates the mutation with `validate_only=true` before execution.

`READY_FOR_APPROVAL` means "safe enough to show a human", **not** "safe to auto-run".

## Explicitly forbidden in V1

- AI-created campaign/account broad negatives without review.
- Auto-executing any negative keyword.
- Treating a local matcher as proof of Google's exact serving behavior.
- Editing a proposal after approval without invalidating approval.
- Reusing approval from one truth/evidence snapshot for a changed proposal.
- Claiming recovered spend merely because a negative was created.
