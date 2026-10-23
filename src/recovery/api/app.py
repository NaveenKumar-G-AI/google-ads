from __future__ import annotations

from contextvars import ContextVar
import json
from datetime import date
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from recovery.db.postgres import PostgresRecoveryRepository
from recovery.build_identity import get_build_identity, validate_build_identity
from recovery.deployment import database_ready
from recovery.billing import (BillingAccessError, BillingWebhookAuthError, BillingProviderError, CheckoutAmbiguousError, BillingMutationAmbiguousError, BillingPlanCatalog, RazorpayProvider)

from .auth import AuthenticationError, Principal, SupabaseJWTVerifier, TokenVerifier
from .billing_service import BillingApplicationService, BillingRuntime
from .jobs import JobReceipt, JobType
from .models import (
    AccountResponse,
    AnalysisCreateRequest,
    BusinessTruthCreateRequest,
    BusinessTruthResponse,
    FindingResponse,
    JobDetailResponse,
    JobResponse,
    LedgerResponse,
    MeResponse,
    WorkspaceSummary,
    ProposalDecisionRequest,
    ProposalDecisionResponse,
    ProposalStateResponse,
    SemanticShadowCreateRequest,
    SyncCreateRequest,
    BillingPlanResponse, BillingStatusResponse, BillingCheckoutRequest, BillingCheckoutResponse, BillingReconcileResponse,
    BillingPlanChangePreviewRequest, BillingPlanChangePreviewResponse, BillingLifecycleOperationResponse,
    BillingInvoiceResponse, BillingInvoiceRefreshResponse, BillingEntitlementHistoryResponse,
    BillingProfileRequest, BillingProfileResponse, BillingAccountSlotResponse,
    PortfolioResponse, PortfolioDetailResponse, PortfolioCreateRequest, PortfolioAccountRequest, TaskResponse, TaskCreateRequest,
    TaskStatusRequest, NotificationResponse, SearchResultResponse, CommandCenterResponse,
    OrganizationCreateRequest, OrganizationCreateResponse, OnboardingStatusResponse,
    GoogleOAuthStartRequest, GoogleOAuthStartResponse, GoogleOAuthCallbackRequest, GoogleOAuthCallbackResponse,
    DiscoveredGoogleAdsAccountResponse, AccountSelectionRequest, GuidedBusinessTruthRequest,
    BusinessTruthVersionResponse, MeasurementProfileRequest, MeasurementProfileResponse,
    SearchOverviewResponse, SearchTermPageResponse, SearchTermDetailResponse, SearchBreakdownResponse,
    SearchNGramResponse, SearchSavedViewCreateRequest, SearchSavedViewResponse, PortfolioNGramResponse,
    WasteOverviewResponse, WasteQueryPageResponse, WasteDimensionResponse, WasteGeoResponse,
    MeasurementOverviewResponse, MeasurementConversionActionResponse, MeasurementGoalsResponse, MeasurementLagResponse,
    ConversionActionMappingRequest, ConversionActionMappingResponse,
    RecoveryCaseSummaryResponse, RecoveryCaseDetailResponse, RecoveryCaseEventRequest, RecoveryCaseEventResponse,
    RecoveryCenterOverviewResponse, RecoveryCenterCaseResponse, RecoveryCenterBreakdownResponse, RecoveryCenterTimelineResponse,
    MonitoringOverviewResponse, MonitoringAlertResponse, MonitoringAlertDetailResponse, MonitoringPolicyRequest,
    MonitoringPolicyResponse, MonitoringAlertEventRequest,
    ReportTemplateResponse, ReportGenerationRequest, ReportGenerationSummaryResponse, ReportGenerationDetailResponse,
    ReportShareCreateRequest, ReportShareResponse, ReportScheduleRequest, ReportScheduleResponse, PublicReportResponse,
    OrganizationInviteCreateRequest, OrganizationInviteResponse, OrganizationInviteAcceptResponse, OrganizationMemberResponse,
    OrganizationMemberUpdateRequest, MemberAccountAccessRequest, ClientWorkspaceCreateRequest, ClientWorkspaceUpdateRequest,
    ClientWorkspaceResponse, ClientWorkspaceAccountRequest, ClientWorkspaceMemberRequest, AccountAssignmentRequest,
    AccountAssignmentResponse, OrganizationActivityResponse, MemberAccountAccessDetailResponse,
    InternalMeResponse, InternalTenantSummaryResponse, InternalTenantDiagnosticsResponse, InternalJobResponse,
    InternalRetryJobRequest, InternalRetryJobResponse, InternalSupportCaseCreateRequest, InternalSupportCaseResponse,
    InternalSupportCaseEventRequest, InternalSupportCaseEventResponse, InternalFeatureControlResponse, InternalFeatureControlRequest,
    InternalIncidentEventRequest, InternalIncidentResponse, InternalReleaseObservationResponse,
    PublicLaunchStatusResponse, InternalLaunchStatusResponse, InternalLaunchQualificationImportRequest,
    InternalLaunchQualificationResponse, InternalLaunchModeRequest, InternalLaunchAccessRequest, InternalLaunchAccessResponse,
    CustomerSupportCaseCreateRequest, CustomerSupportEventRequest, CustomerSupportCaseResponse,
    CustomerDataRequestCreateRequest, CustomerDataRequestResponse, SecurityDataOverviewResponse,
)
from .policy import AuthorizationError, Permission
from recovery.internal_admin import PlatformAccess, PlatformAuthorizationError, PlatformOperatorRole, PlatformPermission
from .repository import ApiConflict, ApiNotFound, ApiRepository, PostgresApiRepository
from .service import ApplicationService
from .onboarding_service import (
    OnboardingApplicationService, OnboardingNotConfigured, OAuthConnectionRuntime, PostgresOnboardingStore
)
from recovery.onboarding import GoogleOAuthProvider, GoogleOAuthSettings, GoogleSecretManagerCredentialVault
from recovery.signup_abuse import TurnstileConfig, TurnstileVerifier
from .settings import ApiSettings


_request_id: ContextVar[str] = ContextVar("request_id", default="")


def _job_response(receipt: JobReceipt) -> JobResponse:
    return JobResponse(
        job_id=receipt.job_id,
        job_type=receipt.job_type.value,
        status=receipt.status.value,
        idempotency_replay=receipt.idempotency_replay,
    )


def create_app(*, repository: ApiRepository, verifier: TokenVerifier,
               allowed_origins: tuple[str, ...] = (), billing_runtime: BillingRuntime | None = None,
               readiness_probe=None, onboarding: OnboardingApplicationService | None = None,
               public_legal_config: dict[str,str] | None = None,
               public_signup_abuse_config: dict[str,Any] | None = None) -> FastAPI:
    app = FastAPI(
        title="Google Ads Recovery API",
        version="0.35.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    billing = BillingApplicationService(repository=repository, runtime=billing_runtime)
    service = ApplicationService(repository, billing=billing)

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        try:
            rid = str(UUID(incoming)) if incoming else str(uuid4())
        except ValueError:
            rid = str(uuid4())
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            _request_id.reset(token)

    def problem(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message, "request_id": _request_id.get()}},
        )

    @app.exception_handler(AuthenticationError)
    async def auth_error(_: Request, exc: AuthenticationError):
        return problem(401, "AUTHENTICATION_FAILED", str(exc))

    @app.exception_handler(AuthorizationError)
    async def authorization_error(_: Request, exc: AuthorizationError):
        return problem(403, "ACCESS_DENIED", "access denied")

    @app.exception_handler(PlatformAuthorizationError)
    async def platform_authorization_error(_: Request, exc: PlatformAuthorizationError):
        return problem(403, "PLATFORM_ACCESS_DENIED", "platform operator access denied")

    @app.exception_handler(BillingAccessError)
    async def billing_access_error(_: Request, exc: BillingAccessError):
        return problem(402, "BILLING_REQUIRED", str(exc))

    @app.exception_handler(BillingWebhookAuthError)
    async def billing_webhook_auth_error(_: Request, exc: BillingWebhookAuthError):
        return problem(401, "WEBHOOK_AUTH_FAILED", "webhook authentication failed")

    @app.exception_handler(CheckoutAmbiguousError)
    async def billing_ambiguous_error(_: Request, exc: CheckoutAmbiguousError):
        return problem(409, "BILLING_OUTCOME_UNKNOWN", str(exc))

    @app.exception_handler(BillingMutationAmbiguousError)
    async def billing_mutation_ambiguous_error(_: Request, exc: BillingMutationAmbiguousError):
        return problem(409, "BILLING_MUTATION_OUTCOME_UNKNOWN", str(exc))

    @app.exception_handler(BillingProviderError)
    async def billing_provider_error(_: Request, exc: BillingProviderError):
        return problem(502, "BILLING_PROVIDER_ERROR", str(exc))

    @app.exception_handler(OnboardingNotConfigured)
    async def onboarding_not_configured(_: Request, exc: OnboardingNotConfigured):
        return problem(503, "ONBOARDING_NOT_CONFIGURED", str(exc))

    @app.exception_handler(ApiNotFound)
    async def not_found(_: Request, exc: ApiNotFound):
        return problem(404, "NOT_FOUND", str(exc))

    @app.exception_handler(ApiConflict)
    async def conflict(_: Request, exc: ApiConflict):
        return problem(409, "CONFLICT", str(exc))

    @app.exception_handler(ValueError)
    async def bad_request(_: Request, exc: ValueError):
        return problem(400, "INVALID_REQUEST", str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Do not echo complete request bodies. Return field locations and normalized messages.
        issues = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", "invalid value")}
            for err in exc.errors()[:20]
        ]
        response = problem(422, "VALIDATION_FAILED", "request validation failed")
        body = {"error": {"code": "VALIDATION_FAILED", "message": "request validation failed",
                          "request_id": _request_id.get(), "issues": issues}}
        return JSONResponse(status_code=422, content=body)

    async def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise AuthenticationError("Bearer access token is required")
        p = verifier.verify(authorization[7:])
        service.register_seen_user(p)
        return p

    def platform_access(p: Principal, permission: PlatformPermission) -> PlatformAccess:
        role_raw=repository.platform_operator_role(user_id=p.user_id)
        if not role_raw:
            raise PlatformAuthorizationError("platform operator access required")
        access=PlatformAccess(user_id=p.user_id,role=PlatformOperatorRole(role_raw))
        access.require(permission)
        return access

    @app.get("/v1/tenants/{tenant_id}/support/cases", response_model=list[CustomerSupportCaseResponse])
    async def customer_support_cases(tenant_id: UUID, limit: int = Query(default=100,ge=1,le=300), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.SUPPORT_READ)
        include_all=access.role.value in {"analyst","admin","owner"}
        return repository.customer_support_cases(tenant_id=tenant_id,user_id=p.user_id,include_all=include_all,limit=limit)

    @app.post("/v1/tenants/{tenant_id}/support/cases", response_model=CustomerSupportCaseResponse, status_code=status.HTTP_201_CREATED)
    async def create_customer_support_case(tenant_id: UUID, body: CustomerSupportCaseCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.SUPPORT_CREATE)
        if body.account_id is not None: access.require_account(body.account_id)
        return repository.create_customer_support_case(tenant_id=tenant_id,user_id=p.user_id,account_id=body.account_id,category=body.category,subject=body.subject,body=body.body)

    @app.get("/v1/tenants/{tenant_id}/support/cases/{case_id}", response_model=CustomerSupportCaseResponse)
    async def customer_support_case(tenant_id: UUID, case_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.SUPPORT_READ)
        include_all=access.role.value in {"analyst","admin","owner"}
        return repository.customer_support_case(tenant_id=tenant_id,user_id=p.user_id,case_id=case_id,include_all=include_all)

    @app.post("/v1/tenants/{tenant_id}/support/cases/{case_id}/events", response_model=CustomerSupportCaseResponse)
    async def customer_support_case_event(tenant_id: UUID, case_id: UUID, body: CustomerSupportEventRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.SUPPORT_CREATE)
        include_all=access.role.value in {"analyst","admin","owner"}
        return repository.customer_support_case_event(tenant_id=tenant_id,user_id=p.user_id,case_id=case_id,include_all=include_all,event_type=body.event_type,comment=body.comment)

    @app.get("/v1/tenants/{tenant_id}/security-data", response_model=SecurityDataOverviewResponse)
    async def security_data_overview(tenant_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p,tenant_id=tenant_id,permission=Permission.SECURITY_DATA_READ)
        return repository.security_data_overview(tenant_id=tenant_id,user_id=p.user_id)

    @app.post("/v1/tenants/{tenant_id}/security-data/requests", response_model=CustomerDataRequestResponse, status_code=status.HTTP_201_CREATED)
    async def create_customer_data_request(tenant_id: UUID, body: CustomerDataRequestCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.DATA_REQUEST_MANAGE)
        if body.request_type=="organization_deletion" and access.role.value!="owner":
            raise AuthorizationError("only an organization owner can request organization deletion")
        if body.account_id is not None: access.require_account(body.account_id)
        return repository.create_customer_data_request(tenant_id=tenant_id,user_id=p.user_id,account_id=body.account_id,request_type=body.request_type,reason=body.reason)

    @app.post("/v1/tenants/{tenant_id}/security-data/requests/{request_id}/cancel", response_model=CustomerDataRequestResponse)
    async def cancel_customer_data_request(tenant_id: UUID, request_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p,tenant_id=tenant_id,permission=Permission.DATA_REQUEST_MANAGE)
        return repository.cancel_customer_data_request(tenant_id=tenant_id,user_id=p.user_id,request_id=request_id)

    @app.get("/v1/tenants/{tenant_id}/security-data/configuration-export")
    async def security_configuration_export(tenant_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p,tenant_id=tenant_id,permission=Permission.DATA_REQUEST_MANAGE)
        payload=repository.security_configuration_export(tenant_id=tenant_id,user_id=p.user_id)
        raw=json.dumps(payload,ensure_ascii=False,indent=2,default=str).encode("utf-8")
        return Response(content=raw,media_type="application/json; charset=utf-8",headers={"Content-Disposition":f'attachment; filename="recovery-os-configuration-{str(tenant_id)[:8]}.json"',"Cache-Control":"private, no-store"})

    @app.get("/v1/internal/me", response_model=InternalMeResponse)
    async def internal_me(p: Principal = Depends(principal)):
        access=platform_access(p,PlatformPermission.PLATFORM_READ)
        return {"user_id":p.user_id,"email":p.email,"operator_role":access.role.value}

    @app.get("/v1/internal/tenants", response_model=list[InternalTenantSummaryResponse])
    async def internal_tenants(q: str | None = Query(default=None,max_length=160), limit: int = Query(default=100,ge=1,le=500), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.PLATFORM_READ)
        return repository.list_internal_tenants(user_id=p.user_id,query=q,limit=limit)

    @app.get("/v1/internal/tenants/{tenant_id}/diagnostics", response_model=InternalTenantDiagnosticsResponse)
    async def internal_tenant_diagnostics(tenant_id: UUID, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.TENANT_DIAGNOSTICS)
        return repository.internal_tenant_diagnostics(user_id=p.user_id,tenant_id=tenant_id)

    @app.get("/v1/internal/tenants/{tenant_id}/jobs", response_model=list[InternalJobResponse])
    async def internal_jobs(tenant_id: UUID, status_filter: str | None = Query(default=None,alias="status"), limit: int = Query(default=200,ge=1,le=500), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.TENANT_DIAGNOSTICS)
        return repository.internal_jobs(user_id=p.user_id,tenant_id=tenant_id,status=status_filter,limit=limit)

    @app.post("/v1/internal/tenants/{tenant_id}/jobs/{job_id}/retry", response_model=InternalRetryJobResponse, status_code=status.HTTP_201_CREATED)
    async def internal_retry_job(tenant_id: UUID, job_id: UUID, body: InternalRetryJobRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.SAFE_REMEDIATION)
        return repository.internal_retry_job(user_id=p.user_id,tenant_id=tenant_id,job_id=job_id,reason=body.reason)

    @app.get("/v1/internal/tenants/{tenant_id}/support-cases", response_model=list[InternalSupportCaseResponse])
    async def internal_support_cases(tenant_id: UUID, limit: int = Query(default=200,ge=1,le=500), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.SUPPORT_CASE_READ)
        return repository.internal_support_cases(user_id=p.user_id,tenant_id=tenant_id,limit=limit)

    @app.post("/v1/internal/tenants/{tenant_id}/support-cases", response_model=InternalSupportCaseResponse, status_code=status.HTTP_201_CREATED)
    async def internal_create_support_case(tenant_id: UUID, body: InternalSupportCaseCreateRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.SUPPORT_CASE_WRITE)
        return repository.create_internal_support_case(user_id=p.user_id,tenant_id=tenant_id,title=body.title,category=body.category,severity=body.severity,note=body.note)

    @app.post("/v1/internal/tenants/{tenant_id}/support-cases/{case_id}/events", response_model=InternalSupportCaseEventResponse)
    async def internal_support_case_event(tenant_id: UUID, case_id: UUID, body: InternalSupportCaseEventRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.SUPPORT_CASE_WRITE)
        return repository.internal_support_case_event(user_id=p.user_id,tenant_id=tenant_id,case_id=case_id,event_type=body.event_type,payload=body.payload)

    @app.get("/v1/internal/tenants/{tenant_id}/feature-controls", response_model=list[InternalFeatureControlResponse])
    async def internal_feature_controls(tenant_id: UUID, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.TENANT_DIAGNOSTICS)
        return repository.internal_feature_controls(user_id=p.user_id,tenant_id=tenant_id)

    @app.post("/v1/internal/tenants/{tenant_id}/feature-controls/{feature_key}", response_model=InternalFeatureControlResponse)
    async def internal_set_feature_control(tenant_id: UUID, feature_key: str, body: InternalFeatureControlRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.FEATURE_CONTROL)
        return repository.set_internal_feature_control(user_id=p.user_id,tenant_id=tenant_id,feature_key=feature_key,enabled=body.enabled,reason=body.reason)

    @app.get("/v1/internal/releases", response_model=list[InternalReleaseObservationResponse])
    async def internal_release_history(limit: int = Query(default=100,ge=1,le=200), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.PLATFORM_READ)
        return repository.internal_release_history(user_id=p.user_id,limit=limit)

    @app.get("/v1/internal/launch", response_model=InternalLaunchStatusResponse)
    async def internal_launch_status(p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.PLATFORM_READ)
        return repository.internal_launch_status(user_id=p.user_id)

    @app.get("/v1/internal/launch/access", response_model=list[InternalLaunchAccessResponse])
    async def internal_launch_access(limit: int = Query(default=200,ge=1,le=500), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.PLATFORM_READ)
        return repository.list_internal_launch_access(user_id=p.user_id,limit=limit)

    @app.post("/v1/internal/launch/qualifications", response_model=InternalLaunchQualificationResponse, status_code=status.HTTP_201_CREATED)
    async def internal_launch_qualification(body: InternalLaunchQualificationImportRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.LAUNCH_CONTROL)
        return repository.import_launch_qualification(user_id=p.user_id,report=body.report)

    @app.post("/v1/internal/launch/mode", response_model=dict[str,Any], status_code=status.HTTP_201_CREATED)
    async def internal_launch_mode(body: InternalLaunchModeRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.LAUNCH_CONTROL)
        return repository.set_internal_launch_mode(user_id=p.user_id,launch_mode=body.launch_mode,release_id=body.release_id,reason=body.reason)

    @app.post("/v1/internal/launch/access", response_model=InternalLaunchAccessResponse, status_code=status.HTTP_201_CREATED)
    async def internal_launch_access_event(body: InternalLaunchAccessRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.LAUNCH_CONTROL)
        return repository.record_internal_launch_access(user_id=p.user_id,email=body.email,event_type=body.event_type,expires_at=body.expires_at,reason=body.reason)

    @app.get("/v1/internal/incidents", response_model=list[InternalIncidentResponse])
    async def internal_incidents(limit: int = Query(default=100,ge=1,le=500), p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.INCIDENT_READ)
        return repository.internal_platform_incidents(user_id=p.user_id,limit=limit)

    @app.post("/v1/internal/incidents/events", response_model=InternalIncidentResponse, status_code=status.HTTP_201_CREATED)
    async def internal_incident_event(body: InternalIncidentEventRequest, p: Principal = Depends(principal)):
        platform_access(p,PlatformPermission.INCIDENT_WRITE)
        return repository.create_internal_platform_incident_event(user_id=p.user_id,incident_id=body.incident_id,event_type=body.event_type,severity=body.severity,title=body.title,payload=body.payload)

    @app.post("/v1/billing/webhooks/razorpay")
    async def razorpay_webhook(
        request: Request,
        x_razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
        x_razorpay_event_id: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
    ) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > 1_000_000:
            raise ValueError("webhook body exceeds 1 MB")
        return billing.handle_webhook(
            raw_body=raw, signature=x_razorpay_signature or "",
            provider_event_id_header=x_razorpay_event_id,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/buildz")
    async def buildz() -> dict[str, str]:
        import os
        return {
            "service": "recovery-api",
            "version": "0.35.0",
            "release_id": os.environ.get("RECOVERY_RELEASE_ID", "unversioned").strip() or "unversioned",
            **get_build_identity(),
        }

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, Any]:
        if readiness_probe is None:
            return {"status": "ready", "database": "not-configured"}
        try:
            detail = readiness_probe()
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not-ready"}
        return {"status": "ready", **detail}

    def _launch_payload(base: dict[str,Any]) -> dict[str,Any]:
        legal=public_legal_config or {}
        result={**base,
                "terms_url":legal.get("terms_url") or None,
                "terms_version":legal.get("terms_version") or None,
                "privacy_url":legal.get("privacy_url") or None,
                "privacy_version":legal.get("privacy_version") or None}
        result["legal_acceptance_ready"]=all(result.get(k) for k in ("terms_url","terms_version","privacy_url","privacy_version"))
        abuse=public_signup_abuse_config or {}
        result["signup_abuse_ready"]=bool(abuse.get("ready"))
        result["turnstile_site_key"]=abuse.get("site_key") or None
        result["public_workspace_max_per_user_24h"]=abuse.get("max_per_user_24h")
        if public_signup_abuse_config is not None and result.get("launch_mode")=="public" and not result["signup_abuse_ready"]:
            result["workspace_creation_open"]=False
        return result

    @app.get("/v1/launch/status", response_model=PublicLaunchStatusResponse)
    async def public_launch_status():
        return _launch_payload(repository.public_launch_status())

    @app.get("/v1/launch/status/me", response_model=PublicLaunchStatusResponse)
    async def personal_launch_status(p: Principal = Depends(principal)):
        return _launch_payload(repository.public_launch_status(user_id=p.user_id,email=p.email))

    @app.get("/v1/me", response_model=MeResponse)
    async def me(p: Principal = Depends(principal)) -> MeResponse:
        return MeResponse(
            user_id=p.user_id,
            email=p.email,
            memberships=repository.list_memberships(user_id=p.user_id),
        )

    @app.post("/v1/onboarding/organizations", response_model=OrganizationCreateResponse, status_code=status.HTTP_201_CREATED)
    async def create_organization(
        body: OrganizationCreateRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        tenant_id, replay = onboarding.create_organization(
            principal=p, display_name=body.display_name, slug=body.slug,
            idempotency_key=idempotency_key or "",
            legal_acceptance_confirmed=body.legal_acceptance_confirmed,
            accepted_terms_version=body.accepted_terms_version,
            accepted_privacy_version=body.accepted_privacy_version,
            turnstile_token=body.turnstile_token,
        )
        return OrganizationCreateResponse(tenant_id=tenant_id, idempotency_replay=replay)

    @app.get("/v1/tenants/{tenant_id}/onboarding", response_model=OnboardingStatusResponse)
    async def onboarding_status(tenant_id: UUID, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.TENANT_READ)
        return onboarding.status(access=access)

    @app.post("/v1/tenants/{tenant_id}/onboarding/google-ads/oauth/start", response_model=GoogleOAuthStartResponse)
    async def google_ads_oauth_start(tenant_id: UUID, body: GoogleOAuthStartRequest, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ONBOARDING_MANAGE)
        return GoogleOAuthStartResponse(authorization_url=onboarding.begin_google_oauth(
            access=access, login_hint=body.login_hint, return_path=body.return_path
        ))

    @app.post("/v1/onboarding/google-ads/oauth/callback", response_model=GoogleOAuthCallbackResponse)
    async def google_ads_oauth_callback(body: GoogleOAuthCallbackRequest, request: Request, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        tenant_id, connection_id, receipt, return_path = onboarding.complete_google_oauth(
            principal=p, code=body.code, state=body.state, endpoint=request.url.path
        )
        return GoogleOAuthCallbackResponse(
            tenant_id=tenant_id, connection_id=connection_id,
            discovery_job=_job_response(receipt), return_path=return_path,
        )

    @app.get("/v1/tenants/{tenant_id}/onboarding/google-ads/accounts", response_model=list[DiscoveredGoogleAdsAccountResponse])
    async def google_ads_discovered_accounts(tenant_id: UUID, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ONBOARDING_MANAGE)
        return onboarding.discovered_accounts(access=access)

    @app.post("/v1/tenants/{tenant_id}/onboarding/google-ads/accounts/select", response_model=list[AccountResponse])
    async def google_ads_select_accounts(tenant_id: UUID, body: AccountSelectionRequest, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ONBOARDING_MANAGE)
        return onboarding.select_accounts(access=access, customer_ids=tuple(body.customer_ids))

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/business-truth", response_model=BusinessTruthVersionResponse)
    async def current_business_truth(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BUSINESS_TRUTH_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id,account_id=account_id,user_id=p.user_id)
        return repository.business_truth_version(tenant_id=tenant_id,account_id=account_id,snapshot_id=None)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/business-truth/versions", response_model=list[BusinessTruthVersionResponse])
    async def business_truth_versions(tenant_id: UUID, account_id: UUID, limit: int = Query(default=50,ge=1,le=200), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BUSINESS_TRUTH_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id,account_id=account_id,user_id=p.user_id)
        return repository.business_truth_versions(tenant_id=tenant_id,account_id=account_id,limit=limit)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/business-truth/versions/{snapshot_id}", response_model=BusinessTruthVersionResponse)
    async def business_truth_version(tenant_id: UUID, account_id: UUID, snapshot_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BUSINESS_TRUTH_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id,account_id=account_id,user_id=p.user_id)
        return repository.business_truth_version(tenant_id=tenant_id,account_id=account_id,snapshot_id=snapshot_id)

    @app.post("/v1/tenants/{tenant_id}/accounts/{account_id}/business-truth/guided", response_model=BusinessTruthResponse, status_code=status.HTTP_201_CREATED)
    async def guided_business_truth(
        tenant_id: UUID, account_id: UUID, body: GuidedBusinessTruthRequest, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.BUSINESS_TRUTH_WRITE)
        snapshot_id, fingerprint, version, replay = onboarding.guided_business_truth(
            access=access, account_id=account_id, data=body.model_dump(),
            idempotency_key=idempotency_key or "", endpoint=request.url.path,
        )
        return BusinessTruthResponse(
            truth_snapshot_id=snapshot_id, truth_fingerprint=fingerprint,
            version=version, idempotency_replay=replay,
        )

    @app.post("/v1/tenants/{tenant_id}/accounts/{account_id}/onboarding/measurement", response_model=MeasurementProfileResponse)
    async def onboarding_measurement(tenant_id: UUID, account_id: UUID, body: MeasurementProfileRequest, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ONBOARDING_MANAGE)
        return onboarding.set_measurement(access=access, account_id=account_id, conversion_lag_days=body.conversion_lag_days)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/onboarding/measurement", response_model=MeasurementProfileResponse | None)
    async def onboarding_measurement_get(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.TENANT_READ)
        return onboarding.measurement(access=access, account_id=account_id)

    @app.post("/v1/tenants/{tenant_id}/onboarding/complete", status_code=status.HTTP_204_NO_CONTENT)
    async def onboarding_complete(tenant_id: UUID, p: Principal = Depends(principal)):
        if onboarding is None:
            raise OnboardingNotConfigured("onboarding runtime is not configured")
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ONBOARDING_MANAGE)
        onboarding.complete(access=access)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/v1/billing/plans", response_model=list[BillingPlanResponse])
    async def billing_plans(p: Principal = Depends(principal)):
        return billing.public_plans()

    @app.get("/v1/tenants/{tenant_id}/billing", response_model=BillingStatusResponse)
    async def billing_status(tenant_id: UUID, p: Principal = Depends(principal)):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.BILLING_READ)
        return billing.status(access=access)

    @app.post(
        "/v1/tenants/{tenant_id}/billing/checkout",
        response_model=BillingCheckoutResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def billing_checkout(
        tenant_id: UUID, body: BillingCheckoutRequest, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.BILLING_MANAGE)
        return billing.start_checkout(
            access=access, plan_key=body.plan_key, idempotency_key=idempotency_key or "",
            endpoint=request.url.path,
        )

    @app.post(
        "/v1/tenants/{tenant_id}/billing/reconcile",
        response_model=BillingReconcileResponse,
    )
    async def billing_reconcile(tenant_id: UUID, p: Principal = Depends(principal)):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.BILLING_MANAGE)
        return billing.reconcile(access=access)

    @app.post("/v1/tenants/{tenant_id}/billing/plan-change/preview", response_model=BillingPlanChangePreviewResponse)
    async def billing_plan_change_preview(tenant_id: UUID, body: BillingPlanChangePreviewRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.plan_change_preview(access=access,target_plan_key=body.target_plan_key)

    @app.post("/v1/tenants/{tenant_id}/billing/plan-change", response_model=BillingLifecycleOperationResponse)
    async def billing_plan_change(
        tenant_id: UUID, body: BillingPlanChangePreviewRequest, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.schedule_plan_change(access=access,target_plan_key=body.target_plan_key,idempotency_key=idempotency_key or "",endpoint=request.url.path)

    @app.post("/v1/tenants/{tenant_id}/billing/plan-change/cancel", response_model=BillingLifecycleOperationResponse)
    async def billing_plan_change_cancel(
        tenant_id: UUID, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.cancel_scheduled_plan_change(access=access,idempotency_key=idempotency_key or "",endpoint=request.url.path)

    @app.post("/v1/tenants/{tenant_id}/billing/cancel", response_model=BillingLifecycleOperationResponse)
    async def billing_cancel_cycle_end(
        tenant_id: UUID, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.cancel_at_cycle_end(access=access,idempotency_key=idempotency_key or "",endpoint=request.url.path)

    @app.get("/v1/tenants/{tenant_id}/billing/invoices", response_model=list[BillingInvoiceResponse])
    async def billing_invoices(tenant_id: UUID, limit: int = Query(default=100,ge=1,le=500), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_READ)
        return billing.invoices(access=access,limit=limit)

    @app.post("/v1/tenants/{tenant_id}/billing/invoices/refresh", response_model=BillingInvoiceRefreshResponse)
    async def billing_invoice_refresh(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.refresh_invoices(access=access)

    @app.get("/v1/tenants/{tenant_id}/billing/history", response_model=list[BillingEntitlementHistoryResponse])
    async def billing_history(tenant_id: UUID, limit: int = Query(default=100,ge=1,le=500), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_READ)
        return billing.entitlement_history(access=access,limit=limit)

    @app.get("/v1/tenants/{tenant_id}/billing/profile", response_model=BillingProfileResponse | None)
    async def billing_profile(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_READ)
        return billing.profile(access=access)

    @app.post("/v1/tenants/{tenant_id}/billing/profile", response_model=BillingProfileResponse)
    async def billing_profile_save(tenant_id: UUID, body: BillingProfileRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        return billing.save_profile(access=access,legal_name=body.legal_name,billing_email=body.billing_email,tax_country=body.tax_country,tax_region=body.tax_region,gstin=body.gstin)

    @app.get("/v1/tenants/{tenant_id}/billing/account-slots", response_model=list[BillingAccountSlotResponse])
    async def billing_account_slots(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_READ)
        return billing.account_slots(access=access)

    @app.post("/v1/tenants/{tenant_id}/billing/account-slots/{account_id}/release", status_code=status.HTTP_204_NO_CONTENT)
    async def billing_account_slot_release(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.BILLING_MANAGE)
        billing.release_account_slot(access=access,account_id=account_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/v1/tenants/{tenant_id}/deployment-probe",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def deployment_probe(
        tenant_id: UUID, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.DEPLOYMENT_PROBE)
        return _job_response(service.enqueue_deployment_probe(
            access=access, idempotency_key=idempotency_key or "", endpoint=request.url.path,
        ))


    @app.post(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/pilot-google-ads-read-probe",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def pilot_google_ads_read_probe(
        tenant_id: UUID, account_id: UUID, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.PILOT_PROBE)
        return _job_response(service.enqueue_pilot_google_ads_read_probe(
            access=access,account_id=account_id,idempotency_key=idempotency_key or "",endpoint=request.url.path,
        ))


    @app.get("/v1/tenants/{tenant_id}/organization/members", response_model=list[OrganizationMemberResponse])
    async def organization_members(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.list_organization_members(tenant_id=tenant_id)

    @app.post("/v1/tenants/{tenant_id}/organization/invites", response_model=OrganizationInviteResponse, status_code=status.HTTP_201_CREATED)
    async def organization_invite_create(tenant_id: UUID, body: OrganizationInviteCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_MANAGE)
        access.require_unrestricted_scope()
        return repository.create_organization_invite(tenant_id=tenant_id,actor_user_id=p.user_id,actor_role=access.role,email=body.email,role=body.role,account_access_mode=body.account_access_mode,client_portal=body.client_portal,expires_days=body.expires_days)

    @app.get("/v1/tenants/{tenant_id}/organization/invites", response_model=list[OrganizationInviteResponse])
    async def organization_invites(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.list_organization_invites(tenant_id=tenant_id)

    @app.post("/v1/tenants/{tenant_id}/organization/invites/{invite_id}/revoke", response_model=OrganizationInviteResponse)
    async def organization_invite_revoke(tenant_id: UUID, invite_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_MANAGE)
        access.require_unrestricted_scope()
        return repository.revoke_organization_invite(tenant_id=tenant_id,invite_id=invite_id,actor_user_id=p.user_id,actor_role=access.role)

    @app.post("/v1/invitations/{token}/accept", response_model=OrganizationInviteAcceptResponse)
    async def organization_invite_accept(token: str, p: Principal = Depends(principal)):
        return repository.accept_organization_invite(token=token,principal_user_id=p.user_id,principal_email=p.email)

    @app.post("/v1/tenants/{tenant_id}/organization/members/{user_id}", response_model=OrganizationMemberResponse)
    async def organization_member_update(tenant_id: UUID, user_id: UUID, body: OrganizationMemberUpdateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_MANAGE)
        access.require_unrestricted_scope()
        return repository.update_organization_member(tenant_id=tenant_id,actor_user_id=p.user_id,actor_role=access.role,user_id=user_id,role=body.role,status=body.status,account_access_mode=body.account_access_mode,client_portal=body.client_portal)

    @app.get("/v1/tenants/{tenant_id}/organization/members/{user_id}/account-access", response_model=list[MemberAccountAccessDetailResponse])
    async def organization_member_account_access_matrix(tenant_id: UUID, user_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.member_account_access_matrix(tenant_id=tenant_id,user_id=user_id)

    @app.post("/v1/tenants/{tenant_id}/organization/members/{user_id}/account-access")
    async def organization_member_account_access(tenant_id: UUID, user_id: UUID, body: MemberAccountAccessRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ACCOUNT_ACCESS_MANAGE)
        access.require_unrestricted_scope()
        return repository.record_member_account_access(tenant_id=tenant_id,actor_user_id=p.user_id,user_id=user_id,account_id=body.account_id,action=body.action,reason=body.reason)

    @app.get("/v1/tenants/{tenant_id}/organization/client-workspaces", response_model=list[ClientWorkspaceResponse])
    async def client_workspaces(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.list_client_workspaces(tenant_id=tenant_id)

    @app.get("/v1/tenants/{tenant_id}/organization/client-workspaces/{workspace_id}", response_model=ClientWorkspaceResponse)
    async def client_workspace_detail(tenant_id: UUID, workspace_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)

    @app.post("/v1/tenants/{tenant_id}/organization/client-workspaces", response_model=ClientWorkspaceResponse, status_code=status.HTTP_201_CREATED)
    async def client_workspace_create(tenant_id: UUID, body: ClientWorkspaceCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.CLIENT_WORKSPACE_MANAGE)
        access.require_unrestricted_scope()
        return repository.record_client_workspace(tenant_id=tenant_id,actor_user_id=p.user_id,workspace_id=None,action="created",name=body.name,external_reference=body.external_reference,notes=body.notes)

    @app.post("/v1/tenants/{tenant_id}/organization/client-workspaces/{workspace_id}", response_model=ClientWorkspaceResponse)
    async def client_workspace_update(tenant_id: UUID, workspace_id: UUID, body: ClientWorkspaceUpdateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.CLIENT_WORKSPACE_MANAGE)
        access.require_unrestricted_scope()
        if body.workspace_id!=workspace_id: raise ValueError("workspace id mismatch")
        return repository.record_client_workspace(tenant_id=tenant_id,actor_user_id=p.user_id,workspace_id=workspace_id,action=body.action,name=body.name,external_reference=body.external_reference,notes=body.notes)

    @app.post("/v1/tenants/{tenant_id}/organization/client-workspaces/{workspace_id}/accounts", response_model=ClientWorkspaceResponse)
    async def client_workspace_account(tenant_id: UUID, workspace_id: UUID, body: ClientWorkspaceAccountRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.CLIENT_WORKSPACE_MANAGE)
        access.require_unrestricted_scope()
        return repository.record_client_workspace_account(tenant_id=tenant_id,actor_user_id=p.user_id,workspace_id=workspace_id,account_id=body.account_id,action=body.action)

    @app.post("/v1/tenants/{tenant_id}/organization/client-workspaces/{workspace_id}/members", response_model=ClientWorkspaceResponse)
    async def client_workspace_member(tenant_id: UUID, workspace_id: UUID, body: ClientWorkspaceMemberRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.CLIENT_WORKSPACE_MANAGE)
        access.require_unrestricted_scope()
        return repository.record_client_workspace_member(tenant_id=tenant_id,actor_user_id=p.user_id,workspace_id=workspace_id,user_id=body.user_id,action=body.action)

    @app.get("/v1/tenants/{tenant_id}/organization/assignments", response_model=list[AccountAssignmentResponse])
    async def organization_assignments(tenant_id: UUID, account_id: UUID | None = Query(default=None), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_READ)
        access.require_unrestricted_scope()
        return repository.account_assignments(tenant_id=tenant_id,account_id=account_id)

    @app.post("/v1/tenants/{tenant_id}/accounts/{account_id}/assignments", response_model=AccountAssignmentResponse)
    async def organization_assignment_event(tenant_id: UUID, account_id: UUID, body: AccountAssignmentRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_TEAM_MANAGE)
        access.require_account(account_id)
        return repository.record_account_assignment(tenant_id=tenant_id,actor_user_id=p.user_id,account_id=account_id,user_id=body.user_id,responsibility=body.responsibility,action=body.action,note=body.note)

    @app.get("/v1/tenants/{tenant_id}/organization/activity", response_model=list[OrganizationActivityResponse])
    async def organization_activity(tenant_id: UUID, limit: int = Query(default=200,ge=1,le=500), p: Principal = Depends(principal)):
        access=service.access(principal=p,tenant_id=tenant_id,permission=Permission.ORGANIZATION_ACTIVITY_READ)
        access.require_unrestricted_scope()
        return repository.organization_activity(tenant_id=tenant_id,limit=limit)

    @app.get("/v1/tenants/{tenant_id}/command-center", response_model=CommandCenterResponse)
    async def command_center(tenant_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.TENANT_READ)
        return repository.command_center(tenant_id=tenant_id, user_id=p.user_id)

    @app.get("/v1/tenants/{tenant_id}/portfolios", response_model=list[PortfolioResponse])
    async def portfolios(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.PORTFOLIO_READ)
        access.require_unrestricted_scope()
        return repository.list_portfolios(tenant_id=tenant_id)

    @app.get("/v1/tenants/{tenant_id}/portfolios/{portfolio_id}", response_model=PortfolioDetailResponse)
    async def portfolio_detail(tenant_id: UUID, portfolio_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.PORTFOLIO_READ)
        access.require_unrestricted_scope()
        return repository.portfolio_detail(tenant_id=tenant_id, portfolio_id=portfolio_id)

    @app.post("/v1/tenants/{tenant_id}/portfolios", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
    async def create_portfolio(tenant_id: UUID, body: PortfolioCreateRequest, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.PORTFOLIO_MANAGE)
        return repository.create_portfolio(tenant_id=tenant_id, user_id=p.user_id, name=body.name, description=body.description)

    @app.post("/v1/tenants/{tenant_id}/portfolios/{portfolio_id}/accounts")
    async def add_portfolio_account(tenant_id: UUID, portfolio_id: UUID, body: PortfolioAccountRequest, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.PORTFOLIO_MANAGE)
        repository.add_portfolio_account(tenant_id=tenant_id, user_id=p.user_id, portfolio_id=portfolio_id, account_id=body.account_id)
        return {"ok": True}

    @app.post("/v1/tenants/{tenant_id}/portfolios/{portfolio_id}/accounts/{account_id}/remove")
    async def remove_portfolio_account(tenant_id: UUID, portfolio_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.PORTFOLIO_MANAGE)
        repository.remove_portfolio_account(tenant_id=tenant_id, portfolio_id=portfolio_id, account_id=account_id)
        return {"ok": True}

    @app.get("/v1/tenants/{tenant_id}/tasks", response_model=list[TaskResponse])
    async def tasks(
        tenant_id: UUID, scope: str = Query(default="all", pattern="^(all|mine)$"),
        account_id: UUID | None = Query(default=None), status_filter: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=100, ge=1, le=500), p: Principal = Depends(principal),
    ):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.TASK_READ)
        return repository.list_tasks(tenant_id=tenant_id, user_id=p.user_id, scope=scope, account_id=account_id, status=status_filter, limit=limit)

    @app.post("/v1/tenants/{tenant_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
    async def create_task(tenant_id: UUID, body: TaskCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.TASK_MANAGE)
        if body.account_id is not None: access.require_account(body.account_id)
        if body.portfolio_id is not None: access.require_unrestricted_scope()
        return repository.create_task(tenant_id=tenant_id, user_id=p.user_id, title=body.title, description=body.description, account_id=body.account_id, portfolio_id=body.portfolio_id, priority=body.priority, assigned_to=body.assigned_to, due_at=body.due_at)

    @app.post("/v1/tenants/{tenant_id}/tasks/{task_id}/status", response_model=TaskResponse)
    async def update_task_status(tenant_id: UUID, task_id: UUID, body: TaskStatusRequest, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.TASK_MANAGE)
        return repository.update_task_status(tenant_id=tenant_id, task_id=task_id, status=body.status)

    @app.get("/v1/tenants/{tenant_id}/notifications", response_model=list[NotificationResponse])
    async def notifications(tenant_id: UUID, unread_only: bool = Query(default=False), limit: int = Query(default=100, ge=1, le=500), p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.NOTIFICATION_READ)
        return repository.list_notifications(tenant_id=tenant_id, user_id=p.user_id, unread_only=unread_only, limit=limit)

    @app.post("/v1/tenants/{tenant_id}/notifications/{notification_id}/read", response_model=NotificationResponse)
    async def read_notification(tenant_id: UUID, notification_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.NOTIFICATION_READ)
        return repository.mark_notification_read(tenant_id=tenant_id, user_id=p.user_id, notification_id=notification_id)

    @app.get("/v1/tenants/{tenant_id}/search", response_model=list[SearchResultResponse])
    async def global_search(tenant_id: UUID, q: str = Query(min_length=2, max_length=200), limit: int = Query(default=20, ge=1, le=50), p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.GLOBAL_SEARCH)
        return repository.global_search(tenant_id=tenant_id, user_id=p.user_id, query=q, limit=limit)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/search-intelligence/overview", response_model=SearchOverviewResponse)
    async def search_intelligence_overview(
        tenant_id: UUID, account_id: UUID,
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.search_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=start, end=end)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/search-intelligence/terms", response_model=SearchTermPageResponse)
    async def search_intelligence_terms(
        tenant_id: UUID, account_id: UUID,
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        query: str | None = Query(default=None, max_length=500),
        network: str | None = Query(default=None, max_length=80),
        fit: str | None = Query(default=None, max_length=80),
        sort: str = Query(default="cost", pattern="^(cost|clicks|impressions|conversions|query)$"),
        direction: str = Query(default="desc", pattern="^(asc|desc)$"),
        page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=50, ge=1, le=200),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.search_intelligence_terms(tenant_id=tenant_id, account_id=account_id, start=start, end=end,
            query=query, network=network, fit=fit, sort=sort, direction=direction, page=page, page_size=page_size)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/search-intelligence/term", response_model=SearchTermDetailResponse)
    async def search_intelligence_term_detail(
        tenant_id: UUID, account_id: UUID, query: str = Query(min_length=1, max_length=500),
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.search_intelligence_term_detail(tenant_id=tenant_id, account_id=account_id,
            normalized_query=query, start=start, end=end)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/search-intelligence/breakdown", response_model=SearchBreakdownResponse)
    async def search_intelligence_breakdown(
        tenant_id: UUID, account_id: UUID,
        dimension: str = Query(pattern="^(network|match_source|intent|fit)$"),
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.search_intelligence_breakdown(tenant_id=tenant_id, account_id=account_id,
            start=start, end=end, dimension=dimension)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/search-intelligence/ngrams", response_model=SearchNGramResponse)
    async def search_intelligence_ngrams(
        tenant_id: UUID, account_id: UUID,
        n: int = Query(default=1, ge=1, le=6), sort: str = Query(default="cost", pattern="^(cost|clicks|impressions|conversions)$"),
        limit: int = Query(default=100, ge=1, le=500), without_conversions: bool = Query(default=False),
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.search_intelligence_ngrams(tenant_id=tenant_id, account_id=account_id,
            start=start, end=end, n=n, sort=sort, limit=limit, without_conversions=without_conversions)

    @app.get("/v1/tenants/{tenant_id}/search-intelligence/saved-views", response_model=list[SearchSavedViewResponse])
    async def search_saved_views(
        tenant_id: UUID, account_id: UUID | None = Query(default=None), portfolio_id: UUID | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        if account_id is not None: access.require_account(account_id)
        if portfolio_id is not None: access.require_unrestricted_scope()
        return repository.list_search_saved_views(tenant_id=tenant_id, user_id=p.user_id, account_id=account_id, portfolio_id=portfolio_id)

    @app.post("/v1/tenants/{tenant_id}/search-intelligence/saved-views", response_model=SearchSavedViewResponse, status_code=status.HTTP_201_CREATED)
    async def create_search_saved_view(tenant_id: UUID, body: SearchSavedViewCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_SAVED_VIEW_MANAGE)
        if body.account_id is not None: access.require_account(body.account_id)
        if body.portfolio_id is not None: access.require_unrestricted_scope()
        return repository.create_search_saved_view(tenant_id=tenant_id, user_id=p.user_id,
            account_id=body.account_id, portfolio_id=body.portfolio_id, name=body.name,
            filters=body.filters, is_default=body.is_default)

    @app.post("/v1/tenants/{tenant_id}/search-intelligence/saved-views/{view_id}/delete")
    async def delete_search_saved_view(tenant_id: UUID, view_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_SAVED_VIEW_MANAGE)
        repository.delete_search_saved_view(tenant_id=tenant_id, user_id=p.user_id, view_id=view_id)
        return {"ok": True}

    @app.get("/v1/tenants/{tenant_id}/portfolios/{portfolio_id}/search-intelligence/ngrams", response_model=PortfolioNGramResponse)
    async def portfolio_search_ngrams(
        tenant_id: UUID, portfolio_id: UUID, start: date, end: date,
        n: int = Query(default=1, ge=1, le=6), limit: int = Query(default=100, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.SEARCH_INTELLIGENCE_READ)
        access.require_unrestricted_scope()
        rows=repository.portfolio_search_ngrams(tenant_id=tenant_id, portfolio_id=portfolio_id, start=start, end=end, n=n, limit=limit)
        return {"portfolio_id": portfolio_id, "start": start, "end": end, "n": n, "rows": rows}

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/waste-intelligence/overview", response_model=WasteOverviewResponse)
    async def waste_intelligence_overview(
        tenant_id: UUID, account_id: UUID,
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.WASTE_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.waste_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=start, end=end)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/waste-intelligence/queries", response_model=WasteQueryPageResponse)
    async def waste_intelligence_queries(
        tenant_id: UUID, account_id: UUID,
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        family: str | None = Query(default=None, max_length=80),
        disposition: str | None = Query(default=None, max_length=80),
        page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=50, ge=1, le=200),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.WASTE_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.waste_intelligence_query_leaks(tenant_id=tenant_id, account_id=account_id, start=start, end=end, family=family, disposition=disposition, page=page, page_size=page_size)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/waste-intelligence/dimension", response_model=WasteDimensionResponse)
    async def waste_intelligence_dimension(
        tenant_id: UUID, account_id: UUID, dimension: str = Query(pattern="^(network|device|daypart)$"),
        start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.WASTE_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.waste_intelligence_dimension(tenant_id=tenant_id, account_id=account_id, start=start, end=end, dimension=dimension)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/waste-intelligence/geo", response_model=WasteGeoResponse)
    async def waste_intelligence_geo(
        tenant_id: UUID, account_id: UUID, start: date | None = Query(default=None), end: date | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.WASTE_INTELLIGENCE_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.waste_intelligence_geo(tenant_id=tenant_id, account_id=account_id, start=start, end=end)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/measurement-integrity/overview", response_model=MeasurementOverviewResponse)
    async def measurement_integrity_overview(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MEASUREMENT_INTEGRITY_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.measurement_integrity_overview(tenant_id=tenant_id, account_id=account_id)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/measurement-integrity/conversion-actions", response_model=list[MeasurementConversionActionResponse])
    async def measurement_conversion_actions(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MEASUREMENT_INTEGRITY_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.measurement_conversion_actions(tenant_id=tenant_id, account_id=account_id)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/measurement-integrity/goals", response_model=MeasurementGoalsResponse)
    async def measurement_goals(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MEASUREMENT_INTEGRITY_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.measurement_goals(tenant_id=tenant_id, account_id=account_id)

    @app.get("/v1/tenants/{tenant_id}/accounts/{account_id}/measurement-integrity/lag", response_model=MeasurementLagResponse)
    async def measurement_lag(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MEASUREMENT_INTEGRITY_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.measurement_lag(tenant_id=tenant_id, account_id=account_id)

    @app.post("/v1/tenants/{tenant_id}/accounts/{account_id}/measurement-integrity/mappings", response_model=ConversionActionMappingResponse, status_code=status.HTTP_201_CREATED)
    async def measurement_mapping(tenant_id: UUID, account_id: UUID, body: ConversionActionMappingRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MEASUREMENT_MAPPING_MANAGE)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.record_conversion_action_mapping(tenant_id=tenant_id, account_id=account_id, user_id=p.user_id, conversion_action_resource=body.conversion_action_resource, outcome_id=body.outcome_id)

    @app.get("/v1/tenants/{tenant_id}/accounts", response_model=list[AccountResponse])
    async def accounts(tenant_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.ACCOUNT_READ)
        return repository.list_accounts(tenant_id=tenant_id,user_id=p.user_id)

    @app.get(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/workspace",
        response_model=WorkspaceSummary,
    )
    async def workspace(tenant_id: UUID, account_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.ACCOUNT_READ)
        access.require_account(account_id)
        return repository.workspace_summary(tenant_id=tenant_id, account_id=account_id)

    @app.post(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/syncs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_sync(
        tenant_id: UUID,
        account_id: UUID,
        body: SyncCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.SYNC_START)
        receipt = service.enqueue_sync(
            access=access, account_id=account_id, start=body.start, end=body.end,
            idempotency_key=idempotency_key or "", endpoint=request.url.path,
        )
        return _job_response(receipt)

    @app.post(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/business-truth",
        response_model=BusinessTruthResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_truth(
        tenant_id: UUID, account_id: UUID, body: BusinessTruthCreateRequest, request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(
            principal=p, tenant_id=tenant_id, permission=Permission.BUSINESS_TRUTH_WRITE
        )
        snapshot_id, fingerprint, version, replay = service.create_business_truth(
            access=access, account_id=account_id, payload=body.payload, idempotency_key=idempotency_key or "",
            endpoint=request.url.path,
        )
        return BusinessTruthResponse(
            truth_snapshot_id=snapshot_id, truth_fingerprint=fingerprint, version=version,
            idempotency_replay=replay,
        )

    @app.post(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/analyses",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_analysis(
        tenant_id: UUID,
        account_id: UUID,
        body: AnalysisCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.ANALYSIS_START)
        receipt = service.enqueue_analysis(
            access=access, account_id=account_id, sync_run_id=body.sync_run_id,
            truth_snapshot_id=body.truth_snapshot_id, as_of=body.as_of,
            conversion_lag_days=body.conversion_lag_days,
            idempotency_key=idempotency_key or "", endpoint=request.url.path,
        )
        return _job_response(receipt)

    @app.post(
        "/v1/tenants/{tenant_id}/accounts/{account_id}/semantic-shadow-runs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_semantic_shadow(
        tenant_id: UUID,
        account_id: UUID,
        body: SemanticShadowCreateRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(
            principal=p, tenant_id=tenant_id, permission=Permission.SEMANTIC_SHADOW_START
        )
        receipt = service.enqueue_semantic_shadow(
            access=access, account_id=account_id, sync_run_id=body.sync_run_id,
            truth_snapshot_id=body.truth_snapshot_id, idempotency_key=idempotency_key or "",
            endpoint=request.url.path,
        )
        return _job_response(receipt)

    @app.get("/v1/tenants/{tenant_id}/findings", response_model=list[FindingResponse])
    async def findings(
        tenant_id: UUID,
        account_id: UUID | None = Query(default=None),
        analysis_run_id: UUID | None = Query(default=None),
        kind: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.FINDINGS_READ)
        if account_id is not None:
            access.require_account(account_id)
            repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        elif access.account_access_mode != "all_accounts":
            raise AuthorizationError("restricted memberships must select an account")
        return repository.list_findings(
            tenant_id=tenant_id, analysis_run_id=analysis_run_id, kind=kind, limit=limit,
            account_id=account_id,
        )

    @app.get("/v1/tenants/{tenant_id}/recovery-cases", response_model=list[RecoveryCaseSummaryResponse])
    async def recovery_cases(
        tenant_id: UUID, account_id: UUID = Query(...), state_filter: str | None = Query(default=None, alias="state"),
        risk: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CASE_READ)
        access.require_account(account_id)
        return repository.list_recovery_cases(tenant_id=tenant_id, account_id=account_id, state=state_filter, risk=risk, limit=limit)

    @app.get("/v1/tenants/{tenant_id}/recovery-cases/{case_id}", response_model=RecoveryCaseDetailResponse)
    async def recovery_case_detail(tenant_id: UUID, case_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CASE_READ)
        detail=repository.recovery_case_detail(tenant_id=tenant_id, case_id=case_id)
        access.require_account(UUID(str(detail["account_id"])))
        return detail

    @app.post("/v1/tenants/{tenant_id}/recovery-cases/{case_id}/events", response_model=RecoveryCaseEventResponse, status_code=status.HTTP_201_CREATED)
    async def recovery_case_event(tenant_id: UUID, case_id: UUID, body: RecoveryCaseEventRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CASE_MANAGE)
        detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=case_id); access.require_account(UUID(str(detail["account_id"])))
        return repository.append_recovery_case_event(tenant_id=tenant_id, case_id=case_id, actor=access.actor_id, event_type=body.event_type, note=body.note, assigned_to=body.assigned_to)

    @app.post("/v1/tenants/{tenant_id}/recovery-cases/{case_id}/decision", response_model=ProposalDecisionResponse)
    async def recovery_case_decision(tenant_id: UUID, case_id: UUID, body: ProposalDecisionRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.PROPOSAL_DECIDE)
        detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=case_id); access.require_account(UUID(str(detail["account_id"])))
        event_id=service.decide_proposal(access=access, proposal_artifact_id=case_id, proposal_fingerprint=body.proposal_fingerprint, decision=body.decision, note=body.note)
        return ProposalDecisionResponse(decision_event_id=event_id, decision=body.decision, proposal_artifact_id=case_id)

    @app.post("/v1/tenants/{tenant_id}/recovery-cases/{case_id}/execute", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def recovery_case_execute(tenant_id: UUID, case_id: UUID, request: Request, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")]=None, p: Principal=Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MUTATION_EXECUTE)
        detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=case_id); access.require_account(UUID(str(detail["account_id"])))
        return _job_response(service.enqueue_mutation(access=access, proposal_artifact_id=case_id, idempotency_key=idempotency_key or "", endpoint=request.url.path))

    @app.post("/v1/tenants/{tenant_id}/recovery-cases/{case_id}/rollback", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def recovery_case_rollback(tenant_id: UUID, case_id: UUID, request: Request, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")]=None, p: Principal=Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MUTATION_ROLLBACK)
        detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=case_id); access.require_account(UUID(str(detail["account_id"])))
        return _job_response(service.enqueue_mutation(access=access, proposal_artifact_id=case_id, idempotency_key=idempotency_key or "", endpoint=request.url.path, rollback=True))

    @app.get(
        "/v1/tenants/{tenant_id}/proposals",
        response_model=list[ProposalStateResponse],
    )
    async def proposals(
        tenant_id: UUID,
        account_id: UUID = Query(...),
        analysis_run_id: UUID | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.FINDINGS_READ)
        access.require_account(account_id)
        repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.list_proposals(
            tenant_id=tenant_id, account_id=account_id, analysis_run_id=analysis_run_id, limit=limit
        )

    @app.post(
        "/v1/tenants/{tenant_id}/proposals/{proposal_artifact_id}/decision",
        response_model=ProposalDecisionResponse,
    )
    async def decide(
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        body: ProposalDecisionRequest,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.PROPOSAL_DECIDE)
        if access.account_access_mode!="all_accounts":
            detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=proposal_artifact_id); access.require_account(UUID(str(detail["account_id"])))
        event_id = service.decide_proposal(
            access=access,
            proposal_artifact_id=proposal_artifact_id,
            proposal_fingerprint=body.proposal_fingerprint,
            decision=body.decision,
            note=body.note,
        )
        return ProposalDecisionResponse(
            decision_event_id=event_id,
            decision=body.decision,
            proposal_artifact_id=proposal_artifact_id,
        )

    @app.post(
        "/v1/tenants/{tenant_id}/proposals/{proposal_artifact_id}/execute",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def execute(
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.MUTATION_EXECUTE)
        if access.account_access_mode!="all_accounts":
            detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=proposal_artifact_id); access.require_account(UUID(str(detail["account_id"])))
        return _job_response(service.enqueue_mutation(
            access=access, proposal_artifact_id=proposal_artifact_id,
            idempotency_key=idempotency_key or "", endpoint=request.url.path,
        ))

    @app.post(
        "/v1/tenants/{tenant_id}/proposals/{proposal_artifact_id}/rollback",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def rollback(
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        p: Principal = Depends(principal),
    ):
        access = service.access(principal=p, tenant_id=tenant_id, permission=Permission.MUTATION_ROLLBACK)
        if access.account_access_mode!="all_accounts":
            detail=repository.recovery_case_detail(tenant_id=tenant_id,case_id=proposal_artifact_id); access.require_account(UUID(str(detail["account_id"])))
        return _job_response(service.enqueue_mutation(
            access=access, proposal_artifact_id=proposal_artifact_id,
            idempotency_key=idempotency_key or "", endpoint=request.url.path, rollback=True,
        ))


    @app.get("/v1/tenants/{tenant_id}/jobs/{job_id}", response_model=JobDetailResponse)
    async def job_status(tenant_id: UUID, job_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.TENANT_READ)
        return repository.get_job(tenant_id=tenant_id, user_id=p.user_id, job_id=job_id)

    @app.get("/v1/tenants/{tenant_id}/recovery-center", response_model=RecoveryCenterOverviewResponse)
    async def recovery_center_overview(
        tenant_id: UUID, account_id: UUID | None = Query(default=None), portfolio_id: UUID | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CENTER_READ)
        if access.account_access_mode != "all_accounts":
            if account_id is None or portfolio_id is not None: raise AuthorizationError("restricted memberships must use account scope")
            access.require_account(account_id)
        return repository.recovery_center_overview(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id)

    @app.get("/v1/tenants/{tenant_id}/recovery-center/cases", response_model=list[RecoveryCenterCaseResponse])
    async def recovery_center_cases(
        tenant_id: UUID, account_id: UUID | None = Query(default=None), portfolio_id: UUID | None = Query(default=None),
        causal_status: str | None = Query(default=None), limit: int = Query(default=300, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CENTER_READ)
        if access.account_access_mode != "all_accounts":
            if account_id is None or portfolio_id is not None: raise AuthorizationError("restricted memberships must use account scope")
            access.require_account(account_id)
        return repository.recovery_center_cases(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id, causal_status=causal_status, limit=limit)

    @app.get("/v1/tenants/{tenant_id}/recovery-center/breakdown", response_model=RecoveryCenterBreakdownResponse)
    async def recovery_center_breakdown(
        tenant_id: UUID, dimension: str = Query(..., pattern="^(account|campaign|leak_type)$"),
        account_id: UUID | None = Query(default=None), portfolio_id: UUID | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CENTER_READ)
        if access.account_access_mode != "all_accounts":
            if account_id is None or portfolio_id is not None: raise AuthorizationError("restricted memberships must use account scope")
            access.require_account(account_id)
        return repository.recovery_center_breakdown(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id, dimension=dimension)

    @app.get("/v1/tenants/{tenant_id}/recovery-center/timeline", response_model=RecoveryCenterTimelineResponse)
    async def recovery_center_timeline(
        tenant_id: UUID, account_id: UUID | None = Query(default=None), portfolio_id: UUID | None = Query(default=None),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.RECOVERY_CENTER_READ)
        if access.account_access_mode != "all_accounts":
            if account_id is None or portfolio_id is not None: raise AuthorizationError("restricted memberships must use account scope")
            access.require_account(account_id)
        return repository.recovery_center_timeline(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id)

    @app.get("/v1/tenants/{tenant_id}/monitoring", response_model=MonitoringOverviewResponse)
    async def monitoring_overview(tenant_id: UUID, account_id: UUID | None = Query(default=None), p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITORING_READ)
        if access.account_access_mode!="all_accounts" and account_id is None: raise AuthorizationError("restricted memberships must select an account")
        if account_id is not None: access.require_account(account_id); repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        return repository.monitoring_overview(tenant_id=tenant_id, account_id=account_id)

    @app.get("/v1/tenants/{tenant_id}/monitoring/alerts", response_model=list[MonitoringAlertResponse])
    async def monitoring_alerts(tenant_id: UUID, account_id: UUID | None = Query(default=None), state: str | None = Query(default=None), severity: str | None = Query(default=None), monitor_type: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=500), p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITORING_READ)
        if access.account_access_mode!="all_accounts" and account_id is None: raise AuthorizationError("restricted memberships must select an account")
        if account_id is not None: access.require_account(account_id)
        return repository.monitoring_alerts(tenant_id=tenant_id, account_id=account_id, state=state, severity=severity, monitor_type=monitor_type, limit=limit)

    @app.get("/v1/tenants/{tenant_id}/monitoring/alerts/{alert_id}", response_model=MonitoringAlertDetailResponse)
    async def monitoring_alert_detail(tenant_id: UUID, alert_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITORING_READ)
        detail=repository.monitoring_alert_detail(tenant_id=tenant_id, alert_id=alert_id)
        access.require_account(UUID(str(detail["account_id"])))
        return detail

    @app.post("/v1/tenants/{tenant_id}/monitoring/alerts/{alert_id}/events", response_model=MonitoringAlertDetailResponse)
    async def monitoring_alert_event(tenant_id: UUID, alert_id: UUID, body: MonitoringAlertEventRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.ALERT_MANAGE)
        detail=repository.monitoring_alert_detail(tenant_id=tenant_id,alert_id=alert_id); access.require_account(UUID(str(detail["account_id"])))
        return repository.monitoring_alert_event(tenant_id=tenant_id, alert_id=alert_id, actor=p.actor_id, event_type=body.event_type, payload=body.payload)

    @app.get("/v1/tenants/{tenant_id}/monitoring/policies", response_model=list[MonitoringPolicyResponse])
    async def monitoring_policies(tenant_id: UUID, account_id: UUID | None = Query(default=None), p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITORING_READ)
        if access.account_access_mode!="all_accounts" and account_id is None: raise AuthorizationError("restricted memberships must select an account")
        if account_id is not None: access.require_account(account_id)
        return repository.monitoring_policies(tenant_id=tenant_id, account_id=account_id)

    @app.post("/v1/tenants/{tenant_id}/monitoring/policies", response_model=MonitoringPolicyResponse, status_code=status.HTTP_201_CREATED)
    async def monitoring_policy_event(tenant_id: UUID, body: MonitoringPolicyRequest, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITOR_POLICY_MANAGE)
        return repository.monitoring_policy_event(tenant_id=tenant_id, account_id=body.account_id, actor=p.actor_id, monitor_type=body.monitor_type, enabled=body.enabled, severity_override=body.severity_override, config=body.config)

    @app.post("/v1/tenants/{tenant_id}/accounts/{account_id}/monitoring/evaluate", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def monitoring_evaluate(tenant_id: UUID, account_id: UUID, request: Request, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.MONITORING_EVALUATE)
        return _job_response(service.enqueue_monitoring_evaluation(access=access, account_id=account_id, idempotency_key=idempotency_key or "", endpoint=request.url.path))

    @app.get("/v1/tenants/{tenant_id}/reports/templates", response_model=list[ReportTemplateResponse])
    async def report_templates(tenant_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        return [
            {"report_type":"executive_recovery","name":"Executive Recovery Report","supported_scopes":["organization","portfolio","account"],"requires_period":False,"description":"Recovery proof with non-additive financial classes."},
            {"report_type":"waste","name":"Waste Intelligence Report","supported_scopes":["account"],"requires_period":True,"description":"Observed query leakage for an explicit period."},
            {"report_type":"measurement_integrity","name":"Measurement Integrity Report","supported_scopes":["account"],"requires_period":False,"description":"Conversion configuration, Business Truth mappings and measurement confidence."},
            {"report_type":"search_demand","name":"Search Demand Report","supported_scopes":["account"],"requires_period":True,"description":"Observed search demand, intent and lexical phrase evidence."},
            {"report_type":"account_health","name":"Account Health Report","supported_scopes":["account"],"requires_period":False,"description":"Data, measurement and active incident health."},
            {"report_type":"change_impact","name":"Change Impact Report","supported_scopes":["account"],"requires_period":False,"description":"Intervention outcomes and Recovery Ledger timeline."},
            {"report_type":"monthly_client","name":"Monthly Client Report","supported_scopes":["account"],"requires_period":True,"description":"Period search/waste context plus clearly labeled current measurement, monitoring and cumulative recovery proof."},
            {"report_type":"agency_portfolio","name":"Agency Portfolio Report","supported_scopes":["organization","portfolio"],"requires_period":False,"description":"Cross-account recovery proof and account breakdowns."},
        ]

    @app.get("/v1/tenants/{tenant_id}/reports", response_model=list[ReportGenerationSummaryResponse])
    async def reports(tenant_id: UUID, report_type: str | None = Query(default=None), scope_kind: str | None = Query(default=None), scope_id: str | None = Query(default=None), limit: int = Query(default=100,ge=1,le=500), p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        if access.account_access_mode!="all_accounts":
            if scope_kind!="account" or not scope_id: raise AuthorizationError("restricted memberships must filter reports to an account")
            access.require_account(UUID(scope_id))
        return repository.list_report_generations(tenant_id=tenant_id,report_type=report_type,scope_kind=scope_kind,scope_id=scope_id,limit=limit)

    @app.post("/v1/tenants/{tenant_id}/reports/generate", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def generate_report(tenant_id: UUID, body: ReportGenerationRequest, request: Request, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORT_GENERATE)
        return _job_response(service.enqueue_report_generation(access=access,report_type=body.report_type,scope_kind=body.scope_kind,scope_id=body.scope_id,period_start=body.period_start,period_end=body.period_end,idempotency_key=idempotency_key or "",endpoint=request.url.path))

    @app.get("/v1/tenants/{tenant_id}/reports/{generation_id}", response_model=ReportGenerationDetailResponse)
    async def report_detail(tenant_id: UUID, generation_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        generation=repository.report_generation(tenant_id=tenant_id,generation_id=generation_id)
        if generation["scope_kind"]=="account": access.require_account(UUID(str(generation["scope_id"])))
        elif access.account_access_mode!="all_accounts": raise AuthorizationError("report scope is outside assigned accounts")
        return generation

    @app.get("/v1/tenants/{tenant_id}/reports/{generation_id}/artifact/{artifact_format}")
    async def report_artifact(tenant_id: UUID, generation_id: UUID, artifact_format: str, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        generation=repository.report_generation(tenant_id=tenant_id,generation_id=generation_id)
        if generation["scope_kind"]=="account": access.require_account(UUID(str(generation["scope_id"])))
        elif access.account_access_mode!="all_accounts": raise AuthorizationError("report scope is outside assigned accounts")
        a=repository.report_artifact(tenant_id=tenant_id,generation_id=generation_id,artifact_format=artifact_format)
        ext="pdf" if artifact_format=="pdf" else "csv"
        filename=f"recovery-os-{a['report_type']}-{str(generation_id)[:8]}.{ext}"
        return Response(content=bytes(a["content"]),media_type=a["content_type"],headers={"Content-Disposition":f'attachment; filename="{filename}"',"X-Artifact-SHA256":a["artifact_sha256"]})

    @app.get("/v1/tenants/{tenant_id}/report-shares", response_model=list[ReportShareResponse])
    async def report_shares(tenant_id: UUID, generation_id: UUID | None = Query(default=None), p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        if access.account_access_mode!="all_accounts":
            if generation_id is None: raise AuthorizationError("restricted memberships must select a report generation")
            g=repository.report_generation(tenant_id=tenant_id,generation_id=generation_id)
            if g["scope_kind"]!="account": raise AuthorizationError("report scope is outside assigned accounts")
            access.require_account(UUID(str(g["scope_id"])))
        return repository.list_report_shares(tenant_id=tenant_id,generation_id=generation_id)

    @app.post("/v1/tenants/{tenant_id}/reports/{generation_id}/shares", response_model=ReportShareResponse, status_code=status.HTTP_201_CREATED)
    async def create_report_share(tenant_id: UUID, generation_id: UUID, body: ReportShareCreateRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORT_SHARE_MANAGE)
        g=repository.report_generation(tenant_id=tenant_id,generation_id=generation_id)
        if g["scope_kind"]=="account": access.require_account(UUID(str(g["scope_id"])))
        elif access.account_access_mode!="all_accounts": raise AuthorizationError("report scope is outside assigned accounts")
        return repository.create_report_share(tenant_id=tenant_id,user_id=p.user_id,actor=p.actor_id,generation_id=generation_id,expires_days=body.expires_days)

    @app.post("/v1/tenants/{tenant_id}/report-shares/{share_id}/revoke", response_model=ReportShareResponse)
    async def revoke_report_share(tenant_id: UUID, share_id: UUID, p: Principal = Depends(principal)):
        service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORT_SHARE_MANAGE)
        return repository.revoke_report_share(tenant_id=tenant_id,actor=p.actor_id,share_id=share_id)

    @app.get("/v1/tenants/{tenant_id}/report-schedules", response_model=list[ReportScheduleResponse])
    async def report_schedules(tenant_id: UUID, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORTING_READ)
        access.require_unrestricted_scope()
        return repository.list_report_schedules(tenant_id=tenant_id)

    @app.post("/v1/tenants/{tenant_id}/report-schedules", response_model=ReportScheduleResponse, status_code=status.HTTP_201_CREATED)
    async def save_report_schedule(tenant_id: UUID, body: ReportScheduleRequest, p: Principal = Depends(principal)):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.REPORT_SCHEDULE_MANAGE)
        access.require_unrestricted_scope()
        return repository.record_report_schedule(tenant_id=tenant_id,user_id=p.user_id,schedule_id=body.schedule_id,report_type=body.report_type,scope_kind=body.scope_kind,scope_id=body.scope_id,frequency=body.frequency,timezone_name=body.timezone_name,hour=body.hour,minute=body.minute,weekday=body.weekday,day_of_month=body.day_of_month,recipients=body.recipients,enabled=body.enabled)

    @app.get("/v1/public/report-shares/{token}", response_model=PublicReportResponse)
    async def public_report_share(token: str, response: Response):
        response.headers["Cache-Control"]="no-store, private"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        return repository.public_report(token=token,record_access=True)

    @app.get("/v1/public/report-shares/{token}/artifact/{artifact_format}")
    async def public_report_artifact(token: str, artifact_format: str):
        a=repository.public_report_artifact(token=token,artifact_format=artifact_format)
        ext="pdf" if artifact_format=="pdf" else "csv"
        return Response(content=bytes(a["content"]),media_type=a["content_type"],headers={"Content-Disposition":f'attachment; filename="recovery-os-shared-report.{ext}"',"X-Artifact-SHA256":a["artifact_sha256"],"Cache-Control":"no-store, private","Referrer-Policy":"no-referrer","X-Robots-Tag":"noindex, nofollow"})

    @app.get("/v1/tenants/{tenant_id}/recovery-ledger", response_model=list[LedgerResponse])
    async def ledger(
        tenant_id: UUID,
        account_id: UUID | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        p: Principal = Depends(principal),
    ):
        access=service.access(principal=p, tenant_id=tenant_id, permission=Permission.LEDGER_READ)
        if account_id is not None:
            access.require_account(account_id)
            repository.ensure_account(tenant_id=tenant_id, account_id=account_id)
        elif access.account_access_mode!="all_accounts":
            raise AuthorizationError("restricted memberships must select an account")
        return repository.list_ledger(tenant_id=tenant_id, limit=limit, account_id=account_id)

    return app


def create_app_from_env() -> FastAPI:
    validate_build_identity()
    settings = ApiSettings.from_env()
    core = PostgresRecoveryRepository(settings.database_url)
    repo = PostgresApiRepository(core)
    verifier = SupabaseJWTVerifier(project_url=settings.supabase_url)
    billing_runtime = None
    if settings.billing_enabled:
        billing_runtime = BillingRuntime(
            provider=RazorpayProvider.from_env(),
            catalog=BillingPlanCatalog.from_env(),
            webhook_secret=settings.razorpay_webhook_secret,
            grace_hours=settings.billing_grace_hours,
        )
    oauth_values = (
        settings.google_ads_oauth_client_id, settings.google_ads_oauth_client_secret,
        settings.google_ads_oauth_redirect_uri, settings.google_oauth_secret_manager_project,
    )
    oauth_runtime = None
    if any(oauth_values):
        if not all(oauth_values):
            raise RuntimeError(
                "GOOGLE_ADS_OAUTH_CLIENT_ID, GOOGLE_ADS_OAUTH_CLIENT_SECRET, GOOGLE_ADS_OAUTH_REDIRECT_URI and "
                "GOOGLE_OAUTH_SECRET_MANAGER_PROJECT must all be configured together"
            )
        oauth_runtime = OAuthConnectionRuntime(
            provider=GoogleOAuthProvider(GoogleOAuthSettings(
                client_id=settings.google_ads_oauth_client_id,
                client_secret=settings.google_ads_oauth_client_secret,
                redirect_uri=settings.google_ads_oauth_redirect_uri,
            )),
            vault=GoogleSecretManagerCredentialVault(project_id=settings.google_oauth_secret_manager_project),
        )
    signup_abuse_verifier=None
    if settings.turnstile_site_key and settings.turnstile_secret_key and settings.turnstile_hostnames:
        signup_abuse_verifier=TurnstileVerifier(TurnstileConfig(site_key=settings.turnstile_site_key,secret_key=settings.turnstile_secret_key,expected_hostnames=frozenset(settings.turnstile_hostnames)))
    onboarding_service = OnboardingApplicationService(
        store=PostgresOnboardingStore(core,public_workspace_max_per_user_24h=settings.public_workspace_max_per_user_24h), api_repository=repo, oauth=oauth_runtime,
        billing=BillingApplicationService(repository=repo, runtime=billing_runtime),
        terms_url=settings.terms_url, terms_version=settings.terms_version,
        privacy_url=settings.privacy_url, privacy_version=settings.privacy_version,
        signup_abuse_verifier=signup_abuse_verifier,
    )
    return create_app(
        repository=repo, verifier=verifier, allowed_origins=settings.allowed_origins,
        billing_runtime=billing_runtime, readiness_probe=lambda: database_ready(settings.database_url),
        onboarding=onboarding_service,
        public_legal_config={"terms_url":settings.terms_url,"terms_version":settings.terms_version,
                             "privacy_url":settings.privacy_url,"privacy_version":settings.privacy_version},
        public_signup_abuse_config={"ready":bool(signup_abuse_verifier),"site_key":settings.turnstile_site_key or None,"max_per_user_24h":settings.public_workspace_max_per_user_24h},
    )
