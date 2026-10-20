# Landing experience: product truth inventory

Prepared before UI implementation. This inventory governs public copy, simulated product scenes, navigation, and conversion events. It describes implemented V1 behavior, not external launch certification.

## What the site can claim

| Area | Implemented truth and public boundary | Source |
| --- | --- | --- |
| Search evidence | Visible Search terms and n-grams, campaign/ad-group/network/match breakdowns, exact analysis windows. Hidden traffic stays unknown; coverage is not inferred waste. Geography is separate; device/daypart are diagnostics. | `docs/EPIC03_IMPLEMENTATION_CONTRACT.md`, `docs/EPIC04_WASTE_INTELLIGENCE_CONTRACT.md`, `src/recovery/waste_intelligence.py` |
| Business Truth | Versioned offers, non-offers, audiences, service areas, outcomes, intent policies and protected queries; immutable versions and SHA256 fingerprint. Protection affects the negative engine. | `src/recovery/business_truth.py` |
| Measurement | Canonical states: **strong, constrained, blocked, unknown**. Conversion-action mappings, goals and observed lag constrain conversion-dependent claims. Mapping an outcome does not independently measure lead quality or revenue. | `src/recovery/measurement_integrity.py`, `docs/EPIC05_MEASUREMENT_INTEGRITY_CONTRACT.md` |
| Action safety | Only **exact ad-group negative keywords** execute in V1. Evidence/proposal, current truth fingerprint, role-based approval, provider validation, read-back and reconciliation precede a trusted outcome. Proposals do not change accounts. | `src/recovery/negative_keywords.py`, `src/recovery/google_ads/mutation.py`, `docs/EPIC06_RECOVERY_CASE_ACTION_CENTER_CONTRACT.md` |
| Control | Owners/admins approve or execute; analysts cannot approve mutations. Ambiguous provider effects require reconciliation rather than automatic replay. Rollback targets the exact resource created and verifies absence. | `src/recovery/api/policy.py`, `src/recovery/worker/google_jobs.py` |
| Financial evidence | Five **non-additive** classes: current observed candidate; historical acted-on exposure; projected prevention; observed post-action query spend; verified recovery. The apply worker bootstraps historical exposure and a baseline-length projection; it does not collect a post-action observation. The current candidate comes from the latest completed analysis and is not cleared by applying a change. Configuration verification is not financial causality. V1 has no experiment ingestion/orchestration. | `src/recovery/recovery_ledger.py`, `src/recovery/worker/google_jobs.py:487`, `src/recovery/api/repository.py:3054`, `docs/EPIC07_RECOVERY_CENTER_CONTRACT.md` |
| Monitoring | Freshness, measurement, jobs, serving status and reconciliation, evaluated after sync or manual queueing. Statistical anomaly monitors are opt-in. No continuous real-time promise. | `src/recovery/api/repository.py` |
| Reports | Eight presets, frozen snapshots, PDF/CSV artifacts and hashes, expiring/revocable capability links. Evidence fields depend on report type. | `src/recovery/reporting_service.py`, `src/recovery/reporting.py` |
| Security/data | Backend roles/account authorization, tenant RLS, configured vault credential storage, safe metadata/config export. Full export, disconnect and deletion have controlled request workflows. No certification/SSO claim. | `src/recovery/api/policy.py`, `src/recovery/api/repository.py`, `docs/V1_BUILD_COMPLETION_CONTRACT.md` |
| Google authorization | OAuth requests the write-capable `adwords` scope. Say **Start with a read-only sync. Changes require your approval.** Never call the grant read-only. | `src/recovery/onboarding.py:14`, `web/app/(dashboard)/onboarding/page.tsx` |

## Explicit exclusions

No automatic budget/bid/campaign changes, deep CRM attribution or closed-revenue measurement, cross-channel support, arbitrary report builder, advanced white-label designer, enterprise SSO, certification, public API/webhooks, causal experiment execution or guaranteed savings. No invented customers, testimonials, customer counts, prices, integrations, or production-readiness assertions.

## Consistent synthetic demonstration

All scenes use **Northstar Roofing**, a fictional business providing residential roof repair/replacement in Austin. It does not sell training, jobs or DIY materials. `roofing company` is a protected commercial query. The candidate `free roofing course` is an explicit training non-offer; a simulated proposal adds that exact negative to one ad group. A second proposal for `roofing company` is blocked by the protection.

Use a labeled 1–30 September 2026 baseline, simulated application on 1 October, and a 30-day run-rate projection for 2–31 October. This matches the apply worker: its projection begins after the application day and uses the baseline's full 30-day length. The $428 baseline therefore projects $428, an estimate rather than observed prevention.

The latest completed analysis still shows **$428 current candidate exposure** because no newer analysis has been completed. The applied intervention separately records **$428 historical acted-on exposure** and **$428 projected prevention**. **Post-action observation is pending/not collected**, not a measured zero. **Verified recovery is $0** and financial verification remains pending, even when configuration read-back is verified. All five financial classes remain non-additive. The initialized ledger field can be zero without an observation; the public illustration deliberately says “Pending” so it does not misrepresent that initialization as a measured outcome.

The domain engine can validate post-change observations, but there is no production caller collecting them in the current implementation. Do not imply that a sync automatically refreshes the financial observation ledger. A valid domain observation would begin strictly after the mixed application day (`src/recovery/recovery_ledger.py:467`).

Measurement is **constrained**, with a confirmed primary enquiry mapping and a page view treated as primary by Google despite being mapped as a supporting signal. That warning does not itself block the action: `conversion_dependent_claims_allowed` requires no blockers and at least one confirmed primary mapping (`src/recovery/measurement_integrity.py:311`). Downstream qualification remains independently unknown; it is not the cause assigned to the measurement warning. The tour explicitly describes the passing action gate before simulated approval.

Query coverage 78% refers only to observed Search spend. Every value is fictional illustration, never a customer result. No downstream qualified leads/customer/revenue values are invented. The report illustration uses the real **Change Impact** preset at **account** scope and states that this sample contains one intervention; it does not invent a per-case report scope.

Tour states: detect → evidence → Business Truth → proposal → protected collision → approval → provider application/read-back → observation pending → financial classification. User interaction in the tour changes local demo state only; no Google mutations.

## Routes and truthful conversion paths

Public: `/`, `/product`, `/for-agencies`, `/for-brands`, `/reporting`, `/security`, `/pricing`, `/demo`. Existing authenticated application stays at `/app` and preserves its authorization. Public rendering must not require Supabase credentials.

Connect routes through `/connect` to signup or existing onboarding. Signup, workspace launch/legal gates, subscription when enabled, Google permission, advertiser selection, Business Truth, measurement, sync and analysis remain distinct. Do not promise free/instant activation. Review/contact uses a configured booking URL or support email; missing configuration must never create a fake booking. Legal pages resolve the backend's authoritative published URLs. Status is a configured public page or an honest unavailable state; deletion links to the real controlled request workflow.

## Analytics contract

Allowlisted, cookie-free events go to a same-origin receiver and structured application logs. Do not collect arbitrary properties, email, IDs, URLs, OAuth state/codes or user-entered content. Respect DNT/GPC. Distinguish CTA click, submitted signup, successful auth account creation, successful OAuth initiation and backend-confirmed connection. Telemetry failure must never block authentication. Logs are a working first sink, not a claimed analytics dashboard. Document retention as an operator responsibility; never claim anonymous hosting logs contain no network metadata.

## Validation required

Preserve product contracts except the intentionally replaced root redirect; retain `/app`. Run repository validation, TypeScript/build where dependencies permit, relevant frontend contract tests, event receiver checks and browser review of the public flow at 1440, 1024, 768 and 390 px. Review source truth and synthetic amounts after implementation.
