param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$Region,
  [Parameter(Mandatory=$true)][string]$Image,
  [Parameter(Mandatory=$true)][string]$RuntimeServiceAccount,
  [Parameter(Mandatory=$true)][string]$DashboardOrigin,
  [Parameter(Mandatory=$true)][string]$SupabaseUrl,
  [string]$Service = "recovery-api",
  [Parameter(Mandatory=$true)][string]$ReleaseId,
  [ValidateSet("staging","production")][string]$Environment = "production",
  [ValidateRange(0,720)][int]$BillingGraceHours = 0,
  [string]$OAuthVerificationAck = "",
  [string]$GoogleAdsProductionAccessAck = "",
  [string]$RazorpayLiveActivationAck = "",
  [string]$RazorpayLiveWebhookAck = "",
  [string]$TermsUrl = "",
  [string]$TermsVersion = "",
  [string]$PrivacyUrl = "",
  [string]$PrivacyVersion = "",
  [string]$DataDeletionUrl = "",
  [string]$SupportEmail = "",
  [string]$StatusUrl = "",
  [string]$TurnstileSiteKey = "",
  [string]$TurnstileHostnames = "",
  [ValidateRange(1,20)][int]$PublicWorkspaceMaxPerUser24h = 1,
  [string]$TurnstileSecretName = "recovery-turnstile-secret"
)

$ErrorActionPreference = "Stop"
if ($Environment -eq "production") {
  if ($OAuthVerificationAck -ne "RESTRICTED_SCOPE_VERIFIED") { throw "Production self-serve Google Ads onboarding requires -OAuthVerificationAck RESTRICTED_SCOPE_VERIFIED only after Google's restricted-scope verification is actually complete." }
  if ($GoogleAdsProductionAccessAck -ne "EXPLORER_OR_HIGHER") { throw "Production requires -GoogleAdsProductionAccessAck EXPLORER_OR_HIGHER only after the Google Cloud project has production Google Ads API access." }
  if ($RazorpayLiveActivationAck -ne "LIVE_ACCOUNT_ACTIVATED") { throw "Production requires -RazorpayLiveActivationAck LIVE_ACCOUNT_ACTIVATED only after the Razorpay merchant account is live." }
  if ($RazorpayLiveWebhookAck -ne "LIVE_WEBHOOK_VERIFIED") { throw "Production requires -RazorpayLiveWebhookAck LIVE_WEBHOOK_VERIFIED only after the live webhook path is verified." }
  foreach ($u in @($TermsUrl,$PrivacyUrl,$DataDeletionUrl)) { if (-not $u.StartsWith("https://")) { throw "Production requires HTTPS TermsUrl, PrivacyUrl and DataDeletionUrl." } }
  if ([string]::IsNullOrWhiteSpace($TermsVersion) -or $TermsVersion.Length -gt 120) { throw "Production requires a non-empty TermsVersion of at most 120 characters." }
  if ([string]::IsNullOrWhiteSpace($PrivacyVersion) -or $PrivacyVersion.Length -gt 120) { throw "Production requires a non-empty PrivacyVersion of at most 120 characters." }
  if ([string]::IsNullOrWhiteSpace($SupportEmail) -or -not $SupportEmail.Contains("@")) { throw "Production requires SupportEmail." }
  if ([string]::IsNullOrWhiteSpace($TurnstileSiteKey) -or [string]::IsNullOrWhiteSpace($TurnstileHostnames)) { throw "Production public signup requires TurnstileSiteKey and TurnstileHostnames." }
  if ($TurnstileHostnames -match "(^|,)(localhost|127\.0\.0\.1|::1)(,|$)") { throw "Production TurnstileHostnames cannot contain local hosts." }
}

$EnvVars = "RECOVERY_ENVIRONMENT=$Environment,RECOVERY_RELEASE_ID=$ReleaseId,SUPABASE_URL=$SupabaseUrl,API_ALLOWED_ORIGINS=$DashboardOrigin,BILLING_ENABLED=true,BILLING_GRACE_HOURS=$BillingGraceHours,GOOGLE_ADS_OAUTH_REDIRECT_URI=$($DashboardOrigin.TrimEnd('/'))/api/google-ads/oauth/callback,GOOGLE_OAUTH_SECRET_MANAGER_PROJECT=$ProjectId,GOOGLE_ADS_OAUTH_VERIFICATION_ACK=$OAuthVerificationAck,GOOGLE_ADS_PRODUCTION_ACCESS_ACK=$GoogleAdsProductionAccessAck,RAZORPAY_LIVE_ACTIVATION_ACK=$RazorpayLiveActivationAck,RAZORPAY_LIVE_WEBHOOK_ACK=$RazorpayLiveWebhookAck,RECOVERY_TERMS_URL=$TermsUrl,RECOVERY_TERMS_VERSION=$TermsVersion,RECOVERY_PRIVACY_URL=$PrivacyUrl,RECOVERY_PRIVACY_VERSION=$PrivacyVersion,RECOVERY_DATA_DELETION_URL=$DataDeletionUrl,RECOVERY_SUPPORT_EMAIL=$SupportEmail,RECOVERY_STATUS_URL=$StatusUrl,RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H=$PublicWorkspaceMaxPerUser24h"
$Secrets = "DATABASE_URL=recovery-api-database-url:latest,RAZORPAY_KEY_ID=recovery-razorpay-key-id:latest,RAZORPAY_KEY_SECRET=recovery-razorpay-key-secret:latest,RAZORPAY_WEBHOOK_SECRET=recovery-razorpay-webhook-secret:latest,BILLING_PLANS_JSON=recovery-billing-plans-json:latest,GOOGLE_ADS_OAUTH_CLIENT_ID=recovery-google-oauth-client-id:latest,GOOGLE_ADS_OAUTH_CLIENT_SECRET=recovery-google-oauth-client-secret:latest"
if (-not [string]::IsNullOrWhiteSpace($TurnstileSiteKey) -and -not [string]::IsNullOrWhiteSpace($TurnstileHostnames)) {
  $EnvVars += ",RECOVERY_TURNSTILE_SITE_KEY=$TurnstileSiteKey,RECOVERY_TURNSTILE_HOSTNAMES=$TurnstileHostnames"
  $Secrets += ",RECOVERY_TURNSTILE_SECRET=${TurnstileSecretName}:latest"
}

# Secret names below are references in Secret Manager, never literal secret values.
gcloud run deploy $Service `
  --project $ProjectId `
  --region $Region `
  --image $Image `
  --service-account $RuntimeServiceAccount `
  --allow-unauthenticated `
  --cpu 1 `
  --memory 1Gi `
  --concurrency 40 `
  --min 0 `
  --max 10 `
  --set-env-vars $EnvVars `
  --update-secrets $Secrets `
  --startup-probe "httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=1,failureThreshold=10,timeoutSeconds=2,periodSeconds=3" `
  --readiness-probe "httpGet.path=/readyz,httpGet.port=8080,failureThreshold=3,timeoutSeconds=3,periodSeconds=10" `
  --liveness-probe "httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=10,failureThreshold=3,timeoutSeconds=2,periodSeconds=30"
if ($LASTEXITCODE -ne 0) { throw "API deployment failed (exit $LASTEXITCODE)." }
