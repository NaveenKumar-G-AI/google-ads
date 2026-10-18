# Epic 6 — Current Google Ads Research Decisions

Version: 0.25.0

Research checked against current Google Ads API documentation in October 2026.

## validate-only

Resource mutate requests support `validate_only`. When true, the request is validated but not executed. Recovery OS keeps this mandatory before its V1 live negative-keyword mutation.

## partial failure

Google mutate requests can support partial failure, where valid operations may commit while invalid operations fail. Recovery OS V1 intentionally uses a single action and `partial_failure=false`, preserving an all-or-nothing action boundary.

## response/read-back

Google mutate responses identify the mutated resource. Recovery OS validates that resource is within the approved advertiser/ad-group scope and then queries the exact resource back before recording the action as applied.

## change tracking

Google provides `change_status` for broad changed-resource tracking and `change_event` for detailed changes. Change Event is limited to recent history and may be delayed. Epic 6 does not use those asynchronous reports as proof of immediate mutate success; exact provider read-back is the immediate proof. They remain appropriate inputs for a later drift/monitoring epic.

## negative criteria metrics

Google reporting views for criterion performance exclude negative criteria from performance metrics. Therefore Recovery OS must not attempt to prove recovery from a negative criterion's own metrics. Recovery verification continues to use post-action paid-search observations and the causal Recovery Ledger.

## dynamic recommendations

Google recommendations can become invalid between retrieval and action. Recovery OS does not use Google recommendation objects as its Action Center source of truth; its own proposal fingerprint, Business Truth version, current analysis and execution-time preflight determine validity.
