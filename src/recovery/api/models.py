from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeResponse(StrictModel):
    user_id: UUID
    email: str | None
    memberships: list[dict[str, Any]]


class AccountResponse(StrictModel):
    id: UUID
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    account_status: str
    test_account: bool


class SyncCreateRequest(StrictModel):
    start: date
    end: date

    @field_validator("end")
    @classmethod
    def _end_present(cls, v: date) -> date:
        return v


class AnalysisCreateRequest(StrictModel):
    sync_run_id: UUID
    truth_snapshot_id: UUID
    as_of: date
    conversion_lag_days: int = Field(ge=0, le=365)


class SemanticShadowCreateRequest(StrictModel):
    sync_run_id: UUID
    truth_snapshot_id: UUID


class BusinessTruthCreateRequest(StrictModel):
    payload: dict[str, Any]


class ProposalDecisionRequest(StrictModel):
    decision: Literal["approved", "rejected"]
    proposal_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=2000)


class JobResponse(StrictModel):
    job_id: UUID
    job_type: str
    status: str
    idempotency_replay: bool


class JobDetailResponse(StrictModel):
    job_id: UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BusinessTruthResponse(StrictModel):
    truth_snapshot_id: UUID
    truth_fingerprint: str
    version: int
    idempotency_replay: bool


class TruthReadinessIssueResponse(StrictModel):
    code: str
    message: str
    blocker: bool


class TruthReadinessResponse(StrictModel):
    ready: bool
    issues: list[TruthReadinessIssueResponse]


class BusinessTruthVersionResponse(StrictModel):
    id: UUID
    account_id: UUID
    truth_fingerprint: str
    schema_version: int
    version: int
    business_id: str | None
    business_name: str | None
    supersedes_version: int | None
    created_by: str
    created_at: datetime
    offer_count: int
    non_offer_count: int
    intent_policy_count: int
    audience_policy_count: int
    service_area_count: int
    outcome_count: int
    protected_query_count: int
    readiness: dict[str, TruthReadinessResponse]
    changed_sections: list[str]
    payload: dict[str, Any]


class ProposalDecisionResponse(StrictModel):
    decision_event_id: UUID
    decision: str
    proposal_artifact_id: UUID


class FindingResponse(StrictModel):
    artifact_id: UUID
    analysis_run_id: UUID
    artifact_kind: str
    external_id: str
    artifact_fingerprint: str
    currency_code: str | None
    money_micros: int | None
    payload: dict[str, Any]
    created_at: datetime


class LedgerResponse(StrictModel):
    entry_id: UUID
    analysis_run_id: UUID
    currency_code: str
    historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    verified_recovery_micros: int
    causal_status: str
    created_at: datetime


class WorkspaceStage(StrictModel):
    id: UUID | None
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class WorkspaceSummary(StrictModel):
    account: AccountResponse
    latest_sync: WorkspaceStage
    latest_truth: WorkspaceStage
    latest_analysis: WorkspaceStage
    currency_code: str | None
    potentially_avoidable_observed_micros: int
    visible_search_term_micros: int
    unobserved_search_micros: int
    coverage_band: str | None
    query_count: int
    review_required_count: int
    proposal_count: int
    ready_for_approval_count: int
    verified_recovery_micros: int
    verified_recovery_entries: int
    last_updated_at: datetime | None


class ProposalStateResponse(StrictModel):
    artifact_id: UUID
    analysis_run_id: UUID
    artifact_fingerprint: str
    currency_code: str | None
    money_micros: int | None
    payload: dict[str, Any]
    decision: str | None
    decision_event_id: UUID | None
    decided_at: datetime | None
    mutation_event_type: str | None
    resource_name: str | None
    mutation_occurred_at: datetime | None
    created_at: datetime

class BillingPlanResponse(StrictModel):
    key: str
    display_name: str
    currency: str
    amount_subunits: int
    max_google_ads_accounts: int
    max_sync_range_days: int


class BillingAccountSlotResponse(StrictModel):
    account_id: UUID
    customer_id: str
    descriptive_name: str
    occurred_at: datetime


class BillingProfileResponse(StrictModel):
    id: UUID
    legal_name: str
    billing_email: str
    tax_country: str
    tax_region: str | None
    gstin: str | None
    actor_user_id: UUID
    occurred_at: datetime


class BillingProfileRequest(StrictModel):
    legal_name: str = Field(min_length=1, max_length=200)
    billing_email: str = Field(min_length=3, max_length=320)
    tax_country: str = Field(min_length=2, max_length=2)
    tax_region: str | None = Field(default=None, max_length=120)
    gstin: str | None = Field(default=None, max_length=15)


class BillingStatusResponse(StrictModel):
    enabled: bool
    plan_key: str | None
    provider_status: str | None
    entitlement_state: str
    current_start: datetime | None
    current_end: datetime | None
    provider_subscription_id: str | None = None
    payment_method: str | None = None
    grace_until: datetime | None = None
    has_scheduled_changes: bool = False
    pending_plan_key: str | None = None
    pending_plan_effective_at: datetime | None = None
    cancellation_scheduled: bool = False
    cancellation_effective_at: datetime | None = None
    account_slots: list[BillingAccountSlotResponse] = Field(default_factory=list)
    billing_profile: BillingProfileResponse | None = None


class BillingCheckoutRequest(StrictModel):
    plan_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


class BillingCheckoutResponse(StrictModel):
    checkout_intent_id: UUID
    plan_key: str
    provider_subscription_id: str
    checkout_url: str | None
    state: str
    idempotency_replay: bool


class BillingReconcileResponse(StrictModel):
    snapshot_id: UUID
    plan_key: str
    provider_status: str
    entitlement_state: str
    current_start: datetime | None
    current_end: datetime | None
    payment_method: str | None = None
    grace_until: datetime | None = None
    has_scheduled_changes: bool = False


class BillingPlanChangePreviewRequest(StrictModel):
    target_plan_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


class BillingPlanAffectedAccountResponse(StrictModel):
    account_id: UUID
    customer_id: str | None
    descriptive_name: str | None


class BillingPlanChangePreviewResponse(StrictModel):
    current_plan_key: str | None
    target_plan: BillingPlanResponse
    provider_status: str
    payment_method: str | None
    automated_change_supported: bool
    schedule_change_at: Literal["cycle_end"]
    effective_at: datetime | None
    active_account_slots: int
    accounts_over_target_limit: list[BillingPlanAffectedAccountResponse]
    note: str


class BillingLifecycleEventResponse(StrictModel):
    id: UUID
    event_type: str
    actor: str
    payload: dict[str, Any]
    occurred_at: datetime


class BillingLifecycleOperationResponse(StrictModel):
    id: UUID
    tenant_id: UUID
    requested_by: UUID
    operation_type: str
    provider_subscription_id: str
    target_plan_key: str | None
    idempotency_key: str
    request_sha256: str
    effective_at: datetime | None
    created_at: datetime
    state: str
    events: list[BillingLifecycleEventResponse]


class BillingInvoiceResponse(StrictModel):
    provider_invoice_id: str
    provider_payment_id: str | None
    status: str
    currency: str
    amount: int
    amount_paid: int
    amount_due: int
    issued_at: datetime | None
    paid_at: datetime | None
    observed_at: datetime


class BillingInvoiceRefreshResponse(StrictModel):
    provider_subscription_id: str
    provider_count: int
    new_snapshots: int
    invoices: list[BillingInvoiceResponse]


class BillingEntitlementHistoryResponse(StrictModel):
    id: UUID
    provider_subscription_id: str
    provider_plan_id: str
    plan_key: str
    provider_status: str
    entitlement_state: str
    current_start: datetime | None
    current_end: datetime | None
    payment_method: str | None
    has_scheduled_changes: bool
    change_scheduled_at: datetime | None
    grace_until: datetime | None
    observed_at: datetime

class PortfolioResponse(StrictModel):
    id: UUID
    name: str
    description: str | None
    account_count: int
    created_at: datetime
    updated_at: datetime


class PortfolioCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class PortfolioAccountRequest(StrictModel):
    account_id: UUID


class TaskResponse(StrictModel):
    id: UUID
    account_id: UUID | None
    portfolio_id: UUID | None
    title: str
    description: str | None
    source_type: str
    source_id: str | None
    priority: str
    status: str
    assigned_to: UUID | None
    due_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    account_id: UUID | None = None
    portfolio_id: UUID | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    assigned_to: UUID | None = None
    due_at: datetime | None = None


class TaskStatusRequest(StrictModel):
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"]


class NotificationResponse(StrictModel):
    id: UUID
    kind: str
    severity: str
    title: str
    body: str | None
    href: str | None
    source_type: str | None
    source_id: str | None
    read_at: datetime | None
    created_at: datetime


class SearchResultResponse(StrictModel):
    kind: str
    id: str
    title: str
    subtitle: str | None
    href: str


class MoneyBucket(StrictModel):
    currency_code: str
    potentially_avoidable_observed_micros: int
    verified_recovery_micros: int


class CommandAccountSummary(StrictModel):
    id: UUID
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    latest_sync_at: datetime | None
    latest_analysis_at: datetime | None
    data_status: str
    potentially_avoidable_observed_micros: int
    verified_recovery_micros: int
    ready_for_approval_count: int


class CommandCenterResponse(StrictModel):
    tenant_id: UUID
    tenant_name: str
    account_count: int
    portfolio_count: int
    open_task_count: int
    unread_notification_count: int
    ready_for_approval_count: int
    current_account_count: int
    stale_account_count: int
    money_by_currency: list[MoneyBucket]
    accounts: list[CommandAccountSummary]
    generated_at: datetime

class PortfolioAccountSummary(StrictModel):
    id: UUID
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    account_status: str


class PortfolioDetailResponse(PortfolioResponse):
    accounts: list[PortfolioAccountSummary]

class OrganizationCreateRequest(StrictModel):
    display_name: str = Field(min_length=2, max_length=160)
    slug: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    legal_acceptance_confirmed: bool = False
    accepted_terms_version: str | None = Field(default=None,max_length=120)
    accepted_privacy_version: str | None = Field(default=None,max_length=120)
    turnstile_token: str | None = Field(default=None,max_length=2048)

class OrganizationCreateResponse(StrictModel):
    tenant_id: UUID
    idempotency_replay: bool

class OnboardingAccountActivationResponse(StrictModel):
    id: UUID
    customer_id: str
    descriptive_name: str
    currency_code: str
    business_truth_ready: bool
    measurement_ready: bool
    sync_ready: bool
    analysis_ready: bool


class OnboardingStatusResponse(StrictModel):
    current_step: str
    completed_steps: list[str]
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    connected_google_users: int
    selected_accounts: int
    truth_snapshots: int
    measurement_profiles: int
    completed_syncs: int
    completed_analyses: int
    proposal_count: int
    account_activation: list[OnboardingAccountActivationResponse] = Field(default_factory=list)

class GoogleOAuthStartRequest(StrictModel):
    return_path: str = Field(default="/onboarding", pattern=r"^/[^\s]*$", max_length=1000)
    login_hint: str | None = Field(default=None, max_length=320)

class GoogleOAuthStartResponse(StrictModel):
    authorization_url: str

class GoogleOAuthCallbackRequest(StrictModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=16, max_length=1024)

class GoogleOAuthCallbackResponse(StrictModel):
    tenant_id: UUID
    connection_id: UUID
    discovery_job: JobResponse
    return_path: str

class DiscoveredGoogleAdsAccountResponse(StrictModel):
    id: UUID
    connection_id: UUID
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    manager: bool
    account_status: str
    test_account: bool
    direct_access: bool
    login_customer_id: str | None
    hierarchy_level: int
    selected_at: datetime | None

class AccountSelectionRequest(StrictModel):
    customer_ids: list[str] = Field(min_length=1, max_length=100)

class GuidedOfferRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=50)

class GuidedNonOfferRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=50)

class GuidedGeoAreaRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    country_code: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=160)
    postal_code: str | None = Field(default=None, max_length=32)

class GuidedAudienceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    disposition: Literal["allow","deny","conditional","unknown"] = "unknown"
    reason: str = Field(min_length=1, max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    condition: str | None = Field(default=None, max_length=2000)


class GuidedProtectedQueryRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)


class GuidedBusinessTruthRequest(StrictModel):
    business_name: str = Field(min_length=1, max_length=200)
    business_id: str | None = Field(default=None, max_length=200)
    offers: list[GuidedOfferRequest] = Field(min_length=1, max_length=100)
    non_offers: list[GuidedNonOfferRequest] = Field(default_factory=list, max_length=100)
    service_areas: list[GuidedGeoAreaRequest] = Field(default_factory=list, max_length=200)
    catalog_complete: bool = False
    employment_policy: Literal["allow","deny","conditional","unknown"] = "unknown"
    free_policy: Literal["allow","deny","conditional","unknown"] = "unknown"
    diy_policy: Literal["allow","deny","conditional","unknown"] = "unknown"
    additional_intent_policies: dict[str, Literal["allow","deny","conditional","unknown"]] = Field(default_factory=dict)
    audience_policies: list[GuidedAudienceRequest] = Field(default_factory=list, max_length=100)
    geo_requirement: Literal["no_restriction","customer_must_be_in_service_area","destination_or_job_must_be_in_service_area","conditional","unknown"] = "destination_or_job_must_be_in_service_area"
    geo_condition: str | None = Field(default=None, max_length=2000)
    primary_outcomes: list[str] = Field(min_length=1, max_length=50)
    supporting_outcomes: list[str] = Field(default_factory=list, max_length=50)
    invalid_outcomes: list[str] = Field(default_factory=list, max_length=50)
    protected_queries: list[GuidedProtectedQueryRequest] = Field(default_factory=list, max_length=200)

class MeasurementProfileRequest(StrictModel):
    conversion_lag_days: int = Field(ge=0, le=365)

class MeasurementProfileResponse(StrictModel):
    conversion_lag_days: int
    configured_at: datetime | None = None
    updated_at: datetime | None = None

class SearchDateWindow(StrictModel):
    start: date
    end: date
    min_available: date
    max_available: date


class SearchCoverageResponse(StrictModel):
    currency_code: str
    visible_search_term_micros: int
    comparable_search_campaign_micros: int
    unobserved_search_micros: int
    coverage_ratio: str | None
    coverage_band: str
    note: str


class SearchOverviewResponse(StrictModel):
    account_id: UUID
    currency_code: str
    window: SearchDateWindow
    distinct_queries: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    latest_analysis_run_id: UUID | None
    latest_analysis_completed_at: datetime | None
    analysis_window_matches: bool
    fit_counts: dict[str, int]
    evidence_counts: dict[str, int]
    coverage: SearchCoverageResponse


class SearchTermRowResponse(StrictModel):
    normalized_query: str
    raw_query_example: str
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    all_conversions: str
    all_conversions_value: str
    campaign_count: int
    ad_group_count: int
    first_observation_date: date
    last_observation_date: date
    networks: list[str]
    match_sources: list[str]
    fit_disposition: str | None
    semantic_status: str | None
    primary_intent: str | None
    evidence_status: str | None
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    analysis_run_id: UUID | None
    financial_evidence_in_window: bool


class SearchTermPageResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    page: int
    page_size: int
    total: int
    rows: list[SearchTermRowResponse]


class SearchBreakdownRow(StrictModel):
    key: str
    query_count: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    potentially_avoidable_observed_micros: int = 0


class SearchBreakdownResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    dimension: str
    rows: list[SearchBreakdownRow]


class SearchNGramRow(StrictModel):
    ngram: str
    query_count: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    potentially_avoidable_observed_micros: int


class SearchNGramResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    n: int
    sort: str
    without_conversions: bool
    rows: list[SearchNGramRow]


class SearchTermScopeBreakdown(StrictModel):
    campaign_id: str
    campaign_name: str
    ad_group_id: str
    ad_group_name: str
    network: str
    match_source: str
    triggering_keyword: str | None
    triggering_keyword_match_type: str | None
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    first_observation_date: date
    last_observation_date: date


class SearchTermDailyPoint(StrictModel):
    date: date
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str


class SearchTermDetailResponse(StrictModel):
    account_id: UUID
    currency_code: str
    window: SearchDateWindow
    term: SearchTermRowResponse
    scope_breakdown: list[SearchTermScopeBreakdown]
    daily: list[SearchTermDailyPoint]
    semantic_assessment: dict[str, Any] | None
    business_fit: dict[str, Any] | None
    financial_findings: list[dict[str, Any]]
    coverage_note: str


class SearchSavedViewCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    account_id: UUID | None = None
    portfolio_id: UUID | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False

    @model_validator(mode="after")
    def _exactly_one_scope(self):
        if (self.account_id is None) == (self.portfolio_id is None):
            raise ValueError("saved view must target exactly one account or portfolio")
        return self


class SearchSavedViewResponse(StrictModel):
    id: UUID
    account_id: UUID | None
    portfolio_id: UUID | None
    name: str
    filters: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class PortfolioNGramRow(StrictModel):
    currency_code: str
    ngram: str
    account_count: int
    query_count: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str


class PortfolioNGramResponse(StrictModel):
    portfolio_id: UUID
    start: date
    end: date
    n: int
    rows: list[PortfolioNGramRow]


class WasteFamilySummary(StrictModel):
    leak_family: str
    query_count: int
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    already_addressed_observed_micros: int


class WasteOverviewResponse(StrictModel):
    account_id: UUID
    window: SearchDateWindow
    currency_code: str
    analysis_run_id: UUID | None
    analysis_window_matches: bool
    query_potentially_avoidable_observed_micros: int
    query_review_required_observed_micros: int
    geo_potentially_avoidable_observed_micros: int
    geo_review_required_observed_micros: int
    families: list[WasteFamilySummary]
    dimension_data_ready: bool
    geo_data_ready: bool
    geo_evaluation_ready: bool
    financial_note: str


class WasteQueryRow(StrictModel):
    normalized_query: str
    raw_query_example: str
    leak_family: str
    disposition: str
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    networks: list[str]
    finding_count: int
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    already_addressed_observed_micros: int


class WasteQueryPageResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    analysis_run_id: UUID | None
    financial_evidence_in_window: bool
    page: int
    page_size: int
    total: int
    rows: list[WasteQueryRow]


class WasteDimensionRow(StrictModel):
    key: str
    query_count: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: str
    conversions_value: str
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    financial_claim_supported: bool


class WasteDimensionResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    dimension: str
    rows: list[WasteDimensionRow]
    note: str


class WasteGeoRow(StrictModel):
    location_resource: str
    location_name: str
    canonical_name: str | None
    country_code: str | None
    target_type: str | None
    disposition: str
    reason: str
    mature_cost_micros: int
    immature_cost_micros: int
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    mature_conversions: str
    row_count: int


class WasteGeoResponse(StrictModel):
    window: SearchDateWindow
    currency_code: str
    evaluation_ready: bool
    analysis_run_id: UUID | None
    truth_snapshot_id: UUID | None
    rows: list[WasteGeoRow]
    note: str

class MeasurementIssueResponse(StrictModel):
    code: str
    severity: Literal["info","warning","blocker"]
    message: str
    conversion_action_resource: str | None = None
    campaign_id: str | None = None


class MeasurementOverviewResponse(StrictModel):
    account_id: UUID
    measurement_snapshot_id: UUID | None
    sync_run_id: UUID | None
    sync_completed_at: datetime | None
    window_start: date | None
    window_end: date | None
    confidence: Literal["strong","constrained","blocked","unknown"]
    enabled_actions: int
    primary_actions: int
    mapped_primary_actions: int
    conversion_dependent_claims_allowed: bool
    recovery_verification_allowed: bool
    configured_conversion_lag_days: int | None
    customer_goal_count: int
    campaign_goal_count: int
    campaign_specific_goal_config_count: int
    issues: list[MeasurementIssueResponse]
    available_outcomes: list[dict[str, Any]]
    note: str


class MeasurementConversionActionResponse(StrictModel):
    resource_name: str
    action_id: str
    name: str
    status: str
    action_type: str
    category: str
    origin: str
    owner_customer: str | None
    primary_for_goal: bool
    account_default_goal_biddable: bool | None
    counting_type: str
    click_through_lookback_days: int
    view_through_lookback_days: int
    attribution_model: str
    data_driven_model_status: str
    default_value: str
    default_currency_code: str | None
    always_use_default_value: bool
    all_conversions: str
    all_conversions_value: str
    last_conversion_date: date | None
    last_received_request_at: str | None
    mapped_outcome_id: str | None
    mapped_outcome_role: str | None
    mapping_confirmed: bool
    mapping_is_current_truth: bool
    mapping_status: str | None
    enhanced_conversions_status: str


class MeasurementGoalsResponse(StrictModel):
    customer_goals: list[dict[str, Any]]
    campaign_goals: list[dict[str, Any]]
    campaign_configs: list[dict[str, Any]]
    note: str


class MeasurementLagResponse(StrictModel):
    configured_conversion_lag_days: int | None
    rows: list[dict[str, Any]]
    note: str


class ConversionActionMappingRequest(StrictModel):
    conversion_action_resource: str = Field(min_length=1, max_length=500)
    outcome_id: str | None = Field(default=None, max_length=240)


class ConversionActionMappingResponse(StrictModel):
    id: UUID
    conversion_action_resource: str
    truth_snapshot_id: UUID
    outcome_id: str | None
    mapping_status: Literal["mapped","cleared"]
    created_at: datetime


class RecoveryCaseSummaryResponse(StrictModel):
    case_id: UUID
    account_id: UUID
    account_name: str
    analysis_run_id: UUID
    proposal_fingerprint: str
    proposal_id: str | None
    query: str | None
    match_type: str | None
    scope: str | None
    campaign_id: str | None
    ad_group_id: str | None
    risk: str | None
    disposition: str | None
    currency_code: str | None
    candidate_exposure_micros: int
    collision_count: int
    state: str
    stale: bool
    stale_reasons: list[str]
    execution_allowed: bool
    rollback_allowed: bool
    verification_status: str
    assigned_to: str | None
    closed: bool
    execution_job_status: str | None = None
    external_effect_state: str | None = None
    measurement_confidence: str | None = None
    conversion_claims_allowed: bool = False
    recovery_verification_allowed: bool = False
    measurement_issue_codes: list[str] = Field(default_factory=list)
    created_at: datetime


class RecoveryCaseDetailResponse(RecoveryCaseSummaryResponse):
    proposal: dict[str, Any]
    financial_findings: list[dict[str, Any]]
    decision_events: list[dict[str, Any]]
    mutation_events: list[dict[str, Any]]
    recovery_ledger: list[dict[str, Any]]
    case_events: list[dict[str, Any]]
    latest_truth_fingerprint: str | None
    latest_analysis_run_id: UUID | None
    analysis_truth_fingerprint: str
    execution_jobs: list[dict[str, Any]] = Field(default_factory=list)
    external_effects: list[dict[str, Any]] = Field(default_factory=list)


class RecoveryCaseEventRequest(StrictModel):
    event_type: Literal["assigned","unassigned","commented","review_requested","closed","reopened"]
    note: str | None = Field(default=None, max_length=4000)
    assigned_to: UUID | None = None


class RecoveryCaseEventResponse(StrictModel):
    id: UUID
    event_type: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any]

class RecoveryCenterMoneyBucket(StrictModel):
    currency_code: str
    current_observed_candidate_micros: int
    current_unobserved_search_micros: int
    acted_on_historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    observed_difference_vs_projection_micros: int
    verified_recovery_micros: int
    ledger_action_count: int
    verified_action_count: int
    inconclusive_action_count: int
    verification_pending_action_count: int


class RecoveryCenterOverviewResponse(StrictModel):
    scope_kind: Literal["organization","portfolio","account"]
    scope_id: str
    scope_name: str
    account_count: int
    money_by_currency: list[RecoveryCenterMoneyBucket]
    case_counts: dict[str, int]
    generated_at: datetime
    financial_classes_are_non_additive: bool
    verified_recovery_requires_causal_evidence: bool
    note: str


class RecoveryCenterCaseResponse(StrictModel):
    case_id: UUID
    account_id: UUID
    account_name: str
    query: str | None
    campaign_id: str | None
    campaign_name: str | None
    leak_family: str
    state: str
    currency_code: str
    historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    observed_difference_vs_projection_micros: int
    verified_recovery_micros: int
    causal_status: str
    ledger_created_at: datetime | None
    mutation_event_id: UUID | None
    applied_at: datetime | None


class RecoveryCenterBreakdownRow(StrictModel):
    key: str
    label: str
    currency_code: str
    action_count: int
    historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    verified_recovery_micros: int


class RecoveryCenterBreakdownResponse(StrictModel):
    dimension: Literal["account","campaign","leak_type"]
    rows: list[RecoveryCenterBreakdownRow]
    note: str


class RecoveryCenterTimelinePoint(StrictModel):
    date: date
    currency_code: str
    ledger_updates: int
    historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    verified_recovery_micros: int


class RecoveryCenterTimelineResponse(StrictModel):
    rows: list[RecoveryCenterTimelinePoint]
    note: str

# Epic 8 canonical event-sourced monitoring API models.
class MonitoringAlertEventResponse(StrictModel):
    id: UUID
    event_type: str
    severity: str | None
    actor: str
    payload: dict[str, Any]
    occurred_at: datetime


class MonitoringAlertResponse(StrictModel):
    id: UUID
    account_id: UUID
    monitor_type: str
    source_key: str
    alert_fingerprint: str
    generation: int
    initial_severity: str
    title: str
    first_evidence: dict[str, Any]
    latest_evidence: dict[str, Any]
    opened_at: datetime
    state: str
    severity: str
    assigned_to: str | None
    last_seen_at: datetime
    occurrence_count: int


class MonitoringAlertDetailResponse(MonitoringAlertResponse):
    events: list[MonitoringAlertEventResponse]


class MonitoringAlertEventRequest(StrictModel):
    event_type: Literal["acknowledged","assigned","unassigned","resolved","dismissed","reopened","commented"]
    payload: dict[str, Any] = Field(default_factory=dict)


class MonitoringOverviewResponse(StrictModel):
    account_id: UUID | None
    counts: dict[str, int]
    active_by_monitor_type: list[dict[str, Any]]
    recent_alerts: list[MonitoringAlertResponse]
    generated_at: datetime
    note: str


class MonitoringPolicyResponse(StrictModel):
    monitor_type: str
    enabled: bool
    severity_override: str | None
    config: dict[str, Any]
    scope: str
    updated_at: datetime | None


class MonitoringPolicyRequest(StrictModel):
    account_id: UUID | None = None
    monitor_type: Literal["data_freshness","measurement_integrity","job_health","campaign_serving","spend_anomaly","conversion_drop","reconciliation","query_recurrence"]
    enabled: bool = True
    severity_override: Literal["info","warning","critical"] | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class MonitoringEvaluationResponse(StrictModel):
    account_id: UUID
    evaluated_monitor_types: list[str]
    signal_count: int
    opened_count: int
    observed_count: int
    auto_resolved_count: int
    evaluated_at: datetime

class ReportTemplateResponse(StrictModel):
    report_type: str
    name: str
    supported_scopes: list[str]
    requires_period: bool
    description: str


class ReportGenerationRequest(StrictModel):
    report_type: Literal["executive_recovery","waste","measurement_integrity","search_demand","account_health","change_impact","monthly_client","agency_portfolio"]
    scope_kind: Literal["organization","portfolio","account"]
    scope_id: str = Field(min_length=1,max_length=300)
    period_start: date | None = None
    period_end: date | None = None


class ReportArtifactMetaResponse(StrictModel):
    format: str
    byte_size: int
    sha256: str
    content_type: str | None = None


class ReportGenerationSummaryResponse(StrictModel):
    id: UUID
    report_type: str
    template_version: str
    schema_version: str
    scope_kind: str
    scope_id: str
    period_start: date | None
    period_end: date | None
    generated_by: UUID
    source_job_id: UUID | None
    schedule_id: UUID | None
    snapshot_sha256: str
    generated_at: datetime
    artifacts: list[dict[str, Any]]


class ReportGenerationDetailResponse(ReportGenerationSummaryResponse):
    snapshot: dict[str, Any]
    deliveries: list[dict[str, Any]]


class ReportShareCreateRequest(StrictModel):
    expires_days: int = Field(default=14,ge=1,le=90)


class ReportShareResponse(StrictModel):
    id: UUID
    generation_id: UUID
    expires_at: datetime
    state: str
    created_at: datetime
    access_count: int | None = None
    token: str | None = None


class ReportScheduleRequest(StrictModel):
    schedule_id: UUID | None = None
    report_type: Literal["executive_recovery","waste","measurement_integrity","search_demand","account_health","change_impact","monthly_client","agency_portfolio"]
    scope_kind: Literal["organization","portfolio","account"]
    scope_id: str = Field(min_length=1,max_length=300)
    frequency: Literal["daily","weekly","monthly"]
    timezone_name: str = Field(min_length=1,max_length=100)
    hour: int = Field(ge=0,le=23)
    minute: int = Field(ge=0,le=59)
    weekday: int | None = Field(default=None,ge=0,le=6)
    day_of_month: int | None = Field(default=None,ge=1,le=28)
    recipients: list[str] = Field(default_factory=list,max_length=50)
    enabled: bool = True


class ReportScheduleResponse(StrictModel):
    id: UUID
    schedule_id: UUID
    report_type: str
    scope_kind: str
    scope_id: str
    frequency: str
    timezone_name: str
    hour: int
    minute: int
    weekday: int | None
    day_of_month: int | None
    recipients: list[str]
    enabled: bool
    actor_user_id: UUID
    occurred_at: datetime


class PublicReportResponse(StrictModel):
    share: dict[str, Any]
    generation: dict[str, Any]

class OrganizationInviteCreateRequest(StrictModel):
    email: str = Field(min_length=3,max_length=320)
    role: Literal["owner","admin","analyst","viewer"]
    account_access_mode: Literal["all_accounts","selected_accounts"] = "all_accounts"
    client_portal: bool = False
    expires_days: int = Field(default=7,ge=1,le=30)

class OrganizationInviteResponse(StrictModel):
    id: UUID
    email: str
    role: str
    account_access_mode: str
    client_portal: bool
    expires_at: datetime
    state: str
    created_at: datetime
    token: str | None = None

class OrganizationInviteAcceptResponse(StrictModel):
    tenant_id: UUID
    tenant_name: str
    role: str
    account_access_mode: str
    client_portal: bool

class OrganizationMemberResponse(StrictModel):
    user_id: UUID
    email: str | None
    role: str
    status: str
    account_access_mode: str
    client_portal: bool
    created_at: datetime
    updated_at: datetime
    accessible_account_count: int
    assignments: list[dict[str,Any]] = Field(default_factory=list)

class OrganizationMemberUpdateRequest(StrictModel):
    role: Literal["owner","admin","analyst","viewer"]
    status: Literal["active","disabled"] = "active"
    account_access_mode: Literal["all_accounts","selected_accounts"] = "all_accounts"
    client_portal: bool = False

class MemberAccountAccessRequest(StrictModel):
    account_id: UUID
    action: Literal["grant","revoke"]
    reason: str | None = Field(default=None,max_length=1000)

class ClientWorkspaceCreateRequest(StrictModel):
    name: str = Field(min_length=1,max_length=160)
    external_reference: str | None = Field(default=None,max_length=240)
    notes: str | None = Field(default=None,max_length=5000)

class ClientWorkspaceUpdateRequest(ClientWorkspaceCreateRequest):
    workspace_id: UUID
    action: Literal["update","archive","restore"] = "update"

class ClientWorkspaceResponse(StrictModel):
    workspace_id: UUID
    name: str
    external_reference: str | None
    notes: str | None
    state: str
    occurred_at: datetime
    accounts: list[dict[str,Any]] = Field(default_factory=list)
    members: list[dict[str,Any]] = Field(default_factory=list)

class ClientWorkspaceAccountRequest(StrictModel):
    account_id: UUID
    action: Literal["link","unlink"]

class ClientWorkspaceMemberRequest(StrictModel):
    user_id: UUID
    action: Literal["grant","revoke"]

class AccountAssignmentRequest(StrictModel):
    user_id: UUID
    responsibility: Literal["lead","analyst","approver","client_contact"]
    action: Literal["assign","unassign"]
    note: str | None = Field(default=None,max_length=2000)

class AccountAssignmentResponse(StrictModel):
    account_id: UUID
    user_id: UUID
    email: str | None
    responsibility: str
    state: str
    occurred_at: datetime

class OrganizationActivityResponse(StrictModel):
    id: UUID
    actor_user_id: UUID
    actor_email: str | None
    event_type: str
    target_type: str
    target_id: str
    occurred_at: datetime
    payload: dict[str,Any]

class MemberAccountAccessDetailResponse(StrictModel):
    account_id: UUID
    customer_id: str
    descriptive_name: str
    accessible: bool
    sources: list[str]

class InternalMeResponse(StrictModel):
    user_id: UUID
    email: str | None
    operator_role: Literal["support_viewer","support_engineer","platform_admin","security_auditor"]


class InternalTenantSummaryResponse(StrictModel):
    tenant_id: UUID
    slug: str
    display_name: str
    first_seen_at: datetime
    account_count: int
    active_member_count: int
    active_job_count: int


class InternalTenantDiagnosticsResponse(StrictModel):
    tenant: dict[str, Any]
    accounts: list[dict[str, Any]]
    members: list[dict[str, Any]]
    job_counts: dict[str, int]
    reconciliation: list[dict[str, Any]]
    billing: dict[str, Any] | None
    latest_sync: dict[str, Any] | None
    latest_analysis: dict[str, Any] | None
    semantic_releases: list[dict[str, Any]]
    feature_controls: list[dict[str, Any]]


class InternalJobResponse(StrictModel):
    id: UUID
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    requested_by: UUID
    endpoint: str
    operation_key: str | None
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class InternalRetryJobRequest(StrictModel):
    reason: str = Field(min_length=8,max_length=2000)


class InternalRetryJobResponse(StrictModel):
    source_job_id: UUID
    new_job_id: UUID
    job_type: str
    status: str


class InternalSupportCaseCreateRequest(StrictModel):
    title: str = Field(min_length=1,max_length=240)
    category: Literal["product","data","google_ads","billing","integration","security","access","other"]
    severity: Literal["low","medium","high","critical"]
    note: str | None = Field(default=None,max_length=4000)


class InternalSupportCaseResponse(StrictModel):
    id: UUID
    title: str
    category: str
    severity: str
    opened_by: UUID | None = None
    created_at: datetime | None = None
    latest_event: str
    updated_at: datetime | None = None


class InternalSupportCaseEventRequest(StrictModel):
    event_type: Literal["note","assigned","unassigned","status_changed","closed","reopened"]
    payload: dict[str, Any] = Field(default_factory=dict)


class InternalSupportCaseEventResponse(StrictModel):
    id: UUID
    case_id: UUID
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime


class InternalFeatureControlResponse(StrictModel):
    feature_key: str
    enabled: bool
    reason: str
    occurred_at: datetime | None
    actor_user_id: UUID | None


class InternalFeatureControlRequest(StrictModel):
    enabled: bool
    reason: str = Field(min_length=8,max_length=2000)


class InternalIncidentEventRequest(StrictModel):
    incident_id: UUID | None = None
    event_type: Literal["opened","update","mitigated","resolved","reopened"]
    severity: Literal["low","medium","high","critical"]
    title: str = Field(min_length=1,max_length=240)
    payload: dict[str, Any] = Field(default_factory=dict)


class InternalIncidentResponse(StrictModel):
    incident_id: UUID
    event_type: str
    severity: str
    title: str
    payload: dict[str, Any]
    occurred_at: datetime
    actor_user_id: UUID


class InternalReleaseObservationResponse(StrictModel):
    tenant_id: UUID
    tenant_name: str
    job_id: UUID
    release_id: str
    worker_version: str
    completed_at: datetime

class PublicLaunchStatusResponse(StrictModel):
    launch_mode: Literal["closed","pilot_only","invite_only","public"]
    workspace_creation_open: bool
    access_granted: bool
    access_hint: str | None = None
    access_expires_at: datetime | None = None
    release_id: str | None = None
    terms_url: str | None = None
    terms_version: str | None = None
    privacy_url: str | None = None
    privacy_version: str | None = None
    legal_acceptance_ready: bool = False
    signup_abuse_ready: bool = False
    turnstile_site_key: str | None = None
    public_workspace_max_per_user_24h: int | None = None


class InternalLaunchQualificationResponse(StrictModel):
    id: UUID
    release_id: str
    report_sha256: str
    report_generated_at: datetime
    occurred_at: datetime
    imported_by: UUID


class InternalLaunchStatusResponse(StrictModel):
    id: UUID | None = None
    launch_mode: Literal["closed","pilot_only","invite_only","public"]
    release_id: str | None
    qualification_id: UUID | None
    reason: str
    occurred_at: datetime | None
    actor_user_id: UUID | None
    active_access_grants: int
    qualifications: list[InternalLaunchQualificationResponse]


class InternalLaunchQualificationImportRequest(StrictModel):
    report: dict[str, Any]


class InternalLaunchModeRequest(StrictModel):
    launch_mode: Literal["closed","pilot_only","invite_only","public"]
    release_id: str | None = Field(default=None,max_length=200)
    reason: str = Field(min_length=8,max_length=2000)


class InternalLaunchAccessRequest(StrictModel):
    email: str = Field(min_length=3,max_length=320)
    event_type: Literal["granted","revoked"]
    expires_at: datetime | None = None
    reason: str = Field(min_length=8,max_length=2000)


class InternalLaunchAccessResponse(StrictModel):
    id: UUID
    subject_email_sha256: str
    subject_hint: str
    event_type: str
    expires_at: datetime | None
    reason: str
    actor_user_id: UUID
    occurred_at: datetime

class CustomerSupportCaseCreateRequest(StrictModel):
    account_id: UUID | None = None
    category: Literal["product","data","google_ads","billing","access","security","reporting","other"]
    subject: str = Field(min_length=1,max_length=240)
    body: str = Field(min_length=1,max_length=10000)


class CustomerSupportEventRequest(StrictModel):
    event_type: Literal["commented","closed","reopened"]
    comment: str | None = Field(default=None,max_length=10000)


class CustomerSupportCaseResponse(StrictModel):
    id: UUID
    account_id: UUID | None
    created_by: UUID
    created_by_email: str | None = None
    category: str
    subject: str
    initial_body: str
    created_at: datetime
    state: str
    comment_count: int | None = None
    last_event_at: datetime | None = None
    events: list[dict[str,Any]] | None = None


class CustomerDataRequestCreateRequest(StrictModel):
    request_type: Literal["full_data_export","organization_deletion","google_ads_disconnect"]
    account_id: UUID | None = None
    reason: str = Field(min_length=1,max_length=5000)


class CustomerDataRequestResponse(StrictModel):
    id: UUID
    account_id: UUID | None
    created_by: UUID
    created_by_email: str | None = None
    request_type: str
    reason: str
    created_at: datetime
    state: str
    last_event_at: datetime | None = None


class SecurityDataOverviewResponse(StrictModel):
    membership: dict[str,Any]
    google_connections: list[dict[str,Any]]
    legal_acceptances: list[dict[str,Any]]
    security_events: list[dict[str,Any]]
    data_requests: list[CustomerDataRequestResponse]
    retention: dict[str,str]
