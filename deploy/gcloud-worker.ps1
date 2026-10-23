param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$Region,
  [Parameter(Mandatory=$true)][string]$Image,
  [Parameter(Mandatory=$true)][string]$RuntimeServiceAccount,
  [string]$LoginCustomerId = "",
  [int]$Instances = 1,
  [int]$HealthPort = 8080,
  [string]$WorkerPool = "recovery-worker",
  [switch]$EnableReportEmail,
  [string]$ReportSmtpHost = "",
  [int]$ReportSmtpPort = 587,
  [ValidateSet("starttls","ssl","plain")][string]$ReportSmtpTlsMode = "starttls",
  [string]$ReportSmtpFrom = "",
  [string]$ReportSmtpUsernameSecret = "",
  [string]$ReportSmtpPasswordSecret = "",
  [Parameter(Mandatory=$true)][string]$ReleaseId,
  [ValidateSet("staging","production")][string]$Environment = "production"
)

$ErrorActionPreference = "Stop"
if ($Instances -lt 1) { throw "Instances must be at least 1 for a live worker pool." }
if ($HealthPort -lt 1 -or $HealthPort -gt 65535) { throw "HealthPort must be between 1 and 65535." }

# Worker Pool is intended for continuous work and has no public HTTP endpoint.
$EnvVars = "RECOVERY_ENVIRONMENT=$Environment,RECOVERY_RELEASE_ID=$ReleaseId,RECOVERY_WORKER_HEALTH_PORT=$HealthPort,GOOGLE_ADS_SERVICE_ACCOUNT_JSON=/secrets/google-ads/service-account.json,GOOGLE_ADS_LOGIN_CUSTOMER_ID=$LoginCustomerId,GOOGLE_OAUTH_SECRET_MANAGER_PROJECT=$ProjectId"
$Secrets = "RECOVERY_WORKER_DATABASE_URL=recovery-worker-database-url:latest,GEMINI_API_KEY=recovery-gemini-api-key:latest,GOOGLE_ADS_OAUTH_CLIENT_ID=recovery-google-oauth-client-id:latest,GOOGLE_ADS_OAUTH_CLIENT_SECRET=recovery-google-oauth-client-secret:latest,/secrets/google-ads/service-account.json=recovery-google-ads-service-account:latest"
if ($EnableReportEmail) {
  if ([string]::IsNullOrWhiteSpace($ReportSmtpHost) -or [string]::IsNullOrWhiteSpace($ReportSmtpFrom)) { throw "Report email requires ReportSmtpHost and ReportSmtpFrom." }
  $EnvVars += ",REPORT_SMTP_HOST=$ReportSmtpHost,REPORT_SMTP_PORT=$ReportSmtpPort,REPORT_SMTP_TLS_MODE=$ReportSmtpTlsMode,REPORT_SMTP_FROM=$ReportSmtpFrom"
  if (-not [string]::IsNullOrWhiteSpace($ReportSmtpUsernameSecret)) { $Secrets += ",REPORT_SMTP_USERNAME=${ReportSmtpUsernameSecret}:latest" }
  if (-not [string]::IsNullOrWhiteSpace($ReportSmtpPasswordSecret)) { $Secrets += ",REPORT_SMTP_PASSWORD=${ReportSmtpPasswordSecret}:latest" }
}

gcloud run worker-pools deploy $WorkerPool `
  --project $ProjectId `
  --region $Region `
  --image $Image `
  --instances $Instances `
  --service-account $RuntimeServiceAccount `
  --cpu 1 `
  --memory 1Gi `
  --command recovery-worker `
  --args "--lease-seconds=300,--idle-seconds=2" `
  --set-env-vars $EnvVars `
  --update-secrets $Secrets
if ($LASTEXITCODE -ne 0) { throw "Worker deployment failed (exit $LASTEXITCODE)." }
