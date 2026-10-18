export type Membership = { tenant_id:string; tenant_name?:string; tenant_slug?:string; role:"viewer"|"analyst"|"admin"|"owner"; status:string; account_access_mode?:"all_accounts"|"selected_accounts"; client_portal?:boolean };
export type Me = { user_id: string; email: string | null; memberships: Membership[] };
export type Account = { id: string; customer_id: string; descriptive_name: string; currency_code: string; time_zone: string; account_status: string; test_account: boolean };
export type WorkspaceStage = { id: string | null; status: string; started_at: string | null; completed_at: string | null; detail: Record<string, unknown> };
export type Workspace = {
  account: Account;
  latest_sync: WorkspaceStage;
  latest_truth: WorkspaceStage;
  latest_analysis: WorkspaceStage;
  currency_code: string | null;
  potentially_avoidable_observed_micros: number;
  visible_search_term_micros: number;
  unobserved_search_micros: number;
  coverage_band: string | null;
  query_count: number;
  review_required_count: number;
  proposal_count: number;
  ready_for_approval_count: number;
  verified_recovery_micros: number;
  verified_recovery_entries: number;
  last_updated_at: string | null;
};
export type Finding = { artifact_id: string; analysis_run_id: string; artifact_kind: string; external_id: string; artifact_fingerprint: string; currency_code: string | null; money_micros: number | null; payload: Record<string, any>; created_at: string };
export type Ledger = { entry_id: string; analysis_run_id: string; currency_code: string; historical_candidate_micros: number; projected_prevented_micros: number; observed_post_action_query_spend_micros: number; verified_recovery_micros: number; causal_status: string; created_at: string };

export type ProposalState = { artifact_id:string; analysis_run_id:string; artifact_fingerprint:string; currency_code:string|null; money_micros:number|null; payload:Record<string,any>; decision:string|null; decision_event_id:string|null; decided_at:string|null; mutation_event_type:string|null; resource_name:string|null; mutation_occurred_at:string|null; created_at:string };

export type BillingPlan = { key:string; display_name:string; currency:string; amount_subunits:number; max_google_ads_accounts:number; max_sync_range_days:number };
export type BillingAccountSlot = { account_id:string; customer_id:string; descriptive_name:string; occurred_at:string };
export type BillingProfile = { id:string; legal_name:string; billing_email:string; tax_country:string; tax_region:string|null; gstin:string|null; actor_user_id:string; occurred_at:string };
export type BillingStatus = { enabled:boolean; plan_key:string|null; provider_status:string|null; entitlement_state:string; current_start:string|null; current_end:string|null; provider_subscription_id:string|null; payment_method:string|null; grace_until:string|null; has_scheduled_changes:boolean; pending_plan_key:string|null; pending_plan_effective_at:string|null; cancellation_scheduled:boolean; cancellation_effective_at:string|null; account_slots:BillingAccountSlot[]; billing_profile:BillingProfile|null };
export type BillingCheckout = { checkout_intent_id:string; plan_key:string; provider_subscription_id:string; checkout_url:string|null; state:string; idempotency_replay:boolean };
export type BillingPlanChangePreview = { current_plan_key:string|null; target_plan:BillingPlan; provider_status:string; payment_method:string|null; automated_change_supported:boolean; schedule_change_at:"cycle_end"; effective_at:string|null; active_account_slots:number; accounts_over_target_limit:Array<{account_id:string;customer_id:string|null;descriptive_name:string|null}>; note:string };
export type BillingLifecycleEvent = { id:string; event_type:string; actor:string; payload:Record<string,any>; occurred_at:string };
export type BillingLifecycleOperation = { id:string; tenant_id:string; requested_by:string; operation_type:string; provider_subscription_id:string; target_plan_key:string|null; idempotency_key:string; request_sha256:string; effective_at:string|null; created_at:string; state:string; events:BillingLifecycleEvent[] };
export type BillingInvoice = { provider_invoice_id:string; provider_payment_id:string|null; status:string; currency:string; amount:number; amount_paid:number; amount_due:number; issued_at:string|null; paid_at:string|null; observed_at:string };
export type BillingInvoiceRefresh = { provider_subscription_id:string; provider_count:number; new_snapshots:number; invoices:BillingInvoice[] };
export type BillingEntitlementHistory = { id:string; provider_subscription_id:string; provider_plan_id:string; plan_key:string; provider_status:string; entitlement_state:string; current_start:string|null; current_end:string|null; payment_method:string|null; has_scheduled_changes:boolean; change_scheduled_at:string|null; grace_until:string|null; observed_at:string };

export type Portfolio = { id:string; name:string; description:string|null; account_count:number; created_at:string; updated_at:string };
export type PortfolioDetail = Portfolio & { accounts:Array<{id:string; customer_id:string; descriptive_name:string; currency_code:string; time_zone:string; account_status:string}> };
export type ShellTask = { id:string; account_id:string|null; portfolio_id:string|null; title:string; description:string|null; source_type:string; source_id:string|null; priority:"low"|"normal"|"high"|"urgent"; status:"open"|"in_progress"|"blocked"|"done"|"cancelled"; assigned_to:string|null; due_at:string|null; created_by:string; created_at:string; updated_at:string; completed_at:string|null };
export type UserNotification = { id:string; kind:string; severity:"info"|"success"|"warning"|"critical"; title:string; body:string|null; href:string|null; source_type:string|null; source_id:string|null; read_at:string|null; created_at:string };
export type SearchResult = { kind:string; id:string; title:string; subtitle:string|null; href:string };
export type MoneyBucket = { currency_code:string; potentially_avoidable_observed_micros:number; verified_recovery_micros:number };
export type CommandAccount = { id:string; customer_id:string; descriptive_name:string; currency_code:string; time_zone:string; latest_sync_at:string|null; latest_analysis_at:string|null; data_status:"current"|"delayed"|"stale"|"unavailable"; potentially_avoidable_observed_micros:number; verified_recovery_micros:number; ready_for_approval_count:number };
export type CommandCenter = { tenant_id:string; tenant_name:string; account_count:number; portfolio_count:number; open_task_count:number; unread_notification_count:number; ready_for_approval_count:number; current_account_count:number; stale_account_count:number; money_by_currency:MoneyBucket[]; accounts:CommandAccount[]; generated_at:string };

export type OnboardingAccountActivation = { id:string; customer_id:string; descriptive_name:string; currency_code:string; business_truth_ready:boolean; measurement_ready:boolean; sync_ready:boolean; analysis_ready:boolean };
export type OnboardingStatus = { current_step:string; completed_steps:string[]; started_at:string; updated_at:string; completed_at:string|null; connected_google_users:number; selected_accounts:number; truth_snapshots:number; measurement_profiles:number; completed_syncs:number; completed_analyses:number; proposal_count:number; account_activation:OnboardingAccountActivation[] };
export type DiscoveredGoogleAdsAccount = { id:string; connection_id:string; customer_id:string; descriptive_name:string; currency_code:string; time_zone:string; manager:boolean; account_status:string; test_account:boolean; direct_access:boolean; login_customer_id:string|null; hierarchy_level:number; selected_at:string|null };
export type GoogleOAuthStart = { authorization_url:string };
export type GoogleOAuthCallback = { tenant_id:string; connection_id:string; discovery_job:{job_id:string;job_type:string;status:string;idempotency_replay:boolean}; return_path:string };
export type MeasurementProfile = { conversion_lag_days:number; configured_at:string|null; updated_at:string|null };
export type JobDetail = { job_id:string; job_type:string; status:string; result:Record<string,unknown>|null; failure_code:string|null; failure_detail:string|null; created_at:string; started_at:string|null; completed_at:string|null };

export type SearchWindow = { start:string; end:string; min_available:string; max_available:string };
export type SearchCoverage = { currency_code:string; visible_search_term_micros:number; comparable_search_campaign_micros:number; unobserved_search_micros:number; coverage_ratio:string|null; coverage_band:string; note:string };
export type SearchOverview = { account_id:string; currency_code:string; window:SearchWindow; distinct_queries:number; impressions:number; clicks:number; cost_micros:number; conversions:string; conversions_value:string; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; latest_analysis_run_id:string|null; latest_analysis_completed_at:string|null; analysis_window_matches:boolean; fit_counts:Record<string,number>; evidence_counts:Record<string,number>; coverage:SearchCoverage };
export type SearchTermRow = { normalized_query:string; raw_query_example:string; impressions:number; clicks:number; cost_micros:number; conversions:string; conversions_value:string; all_conversions:string; all_conversions_value:string; campaign_count:number; ad_group_count:number; first_observation_date:string; last_observation_date:string; networks:string[]; match_sources:string[]; fit_disposition:string|null; semantic_status:string|null; primary_intent:string|null; evidence_status:string|null; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; analysis_run_id:string|null; financial_evidence_in_window:boolean };
export type SearchTermPage = { window:SearchWindow; currency_code:string; page:number; page_size:number; total:number; rows:SearchTermRow[] };
export type SearchBreakdownRow = { key:string; query_count:number; impressions:number; clicks:number; cost_micros:number; conversions:string; conversions_value:string; potentially_avoidable_observed_micros:number };
export type SearchBreakdown = { window:SearchWindow; currency_code:string; dimension:string; rows:SearchBreakdownRow[] };
export type SearchNGramRow = { ngram:string; query_count:number; impressions:number; clicks:number; cost_micros:number; conversions:string; conversions_value:string; potentially_avoidable_observed_micros:number };
export type SearchNGram = { window:SearchWindow; currency_code:string; n:number; sort:string; without_conversions:boolean; rows:SearchNGramRow[] };
export type SearchTermDetail = { account_id:string; currency_code:string; window:SearchWindow; term:SearchTermRow; scope_breakdown:Array<{campaign_id:string;campaign_name:string;ad_group_id:string;ad_group_name:string;network:string;match_source:string;triggering_keyword:string|null;triggering_keyword_match_type:string|null;impressions:number;clicks:number;cost_micros:number;conversions:string;conversions_value:string;first_observation_date:string;last_observation_date:string}>; daily:Array<{date:string;impressions:number;clicks:number;cost_micros:number;conversions:string;conversions_value:string}>; semantic_assessment:Record<string,unknown>|null; business_fit:Record<string,unknown>|null; financial_findings:Array<Record<string,unknown>>; coverage_note:string };
export type SearchSavedView = { id:string; account_id:string|null; portfolio_id:string|null; name:string; filters:Record<string,unknown>; is_default:boolean; created_at:string; updated_at:string };
export type PortfolioNGram = { portfolio_id:string; start:string; end:string; n:number; rows:Array<{currency_code:string;ngram:string;account_count:number;query_count:number;impressions:number;clicks:number;cost_micros:number;conversions:string;conversions_value:string}> };

export type WasteFamilySummary = { leak_family:string; query_count:number; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; already_addressed_observed_micros:number };
export type WasteOverview = { account_id:string; window:SearchWindow; currency_code:string; analysis_run_id:string|null; analysis_window_matches:boolean; query_potentially_avoidable_observed_micros:number; query_review_required_observed_micros:number; geo_potentially_avoidable_observed_micros:number; geo_review_required_observed_micros:number; families:WasteFamilySummary[]; dimension_data_ready:boolean; geo_data_ready:boolean; geo_evaluation_ready:boolean; financial_note:string };
export type WasteQueryRow = { normalized_query:string; raw_query_example:string; leak_family:string; disposition:string; impressions:number; clicks:number; cost_micros:number; conversions:string; networks:string[]; finding_count:number; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; already_addressed_observed_micros:number };
export type WasteQueryPage = { window:SearchWindow; currency_code:string; analysis_run_id:string|null; financial_evidence_in_window:boolean; page:number; page_size:number; total:number; rows:WasteQueryRow[] };
export type WasteDimensionRow = { key:string; query_count:number; impressions:number; clicks:number; cost_micros:number; conversions:string; conversions_value:string; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; financial_claim_supported:boolean };
export type WasteDimension = { window:SearchWindow; currency_code:string; dimension:"network"|"device"|"daypart"; rows:WasteDimensionRow[]; note:string };
export type WasteGeoRow = { location_resource:string; location_name:string; canonical_name:string|null; country_code:string|null; target_type:string|null; disposition:string; reason:string; mature_cost_micros:number; immature_cost_micros:number; potentially_avoidable_observed_micros:number; review_required_observed_micros:number; mature_conversions:string; row_count:number };
export type WasteGeo = { window:SearchWindow; currency_code:string; evaluation_ready:boolean; analysis_run_id:string|null; truth_snapshot_id:string|null; rows:WasteGeoRow[]; note:string };

export type MeasurementIssue={code:string;severity:"info"|"warning"|"blocker";message:string;conversion_action_resource:string|null;campaign_id:string|null};
export type MeasurementOverview={account_id:string;measurement_snapshot_id:string|null;sync_run_id:string|null;sync_completed_at:string|null;window_start:string|null;window_end:string|null;confidence:"strong"|"constrained"|"blocked"|"unknown";enabled_actions:number;primary_actions:number;mapped_primary_actions:number;conversion_dependent_claims_allowed:boolean;recovery_verification_allowed:boolean;configured_conversion_lag_days:number|null;customer_goal_count:number;campaign_goal_count:number;campaign_specific_goal_config_count:number;issues:MeasurementIssue[];available_outcomes:Array<{outcome_id:string;name:string;role:string;confirmed:boolean}>;note:string};
export type MeasurementConversionAction={resource_name:string;action_id:string;name:string;status:string;action_type:string;category:string;origin:string;owner_customer:string|null;primary_for_goal:boolean;account_default_goal_biddable:boolean|null;counting_type:string;click_through_lookback_days:number;view_through_lookback_days:number;attribution_model:string;data_driven_model_status:string;default_value:string;default_currency_code:string|null;always_use_default_value:boolean;all_conversions:string;all_conversions_value:string;last_conversion_date:string|null;last_received_request_at:string|null;mapped_outcome_id:string|null;mapped_outcome_role:string|null;mapping_confirmed:boolean;mapping_is_current_truth:boolean;mapping_status:string|null;enhanced_conversions_status:string};
export type MeasurementGoals={customer_goals:Array<Record<string,unknown>>;campaign_goals:Array<Record<string,unknown>>;campaign_configs:Array<Record<string,unknown>>;note:string};
export type MeasurementLag={configured_conversion_lag_days:number|null;rows:Array<{conversion_action_resource:string;conversion_action_name:string;category:string;lag_bucket:string;conversions:string;all_conversions:string;conversions_value:string;all_conversions_value:string}>;note:string};

export type RecoveryCaseSummary = {
  case_id:string; account_id:string; account_name:string; analysis_run_id:string; proposal_fingerprint:string;
  proposal_id:string|null; query:string|null; match_type:string|null; scope:string|null; campaign_id:string|null; ad_group_id:string|null;
  risk:string|null; disposition:string|null; currency_code:string|null; candidate_exposure_micros:number; collision_count:number;
  state:string; stale:boolean; stale_reasons:string[]; execution_allowed:boolean; rollback_allowed:boolean; verification_status:string;
  assigned_to:string|null; closed:boolean; execution_job_status:string|null; external_effect_state:string|null; measurement_confidence:string|null; conversion_claims_allowed:boolean; recovery_verification_allowed:boolean; measurement_issue_codes:string[]; created_at:string;
};
export type RecoveryCaseDetail = RecoveryCaseSummary & {
  proposal:Record<string,any>; financial_findings:Array<Record<string,any>>; decision_events:Array<Record<string,any>>;
  mutation_events:Array<Record<string,any>>; recovery_ledger:Array<Record<string,any>>; case_events:Array<Record<string,any>>;
  latest_truth_fingerprint:string|null; latest_analysis_run_id:string|null; analysis_truth_fingerprint:string;
  execution_jobs:Array<Record<string,any>>; external_effects:Array<Record<string,any>>;
};

export type RecoveryCenterMoneyBucket = {
  currency_code:string;
  current_observed_candidate_micros:number;
  current_unobserved_search_micros:number;
  acted_on_historical_candidate_micros:number;
  projected_prevented_micros:number;
  observed_post_action_query_spend_micros:number;
  observed_difference_vs_projection_micros:number;
  verified_recovery_micros:number;
  ledger_action_count:number;
  verified_action_count:number;
  inconclusive_action_count:number;
  verification_pending_action_count:number;
};
export type RecoveryCenterOverview = {scope_kind:"organization"|"portfolio"|"account";scope_id:string;scope_name:string;account_count:number;money_by_currency:RecoveryCenterMoneyBucket[];case_counts:Record<string,number>;generated_at:string;financial_classes_are_non_additive:boolean;verified_recovery_requires_causal_evidence:boolean;note:string};
export type RecoveryCenterCase = {case_id:string;account_id:string;account_name:string;query:string|null;campaign_id:string|null;campaign_name:string|null;leak_family:string;state:string;currency_code:string;historical_candidate_micros:number;projected_prevented_micros:number;observed_post_action_query_spend_micros:number;observed_difference_vs_projection_micros:number;verified_recovery_micros:number;causal_status:string;ledger_created_at:string|null;mutation_event_id:string|null;applied_at:string|null};
export type RecoveryCenterBreakdown = {dimension:"account"|"campaign"|"leak_type";rows:Array<{key:string;label:string;currency_code:string;action_count:number;historical_candidate_micros:number;projected_prevented_micros:number;observed_post_action_query_spend_micros:number;verified_recovery_micros:number}>;note:string};
export type RecoveryCenterTimeline = {rows:Array<{date:string;currency_code:string;ledger_updates:number;historical_candidate_micros:number;projected_prevented_micros:number;observed_post_action_query_spend_micros:number;verified_recovery_micros:number}>;note:string};

export type MonitoringAlertEvent={id:string;event_type:string;severity:string|null;actor:string;payload:Record<string,any>;occurred_at:string};
export type MonitorAlert={id:string;account_id:string;monitor_type:string;source_key:string;alert_fingerprint:string;generation:number;initial_severity:string;title:string;first_evidence:Record<string,any>;latest_evidence:Record<string,any>;opened_at:string;state:"open"|"acknowledged"|"resolved"|"dismissed";severity:"info"|"warning"|"critical";assigned_to:string|null;last_seen_at:string;occurrence_count:number};
export type MonitorAlertDetail=MonitorAlert&{events:MonitoringAlertEvent[]};
export type MonitoringOverview={account_id:string|null;counts:Record<string,number>;active_by_monitor_type:Array<{monitor_type:string;count:number}>;recent_alerts:MonitorAlert[];generated_at:string;note:string};
export type MonitoringPolicy={monitor_type:string;enabled:boolean;severity_override:string|null;config:Record<string,any>;scope:string;updated_at:string|null};

export type ReportTemplate={report_type:string;name:string;supported_scopes:string[];requires_period:boolean;description:string};
export type ReportArtifactMeta={format:"pdf"|"csv";byte_size:number;sha256:string;content_type?:string|null};
export type ReportGenerationSummary={id:string;report_type:string;template_version:string;schema_version:string;scope_kind:"organization"|"portfolio"|"account";scope_id:string;period_start:string|null;period_end:string|null;generated_by:string;source_job_id:string|null;schedule_id:string|null;snapshot_sha256:string;generated_at:string;artifacts:ReportArtifactMeta[]};
export type ReportGenerationDetail=ReportGenerationSummary&{snapshot:Record<string,any>;deliveries:Array<Record<string,any>>};
export type ReportShare={id:string;generation_id:string;expires_at:string;state:"active"|"expired"|"revoked";created_at:string;access_count:number|null;token?:string|null};
export type ReportSchedule={id:string;schedule_id:string;report_type:string;scope_kind:"organization"|"portfolio"|"account";scope_id:string;frequency:"daily"|"weekly"|"monthly";timezone_name:string;hour:number;minute:number;weekday:number|null;day_of_month:number|null;recipients:string[];enabled:boolean;actor_user_id:string;occurred_at:string};
export type PublicReport={share:{expires_at:string};generation:{id:string;report_type:string;snapshot_sha256:string;generated_at:string;snapshot:Record<string,any>;artifacts:ReportArtifactMeta[]}};

export type OrganizationMember={user_id:string;email:string|null;role:string;status:string;account_access_mode:string;client_portal:boolean;created_at:string;updated_at:string;accessible_account_count:number;assignments:Array<Record<string,unknown>>};
export type OrganizationInvite={id:string;email:string;role:string;account_access_mode:string;client_portal:boolean;expires_at:string;state:string;created_at:string;token?:string|null};
export type ClientWorkspace={workspace_id:string;name:string;external_reference:string|null;notes:string|null;state:string;occurred_at:string;accounts:Array<{id:string;customer_id:string;descriptive_name:string;currency_code:string}>;members:Array<{user_id:string;email:string|null;role:string;client_portal:boolean}>};
export type AccountAssignment={account_id:string;user_id:string;email:string|null;responsibility:string;state:string;occurred_at:string};
export type OrganizationActivity={id:string;actor_user_id:string;actor_email:string|null;event_type:string;target_type:string;target_id:string;occurred_at:string;payload:Record<string,unknown>};
export type MemberAccountAccessDetail={account_id:string;customer_id:string;descriptive_name:string;accessible:boolean;sources:string[]};

export type InternalMe={user_id:string;email:string|null;operator_role:"support_viewer"|"support_engineer"|"platform_admin"|"security_auditor"};
export type InternalTenantSummary={tenant_id:string;slug:string;display_name:string;first_seen_at:string;account_count:number;active_member_count:number;active_job_count:number};
export type InternalTenantDiagnostics={tenant:Record<string,any>;accounts:Array<Record<string,any>>;members:Array<Record<string,any>>;job_counts:Record<string,number>;reconciliation:Array<Record<string,any>>;billing:Record<string,any>|null;latest_sync:Record<string,any>|null;latest_analysis:Record<string,any>|null;semantic_releases:Array<Record<string,any>>;feature_controls:Array<Record<string,any>>};
export type InternalJob={id:string;job_type:string;status:string;attempts:number;max_attempts:number;requested_by:string;endpoint:string;operation_key:string|null;failure_code:string|null;created_at:string;started_at:string|null;completed_at:string|null};
export type InternalSupportCase={id:string;title:string;category:string;severity:string;opened_by?:string|null;created_at?:string|null;latest_event:string;updated_at?:string|null};
export type InternalFeatureControl={feature_key:string;enabled:boolean;reason:string;occurred_at:string|null;actor_user_id:string|null};
export type InternalIncident={incident_id:string;event_type:string;severity:string;title:string;payload:Record<string,any>;occurred_at:string;actor_user_id:string};
export type InternalReleaseObservation={tenant_id:string;tenant_name:string;job_id:string;release_id:string;worker_version:string;completed_at:string};

export type PublicLaunchStatus={launch_mode:"closed"|"pilot_only"|"invite_only"|"public";workspace_creation_open:boolean;access_granted:boolean;access_hint:string|null;access_expires_at:string|null;release_id:string|null;terms_url:string|null;terms_version:string|null;privacy_url:string|null;privacy_version:string|null;legal_acceptance_ready:boolean;signup_abuse_ready:boolean;turnstile_site_key:string|null;public_workspace_max_per_user_24h:number|null};
export type InternalLaunchQualification={id:string;release_id:string;report_sha256:string;report_generated_at:string;occurred_at:string;imported_by:string};
export type InternalLaunchStatus={id:string|null;launch_mode:"closed"|"pilot_only"|"invite_only"|"public";release_id:string|null;qualification_id:string|null;reason:string;occurred_at:string|null;actor_user_id:string|null;active_access_grants:number;qualifications:InternalLaunchQualification[]};
export type InternalLaunchAccess={id:string;subject_email_sha256:string;subject_hint:string;event_type:"granted"|"revoked";expires_at:string|null;reason:string;actor_user_id:string;occurred_at:string};

export type TruthReadinessIssue={code:string;message:string;blocker:boolean};
export type TruthReadiness={ready:boolean;issues:TruthReadinessIssue[]};
export type BusinessTruthVersion={id:string;account_id:string;truth_fingerprint:string;schema_version:number;version:number;business_id:string|null;business_name:string|null;supersedes_version:number|null;created_by:string;created_at:string;offer_count:number;non_offer_count:number;intent_policy_count:number;audience_policy_count:number;service_area_count:number;outcome_count:number;protected_query_count:number;readiness:Record<string,TruthReadiness>;changed_sections:string[];payload:Record<string,any>};

export type CustomerSupportEvent={id:string;event_type:string;actor_user_id:string;actor_email:string|null;payload:Record<string,any>;occurred_at:string};
export type CustomerSupportCase={id:string;account_id:string|null;created_by:string;created_by_email:string|null;category:string;subject:string;initial_body:string;created_at:string;state:"open"|"closed";comment_count:number|null;last_event_at:string|null;events?:CustomerSupportEvent[]|null};
export type CustomerDataRequest={id:string;account_id:string|null;created_by:string;created_by_email:string|null;request_type:string;reason:string;created_at:string;state:string;last_event_at:string|null};
export type SecurityDataOverview={membership:Record<string,any>;google_connections:Array<Record<string,any>>;legal_acceptances:Array<Record<string,any>>;security_events:Array<Record<string,any>>;data_requests:CustomerDataRequest[];retention:Record<string,string>};
export type BuildInfo={service:string;version:string;release_id:string};
