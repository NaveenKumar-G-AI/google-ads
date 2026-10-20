import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { Account, Finding, Ledger, Me, ProposalState, Workspace, BillingPlan, BillingStatus, BillingCheckout, BillingPlanChangePreview, BillingLifecycleOperation, BillingInvoice, BillingInvoiceRefresh, BillingEntitlementHistory, BillingProfile, BillingAccountSlot, OnboardingStatus, DiscoveredGoogleAdsAccount, GoogleOAuthStart, MeasurementProfile, JobDetail } from "@/lib/types";

const API = process.env.RECOVERY_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function accessToken(): Promise<string> {
  const supabase = await createClient();
  const { data: claimsData, error: claimsError } = await supabase.auth.getClaims();
  if (claimsError || !claimsData?.claims?.sub) redirect("/login");
  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData.session?.access_token;
  if (!token) redirect("/login");
  return token;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await accessToken();
  const response = await fetch(`${API}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers ?? {}) }
  });
  if (response.status === 401) redirect("/login");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Recovery API request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  const raw = await response.text();
  if (!raw) return undefined as T;
  return JSON.parse(raw) as T;
}

export const getMe = () => apiFetch<Me>("/v1/me");
export const getAccounts = (tenantId: string) => apiFetch<Account[]>(`/v1/tenants/${tenantId}/accounts`);
export const getWorkspace = (tenantId: string, accountId: string) => apiFetch<Workspace>(`/v1/tenants/${tenantId}/accounts/${accountId}/workspace`);
export const getFindings = (tenantId: string, accountId: string, kind?: string) => apiFetch<Finding[]>(`/v1/tenants/${tenantId}/findings?account_id=${encodeURIComponent(accountId)}${kind ? `&kind=${encodeURIComponent(kind)}` : ""}&limit=200`);
export const getLedger = (tenantId: string, accountId: string) => apiFetch<Ledger[]>(`/v1/tenants/${tenantId}/recovery-ledger?account_id=${encodeURIComponent(accountId)}&limit=200`);

export const getProposals = (tenantId:string, accountId:string, analysisRunId?:string|null) => apiFetch<ProposalState[]>(`/v1/tenants/${tenantId}/proposals?account_id=${encodeURIComponent(accountId)}${analysisRunId?`&analysis_run_id=${encodeURIComponent(analysisRunId)}`:""}&limit=200`);

export const getBillingPlans = () => apiFetch<BillingPlan[]>("/v1/billing/plans");
export const getBillingStatus = (tenantId:string) => apiFetch<BillingStatus>(`/v1/tenants/${tenantId}/billing`);
export const createBillingCheckout = (tenantId:string, planKey:string, idempotencyKey:string) => apiFetch<BillingCheckout>(`/v1/tenants/${tenantId}/billing/checkout`, { method:"POST", headers:{"Idempotency-Key":idempotencyKey}, body:JSON.stringify({plan_key:planKey}) });
export const reconcileBilling = (tenantId:string) => apiFetch<BillingStatus & {snapshot_id:string}>(`/v1/tenants/${tenantId}/billing/reconcile`, { method:"POST" });
export const previewBillingPlanChange=(tenantId:string,targetPlanKey:string)=>apiFetch<BillingPlanChangePreview>(`/v1/tenants/${tenantId}/billing/plan-change/preview`,{method:"POST",body:JSON.stringify({target_plan_key:targetPlanKey})});
export const scheduleBillingPlanChange=(tenantId:string,targetPlanKey:string,key:string)=>apiFetch<BillingLifecycleOperation>(`/v1/tenants/${tenantId}/billing/plan-change`,{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify({target_plan_key:targetPlanKey})});
export const cancelBillingPlanChange=(tenantId:string,key:string)=>apiFetch<BillingLifecycleOperation>(`/v1/tenants/${tenantId}/billing/plan-change/cancel`,{method:"POST",headers:{"Idempotency-Key":key},body:"{}"});
export const cancelBillingAtCycleEnd=(tenantId:string,key:string)=>apiFetch<BillingLifecycleOperation>(`/v1/tenants/${tenantId}/billing/cancel`,{method:"POST",headers:{"Idempotency-Key":key},body:"{}"});
export const getBillingInvoices=(tenantId:string)=>apiFetch<BillingInvoice[]>(`/v1/tenants/${tenantId}/billing/invoices?limit=200`);
export const refreshBillingInvoices=(tenantId:string)=>apiFetch<BillingInvoiceRefresh>(`/v1/tenants/${tenantId}/billing/invoices/refresh`,{method:"POST",body:"{}"});
export const getBillingHistory=(tenantId:string)=>apiFetch<BillingEntitlementHistory[]>(`/v1/tenants/${tenantId}/billing/history?limit=200`);
export const getBillingProfile=(tenantId:string)=>apiFetch<BillingProfile|null>(`/v1/tenants/${tenantId}/billing/profile`);
export const saveBillingProfile=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<BillingProfile>(`/v1/tenants/${tenantId}/billing/profile`,{method:"POST",body:JSON.stringify(payload)});
export const getBillingAccountSlots=(tenantId:string)=>apiFetch<BillingAccountSlot[]>(`/v1/tenants/${tenantId}/billing/account-slots`);
export const releaseBillingAccountSlot=(tenantId:string,accountId:string)=>apiFetch<void>(`/v1/tenants/${tenantId}/billing/account-slots/${accountId}/release`,{method:"POST",body:"{}"});

import type { Portfolio, PortfolioDetail, ShellTask, UserNotification, SearchResult, CommandCenter } from "@/lib/types";

export const getCommandCenter = (tenantId:string) => apiFetch<CommandCenter>(`/v1/tenants/${tenantId}/command-center`);
export const getPortfolios = (tenantId:string) => apiFetch<Portfolio[]>(`/v1/tenants/${tenantId}/portfolios`);
export const getPortfolio = (tenantId:string, portfolioId:string) => apiFetch<PortfolioDetail>(`/v1/tenants/${tenantId}/portfolios/${portfolioId}`);
export const createPortfolio = (tenantId:string, name:string, description:string|null) => apiFetch<Portfolio>(`/v1/tenants/${tenantId}/portfolios`,{method:"POST",body:JSON.stringify({name,description})});
export const addPortfolioAccount = (tenantId:string, portfolioId:string, accountId:string) => apiFetch<void>(`/v1/tenants/${tenantId}/portfolios/${portfolioId}/accounts`,{method:"POST",body:JSON.stringify({account_id:accountId})});
export const removePortfolioAccount = (tenantId:string, portfolioId:string, accountId:string) => apiFetch<void>(`/v1/tenants/${tenantId}/portfolios/${portfolioId}/accounts/${accountId}/remove`,{method:"POST"});
export const getTasks = (tenantId:string, scope="all", accountId?:string|null, status?:string|null) => apiFetch<ShellTask[]>(`/v1/tenants/${tenantId}/tasks?scope=${encodeURIComponent(scope)}${accountId?`&account_id=${encodeURIComponent(accountId)}`:""}${status?`&status=${encodeURIComponent(status)}`:""}&limit=200`);
export const createTask = (tenantId:string, payload:Record<string,unknown>) => apiFetch<ShellTask>(`/v1/tenants/${tenantId}/tasks`,{method:"POST",body:JSON.stringify(payload)});
export const updateTaskStatus = (tenantId:string, taskId:string, status:string) => apiFetch<ShellTask>(`/v1/tenants/${tenantId}/tasks/${taskId}/status`,{method:"POST",body:JSON.stringify({status})});
export const getNotifications = (tenantId:string, unreadOnly=false) => apiFetch<UserNotification[]>(`/v1/tenants/${tenantId}/notifications?unread_only=${unreadOnly?"true":"false"}&limit=200`);
export const markNotificationRead = (tenantId:string, id:string) => apiFetch<UserNotification>(`/v1/tenants/${tenantId}/notifications/${id}/read`,{method:"POST"});
export const globalSearch = (tenantId:string, q:string) => apiFetch<SearchResult[]>(`/v1/tenants/${tenantId}/search?q=${encodeURIComponent(q)}&limit=25`);

export const createOrganization = (displayName:string, slug:string|null, idempotencyKey:string, legalAcceptanceConfirmed:boolean=false, acceptedTermsVersion:string|null=null, acceptedPrivacyVersion:string|null=null, turnstileToken:string|null=null) => apiFetch<{tenant_id:string;idempotency_replay:boolean}>(`/v1/onboarding/organizations`,{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:JSON.stringify({display_name:displayName,slug,legal_acceptance_confirmed:legalAcceptanceConfirmed,accepted_terms_version:acceptedTermsVersion,accepted_privacy_version:acceptedPrivacyVersion,turnstile_token:turnstileToken})});
export const getOnboardingStatus = (tenantId:string) => apiFetch<OnboardingStatus>(`/v1/tenants/${tenantId}/onboarding`);
export const startGoogleAdsOAuth = (tenantId:string, returnPath:string, loginHint?:string|null) => apiFetch<GoogleOAuthStart>(`/v1/tenants/${tenantId}/onboarding/google-ads/oauth/start`,{method:"POST",body:JSON.stringify({return_path:returnPath,login_hint:loginHint??null})});
export const getDiscoveredGoogleAdsAccounts = (tenantId:string) => apiFetch<DiscoveredGoogleAdsAccount[]>(`/v1/tenants/${tenantId}/onboarding/google-ads/accounts`);
export const selectGoogleAdsAccounts = (tenantId:string, customerIds:string[]) => apiFetch<Account[]>(`/v1/tenants/${tenantId}/onboarding/google-ads/accounts/select`,{method:"POST",body:JSON.stringify({customer_ids:customerIds})});
export const saveGuidedBusinessTruth = (tenantId:string, accountId:string, payload:Record<string,unknown>, idempotencyKey:string) => apiFetch<{truth_snapshot_id:string;truth_fingerprint:string;version:number;idempotency_replay:boolean}>(`/v1/tenants/${tenantId}/accounts/${accountId}/business-truth/guided`,{method:"POST",headers:{"Idempotency-Key":idempotencyKey},body:JSON.stringify(payload)});
export const saveMeasurementProfile = (tenantId:string, accountId:string, days:number) => apiFetch<MeasurementProfile>(`/v1/tenants/${tenantId}/accounts/${accountId}/onboarding/measurement`,{method:"POST",body:JSON.stringify({conversion_lag_days:days})});
export const getMeasurementProfile = (tenantId:string, accountId:string) => apiFetch<MeasurementProfile|null>(`/v1/tenants/${tenantId}/accounts/${accountId}/onboarding/measurement`);
export const startAccountSync = (tenantId:string, accountId:string, start:string, end:string, key:string) => apiFetch<{job_id:string;job_type:string;status:string;idempotency_replay:boolean}>(`/v1/tenants/${tenantId}/accounts/${accountId}/syncs`,{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify({start,end})});
export const startAccountAnalysis = (tenantId:string, accountId:string, payload:{sync_run_id:string;truth_snapshot_id:string;as_of:string;conversion_lag_days:number}, key:string) => apiFetch<{job_id:string;job_type:string;status:string;idempotency_replay:boolean}>(`/v1/tenants/${tenantId}/accounts/${accountId}/analyses`,{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify(payload)});
export const getJob = (tenantId:string, jobId:string) => apiFetch<JobDetail>(`/v1/tenants/${tenantId}/jobs/${jobId}`);
export const completeOnboarding = (tenantId:string) => apiFetch<void>(`/v1/tenants/${tenantId}/onboarding/complete`,{method:"POST"});

import type { SearchOverview, SearchTermPage, SearchTermDetail, SearchBreakdown, SearchNGram, SearchSavedView, PortfolioNGram } from "@/lib/types";
const searchWindowParams=(start?:string|null,end?:string|null)=>`${start?`&start=${encodeURIComponent(start)}`:""}${end?`&end=${encodeURIComponent(end)}`:""}`;
export const getSearchOverview=(tenantId:string,accountId:string,start?:string|null,end?:string|null)=>{const w=searchWindowParams(start,end);return apiFetch<SearchOverview>(`/v1/tenants/${tenantId}/accounts/${accountId}/search-intelligence/overview${w?`?${w.slice(1)}`:""}`)};
export const getSearchTerms=(tenantId:string,accountId:string,p:{start?:string|null;end?:string|null;query?:string|null;network?:string|null;fit?:string|null;sort?:string;direction?:string;page?:number;pageSize?:number}={})=>apiFetch<SearchTermPage>(`/v1/tenants/${tenantId}/accounts/${accountId}/search-intelligence/terms?sort=${encodeURIComponent(p.sort||"cost")}&direction=${encodeURIComponent(p.direction||"desc")}&page=${p.page||1}&page_size=${p.pageSize||50}${searchWindowParams(p.start,p.end)}${p.query?`&query=${encodeURIComponent(p.query)}`:""}${p.network?`&network=${encodeURIComponent(p.network)}`:""}${p.fit?`&fit=${encodeURIComponent(p.fit)}`:""}`);
export const getSearchTermDetail=(tenantId:string,accountId:string,query:string,start?:string|null,end?:string|null)=>apiFetch<SearchTermDetail>(`/v1/tenants/${tenantId}/accounts/${accountId}/search-intelligence/term?query=${encodeURIComponent(query)}${searchWindowParams(start,end)}`);
export const getSearchBreakdown=(tenantId:string,accountId:string,dimension:string,start?:string|null,end?:string|null)=>apiFetch<SearchBreakdown>(`/v1/tenants/${tenantId}/accounts/${accountId}/search-intelligence/breakdown?dimension=${encodeURIComponent(dimension)}${searchWindowParams(start,end)}`);
export const getSearchNGrams=(tenantId:string,accountId:string,p:{start?:string|null;end?:string|null;n?:number;sort?:string;limit?:number;withoutConversions?:boolean}={})=>apiFetch<SearchNGram>(`/v1/tenants/${tenantId}/accounts/${accountId}/search-intelligence/ngrams?n=${p.n||1}&sort=${encodeURIComponent(p.sort||"cost")}&limit=${p.limit||100}&without_conversions=${p.withoutConversions?"true":"false"}${searchWindowParams(p.start,p.end)}`);
export const getSearchSavedViews=(tenantId:string,accountId?:string|null,portfolioId?:string|null)=>apiFetch<SearchSavedView[]>(`/v1/tenants/${tenantId}/search-intelligence/saved-views?${accountId?`account_id=${encodeURIComponent(accountId)}`:portfolioId?`portfolio_id=${encodeURIComponent(portfolioId)}`:""}`);
export const createSearchSavedView=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<SearchSavedView>(`/v1/tenants/${tenantId}/search-intelligence/saved-views`,{method:"POST",body:JSON.stringify(payload)});
export const deleteSearchSavedView=(tenantId:string,id:string)=>apiFetch<{ok:boolean}>(`/v1/tenants/${tenantId}/search-intelligence/saved-views/${id}/delete`,{method:"POST",body:""});
export const getPortfolioSearchNGrams=(tenantId:string,portfolioId:string,start:string,end:string,n=1,limit=100)=>apiFetch<PortfolioNGram>(`/v1/tenants/${tenantId}/portfolios/${portfolioId}/search-intelligence/ngrams?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&n=${n}&limit=${limit}`);

import type { WasteOverview, WasteQueryPage, WasteDimension, WasteGeo } from "@/lib/types";
const wasteWindowParams=(start?:string|null,end?:string|null)=>`${start?`&start=${encodeURIComponent(start)}`:""}${end?`&end=${encodeURIComponent(end)}`:""}`;
export const getWasteOverview=(tenantId:string,accountId:string,start?:string|null,end?:string|null)=>{const w=wasteWindowParams(start,end);return apiFetch<WasteOverview>(`/v1/tenants/${tenantId}/accounts/${accountId}/waste-intelligence/overview${w?`?${w.slice(1)}`:""}`)};
export const getWasteQueries=(tenantId:string,accountId:string,p:{start?:string|null;end?:string|null;family?:string|null;disposition?:string|null;page?:number;pageSize?:number}={})=>apiFetch<WasteQueryPage>(`/v1/tenants/${tenantId}/accounts/${accountId}/waste-intelligence/queries?page=${p.page||1}&page_size=${p.pageSize||50}${wasteWindowParams(p.start,p.end)}${p.family?`&family=${encodeURIComponent(p.family)}`:""}${p.disposition?`&disposition=${encodeURIComponent(p.disposition)}`:""}`);
export const getWasteDimension=(tenantId:string,accountId:string,dimension:"network"|"device"|"daypart",start?:string|null,end?:string|null)=>apiFetch<WasteDimension>(`/v1/tenants/${tenantId}/accounts/${accountId}/waste-intelligence/dimension?dimension=${dimension}${wasteWindowParams(start,end)}`);
export const getWasteGeo=(tenantId:string,accountId:string,start?:string|null,end?:string|null)=>apiFetch<WasteGeo>(`/v1/tenants/${tenantId}/accounts/${accountId}/waste-intelligence/geo?${wasteWindowParams(start,end).replace(/^&/,"")}`);

import type { MeasurementOverview,MeasurementConversionAction,MeasurementGoals,MeasurementLag } from "@/lib/types";
export const getMeasurementOverview=(tenantId:string,accountId:string)=>apiFetch<MeasurementOverview>(`/v1/tenants/${tenantId}/accounts/${accountId}/measurement-integrity/overview`);
export const getMeasurementActions=(tenantId:string,accountId:string)=>apiFetch<MeasurementConversionAction[]>(`/v1/tenants/${tenantId}/accounts/${accountId}/measurement-integrity/conversion-actions`);
export const getMeasurementGoals=(tenantId:string,accountId:string)=>apiFetch<MeasurementGoals>(`/v1/tenants/${tenantId}/accounts/${accountId}/measurement-integrity/goals`);
export const getMeasurementLag=(tenantId:string,accountId:string)=>apiFetch<MeasurementLag>(`/v1/tenants/${tenantId}/accounts/${accountId}/measurement-integrity/lag`);
export const saveMeasurementMapping=(tenantId:string,accountId:string,conversionActionResource:string,outcomeId:string|null)=>apiFetch(`/v1/tenants/${tenantId}/accounts/${accountId}/measurement-integrity/mappings`,{method:"POST",body:JSON.stringify({conversion_action_resource:conversionActionResource,outcome_id:outcomeId})});

import type { RecoveryCaseSummary,RecoveryCaseDetail } from "@/lib/types";
export const getRecoveryCases=(tenantId:string,accountId:string,p:{state?:string|null;risk?:string|null}={})=>apiFetch<RecoveryCaseSummary[]>(`/v1/tenants/${tenantId}/recovery-cases?account_id=${encodeURIComponent(accountId)}${p.state?`&state=${encodeURIComponent(p.state)}`:""}${p.risk?`&risk=${encodeURIComponent(p.risk)}`:""}&limit=300`);
export const getRecoveryCase=(tenantId:string,caseId:string)=>apiFetch<RecoveryCaseDetail>(`/v1/tenants/${tenantId}/recovery-cases/${caseId}`);

import type { RecoveryCenterOverview,RecoveryCenterCase,RecoveryCenterBreakdown,RecoveryCenterTimeline } from "@/lib/types";
function recoveryScope(accountId?:string|null,portfolioId?:string|null){return `${accountId?`&account_id=${encodeURIComponent(accountId)}`:""}${portfolioId?`&portfolio_id=${encodeURIComponent(portfolioId)}`:""}`}
export const getRecoveryCenter=(tenantId:string,accountId?:string|null,portfolioId?:string|null)=>apiFetch<RecoveryCenterOverview>(`/v1/tenants/${tenantId}/recovery-center?x=1${recoveryScope(accountId,portfolioId)}`);
export const getRecoveryCenterCases=(tenantId:string,accountId?:string|null,portfolioId?:string|null,causalStatus?:string|null)=>apiFetch<RecoveryCenterCase[]>(`/v1/tenants/${tenantId}/recovery-center/cases?limit=500${recoveryScope(accountId,portfolioId)}${causalStatus?`&causal_status=${encodeURIComponent(causalStatus)}`:""}`);
export const getRecoveryCenterBreakdown=(tenantId:string,dimension:"account"|"campaign"|"leak_type",accountId?:string|null,portfolioId?:string|null)=>apiFetch<RecoveryCenterBreakdown>(`/v1/tenants/${tenantId}/recovery-center/breakdown?dimension=${dimension}${recoveryScope(accountId,portfolioId)}`);
export const getRecoveryCenterTimeline=(tenantId:string,accountId?:string|null,portfolioId?:string|null)=>apiFetch<RecoveryCenterTimeline>(`/v1/tenants/${tenantId}/recovery-center/timeline?x=1${recoveryScope(accountId,portfolioId)}`);

import type { MonitoringOverview, MonitorAlert, MonitorAlertDetail, MonitoringPolicy } from "@/lib/types";
export const getMonitoringOverview=(tenantId:string,accountId?:string|null)=>apiFetch<MonitoringOverview>(`/v1/tenants/${tenantId}/monitoring${accountId?`?account_id=${encodeURIComponent(accountId)}`:""}`);
export const getMonitorAlerts=(tenantId:string,accountId?:string|null,state?:string|null,severity?:string|null,monitorType?:string|null)=>{const q=new URLSearchParams();if(accountId)q.set("account_id",accountId);if(state)q.set("state",state);if(severity)q.set("severity",severity);if(monitorType)q.set("monitor_type",monitorType);q.set("limit","300");return apiFetch<MonitorAlert[]>(`/v1/tenants/${tenantId}/monitoring/alerts?${q}`)};
export const getMonitorAlert=(tenantId:string,alertId:string)=>apiFetch<MonitorAlertDetail>(`/v1/tenants/${tenantId}/monitoring/alerts/${alertId}`);
export const getMonitoringPolicies=(tenantId:string,accountId?:string|null)=>apiFetch<MonitoringPolicy[]>(`/v1/tenants/${tenantId}/monitoring/policies${accountId?`?account_id=${encodeURIComponent(accountId)}`:""}`);

export const appendMonitoringAlertEvent=(tenantId:string,alertId:string,eventType:string,payload:Record<string,unknown>={})=>apiFetch<MonitorAlertDetail>(`/v1/tenants/${tenantId}/monitoring/alerts/${alertId}/events`,{method:"POST",body:JSON.stringify({event_type:eventType,payload})});
export const saveMonitoringPolicy=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<MonitoringPolicy>(`/v1/tenants/${tenantId}/monitoring/policies`,{method:"POST",body:JSON.stringify(payload)});
export const startMonitoringEvaluation=(tenantId:string,accountId:string,key:string)=>apiFetch<{job_id:string;job_type:string;status:string;idempotency_replay:boolean}>(`/v1/tenants/${tenantId}/accounts/${accountId}/monitoring/evaluate`,{method:"POST",headers:{"Idempotency-Key":key},body:"{}"});

import type { ReportTemplate,ReportGenerationSummary,ReportGenerationDetail,ReportShare,ReportSchedule,PublicReport } from "@/lib/types";
export const getReportTemplates=(tenantId:string)=>apiFetch<ReportTemplate[]>(`/v1/tenants/${tenantId}/reports/templates`);
export const getReports=(tenantId:string,scopeKind?:string|null,scopeId?:string|null)=>{const q=new URLSearchParams();if(scopeKind)q.set("scope_kind",scopeKind);if(scopeId)q.set("scope_id",scopeId);q.set("limit","200");return apiFetch<ReportGenerationSummary[]>(`/v1/tenants/${tenantId}/reports?${q}`)};
export const getReport=(tenantId:string,id:string)=>apiFetch<ReportGenerationDetail>(`/v1/tenants/${tenantId}/reports/${id}`);
export const startReportGeneration=(tenantId:string,payload:Record<string,unknown>,key:string)=>apiFetch<{job_id:string;job_type:string;status:string;idempotency_replay:boolean}>(`/v1/tenants/${tenantId}/reports/generate`,{method:"POST",headers:{"Idempotency-Key":key},body:JSON.stringify(payload)});
export const getReportShares=(tenantId:string,generationId?:string|null)=>apiFetch<ReportShare[]>(`/v1/tenants/${tenantId}/report-shares${generationId?`?generation_id=${encodeURIComponent(generationId)}`:""}`);
export const createReportShare=(tenantId:string,generationId:string,expiresDays:number)=>apiFetch<ReportShare>(`/v1/tenants/${tenantId}/reports/${generationId}/shares`,{method:"POST",body:JSON.stringify({expires_days:expiresDays})});
export const revokeReportShare=(tenantId:string,shareId:string)=>apiFetch<ReportShare>(`/v1/tenants/${tenantId}/report-shares/${shareId}/revoke`,{method:"POST",body:"{}"});
export const getReportSchedules=(tenantId:string)=>apiFetch<ReportSchedule[]>(`/v1/tenants/${tenantId}/report-schedules`);
export const saveReportSchedule=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<ReportSchedule>(`/v1/tenants/${tenantId}/report-schedules`,{method:"POST",body:JSON.stringify(payload)});

export async function publicApiFetch<T>(path:string,signal?:AbortSignal):Promise<T>{const response=await fetch(`${API}${path}`,{cache:"no-store",signal,headers:{"Content-Type":"application/json"}});if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.error?.message??`Public Recovery API request failed (${response.status})`)}return await response.json() as T}
export const getPublicReport=(token:string)=>publicApiFetch<PublicReport>(`/v1/public/report-shares/${encodeURIComponent(token)}`);

import type { OrganizationMember,OrganizationInvite,ClientWorkspace,AccountAssignment,OrganizationActivity } from "@/lib/types";
export const getOrganizationMembers=(tenantId:string)=>apiFetch<OrganizationMember[]>(`/v1/tenants/${tenantId}/organization/members`);
export const getOrganizationInvites=(tenantId:string)=>apiFetch<OrganizationInvite[]>(`/v1/tenants/${tenantId}/organization/invites`);
export const createOrganizationInvite=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<OrganizationInvite>(`/v1/tenants/${tenantId}/organization/invites`,{method:"POST",body:JSON.stringify(payload)});
export const revokeOrganizationInvite=(tenantId:string,inviteId:string)=>apiFetch<OrganizationInvite>(`/v1/tenants/${tenantId}/organization/invites/${inviteId}/revoke`,{method:"POST",body:"{}"});
export const acceptOrganizationInvite=(token:string)=>apiFetch<{tenant_id:string;tenant_name:string;role:string;account_access_mode:string;client_portal:boolean}>(`/v1/invitations/${encodeURIComponent(token)}/accept`,{method:"POST",body:"{}"});
export const updateOrganizationMember=(tenantId:string,userId:string,payload:Record<string,unknown>)=>apiFetch<OrganizationMember>(`/v1/tenants/${tenantId}/organization/members/${userId}`,{method:"POST",body:JSON.stringify(payload)});
export const recordMemberAccountAccess=(tenantId:string,userId:string,payload:Record<string,unknown>)=>apiFetch<Record<string,unknown>>(`/v1/tenants/${tenantId}/organization/members/${userId}/account-access`,{method:"POST",body:JSON.stringify(payload)});
export const getClientWorkspaces=(tenantId:string)=>apiFetch<ClientWorkspace[]>(`/v1/tenants/${tenantId}/organization/client-workspaces`);
export const getClientWorkspace=(tenantId:string,id:string)=>apiFetch<ClientWorkspace>(`/v1/tenants/${tenantId}/organization/client-workspaces/${id}`);
export const createClientWorkspace=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<ClientWorkspace>(`/v1/tenants/${tenantId}/organization/client-workspaces`,{method:"POST",body:JSON.stringify(payload)});
export const updateClientWorkspace=(tenantId:string,id:string,payload:Record<string,unknown>)=>apiFetch<ClientWorkspace>(`/v1/tenants/${tenantId}/organization/client-workspaces/${id}`,{method:"POST",body:JSON.stringify(payload)});
export const recordClientWorkspaceAccount=(tenantId:string,id:string,payload:Record<string,unknown>)=>apiFetch<ClientWorkspace>(`/v1/tenants/${tenantId}/organization/client-workspaces/${id}/accounts`,{method:"POST",body:JSON.stringify(payload)});
export const recordClientWorkspaceMember=(tenantId:string,id:string,payload:Record<string,unknown>)=>apiFetch<ClientWorkspace>(`/v1/tenants/${tenantId}/organization/client-workspaces/${id}/members`,{method:"POST",body:JSON.stringify(payload)});
export const getAccountAssignments=(tenantId:string,accountId?:string|null)=>apiFetch<AccountAssignment[]>(`/v1/tenants/${tenantId}/organization/assignments${accountId?`?account_id=${encodeURIComponent(accountId)}`:""}`);
export const recordAccountAssignment=(tenantId:string,accountId:string,payload:Record<string,unknown>)=>apiFetch<AccountAssignment>(`/v1/tenants/${tenantId}/accounts/${accountId}/assignments`,{method:"POST",body:JSON.stringify(payload)});
export const getOrganizationActivity=(tenantId:string)=>apiFetch<OrganizationActivity[]>(`/v1/tenants/${tenantId}/organization/activity?limit=300`);
import type { MemberAccountAccessDetail } from "@/lib/types";
export const getMemberAccountAccess=(tenantId:string,userId:string)=>apiFetch<MemberAccountAccessDetail[]>(`/v1/tenants/${tenantId}/organization/members/${userId}/account-access`);

import type { InternalMe,InternalTenantSummary,InternalTenantDiagnostics,InternalJob,InternalSupportCase,InternalFeatureControl,InternalIncident } from "@/lib/types";
export const getInternalMe=()=>apiFetch<InternalMe>("/v1/internal/me");
export const getInternalTenants=(q?:string|null)=>apiFetch<InternalTenantSummary[]>(`/v1/internal/tenants?limit=200${q?`&q=${encodeURIComponent(q)}`:""}`);
export const getInternalTenantDiagnostics=(tenantId:string)=>apiFetch<InternalTenantDiagnostics>(`/v1/internal/tenants/${tenantId}/diagnostics`);
export const getInternalJobs=(tenantId:string,status?:string|null)=>apiFetch<InternalJob[]>(`/v1/internal/tenants/${tenantId}/jobs?limit=300${status?`&status=${encodeURIComponent(status)}`:""}`);
export const retryInternalJob=(tenantId:string,jobId:string,reason:string)=>apiFetch<{source_job_id:string;new_job_id:string;job_type:string;status:string}>(`/v1/internal/tenants/${tenantId}/jobs/${jobId}/retry`,{method:"POST",body:JSON.stringify({reason})});
export const getInternalSupportCases=(tenantId:string)=>apiFetch<InternalSupportCase[]>(`/v1/internal/tenants/${tenantId}/support-cases?limit=300`);
export const createInternalSupportCase=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<InternalSupportCase>(`/v1/internal/tenants/${tenantId}/support-cases`,{method:"POST",body:JSON.stringify(payload)});
export const appendInternalSupportCaseEvent=(tenantId:string,caseId:string,eventType:string,payload:Record<string,unknown>)=>apiFetch<Record<string,unknown>>(`/v1/internal/tenants/${tenantId}/support-cases/${caseId}/events`,{method:"POST",body:JSON.stringify({event_type:eventType,payload})});
export const getInternalFeatureControls=(tenantId:string)=>apiFetch<InternalFeatureControl[]>(`/v1/internal/tenants/${tenantId}/feature-controls`);
export const setInternalFeatureControl=(tenantId:string,key:string,enabled:boolean,reason:string)=>apiFetch<InternalFeatureControl>(`/v1/internal/tenants/${tenantId}/feature-controls/${key}`,{method:"POST",body:JSON.stringify({enabled,reason})});
export const getInternalIncidents=()=>apiFetch<InternalIncident[]>("/v1/internal/incidents?limit=200");
export const appendInternalIncidentEvent=(payload:Record<string,unknown>)=>apiFetch<InternalIncident>("/v1/internal/incidents/events",{method:"POST",body:JSON.stringify(payload)});
import type { InternalReleaseObservation } from "@/lib/types";
export const getInternalReleaseHistory=()=>apiFetch<InternalReleaseObservation[]>("/v1/internal/releases?limit=100");

import type { PublicLaunchStatus,InternalLaunchStatus,InternalLaunchAccess,InternalLaunchQualification } from "@/lib/types";
export const getPublicLaunchStatus=(signal?:AbortSignal)=>publicApiFetch<PublicLaunchStatus>("/v1/launch/status",signal);
export const getPersonalLaunchStatus=()=>apiFetch<PublicLaunchStatus>("/v1/launch/status/me");
export const getInternalLaunchStatus=()=>apiFetch<InternalLaunchStatus>("/v1/internal/launch");
export const getInternalLaunchAccess=()=>apiFetch<InternalLaunchAccess[]>("/v1/internal/launch/access?limit=300");
export const importInternalLaunchQualification=(report:Record<string,unknown>)=>apiFetch<InternalLaunchQualification>("/v1/internal/launch/qualifications",{method:"POST",body:JSON.stringify({report})});
export const setInternalLaunchMode=(payload:Record<string,unknown>)=>apiFetch<Record<string,unknown>>("/v1/internal/launch/mode",{method:"POST",body:JSON.stringify(payload)});
export const recordInternalLaunchAccess=(payload:Record<string,unknown>)=>apiFetch<InternalLaunchAccess>("/v1/internal/launch/access",{method:"POST",body:JSON.stringify(payload)});

import type { BusinessTruthVersion } from "@/lib/types";
export const getBusinessTruth=(tenantId:string,accountId:string)=>apiFetch<BusinessTruthVersion>(`/v1/tenants/${tenantId}/accounts/${accountId}/business-truth`);
export const getBusinessTruthVersions=(tenantId:string,accountId:string,limit=50)=>apiFetch<BusinessTruthVersion[]>(`/v1/tenants/${tenantId}/accounts/${accountId}/business-truth/versions?limit=${limit}`);
export const getBusinessTruthVersion=(tenantId:string,accountId:string,snapshotId:string)=>apiFetch<BusinessTruthVersion>(`/v1/tenants/${tenantId}/accounts/${accountId}/business-truth/versions/${snapshotId}`);

import type { CustomerSupportCase,SecurityDataOverview,CustomerDataRequest,BuildInfo } from "@/lib/types";
export const getSupportCases=(tenantId:string)=>apiFetch<CustomerSupportCase[]>(`/v1/tenants/${tenantId}/support/cases?limit=200`);
export const getSupportCase=(tenantId:string,caseId:string)=>apiFetch<CustomerSupportCase>(`/v1/tenants/${tenantId}/support/cases/${caseId}`);
export const createSupportCase=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<CustomerSupportCase>(`/v1/tenants/${tenantId}/support/cases`,{method:"POST",body:JSON.stringify(payload)});
export const supportCaseEvent=(tenantId:string,caseId:string,event_type:string,comment?:string|null)=>apiFetch<CustomerSupportCase>(`/v1/tenants/${tenantId}/support/cases/${caseId}/events`,{method:"POST",body:JSON.stringify({event_type,comment:comment??null})});
export const getSecurityDataOverview=(tenantId:string)=>apiFetch<SecurityDataOverview>(`/v1/tenants/${tenantId}/security-data`);
export const createDataRequest=(tenantId:string,payload:Record<string,unknown>)=>apiFetch<CustomerDataRequest>(`/v1/tenants/${tenantId}/security-data/requests`,{method:"POST",body:JSON.stringify(payload)});
export const cancelDataRequest=(tenantId:string,id:string)=>apiFetch<CustomerDataRequest>(`/v1/tenants/${tenantId}/security-data/requests/${id}/cancel`,{method:"POST",body:"{}"});
export const getBuildInfo=()=>apiFetch<BuildInfo>(`/buildz`);
