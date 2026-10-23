param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$Region,
  [Parameter(Mandatory=$true)][string]$ArtifactRepository,
  [Parameter(Mandatory=$true)][string]$RuntimeServiceAccount,
  [Parameter(Mandatory=$true)][string]$DashboardOrigin,
  [Parameter(Mandatory=$true)][string]$SupabaseUrl,
  [string]$LoginCustomerId = "",
  [ValidateSet("staging","production")][string]$Environment = "staging",
  [string]$DashboardUrl = "",
  [switch]$DeployDashboard,
  [switch]$RequireBillingFull,
  [switch]$RequireGoogleAdsRead,
  [switch]$RequireGoogleTestAccount
)
$ErrorActionPreference = "Stop"

function Require-Command([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name is required" }
}
function Assert-NativeSuccess([string]$Operation) {
  if ($LASTEXITCODE -ne 0) { throw "$Operation failed (exit $LASTEXITCODE); release stopped." }
}
Require-Command "gcloud"
Require-Command "git"
Require-Command "recovery-migrate"
Require-Command "recovery-staging-accept"
if ($DeployDashboard) { Require-Command "vercel" }
if (-not $env:DATABASE_URL) { throw "DATABASE_URL must be set in the current process for migration." }

$SourceRevision = (git rev-parse HEAD)
Assert-NativeSuccess "Reading Git revision"
$SourceRevision = $SourceRevision.Trim()
if ($SourceRevision -notmatch "^[0-9a-f]{40}$|^[0-9a-f]{64}$") { throw "A full Git commit SHA is required." }
$gitChanges = git status --porcelain
Assert-NativeSuccess "Checking release worktree"
if ($gitChanges) { throw "Commit or remove unreviewed worktree changes before building a named release." }
$gitPart = $SourceRevision.Substring(0,12)
$ReleaseId = "r$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))-$gitPart"
$ImageBase = "$Region-docker.pkg.dev/$ProjectId/$ArtifactRepository/recovery"
$TaggedImage = "$ImageBase`:$ReleaseId"

Write-Host "Building release $ReleaseId"
gcloud builds submit . --project $ProjectId --config deploy/cloudbuild.backend.yaml --substitutions "_IMAGE=$TaggedImage,_RELEASE_ID=$ReleaseId,_REVISION=$SourceRevision"
Assert-NativeSuccess "Backend image build"
$Digest = gcloud artifacts docker images describe $TaggedImage --project $ProjectId --format "value(image_summary.digest)"
Assert-NativeSuccess "Resolving backend image digest"
$Digest = $Digest.Trim()
if (-not $Digest.StartsWith("sha256:")) { throw "Could not resolve immutable image digest for $TaggedImage" }
$ImmutableImage = "$ImageBase@$Digest"

Write-Host "Applying database migrations before traffic deployment"
recovery-migrate
Assert-NativeSuccess "Database migrations"

& "$PSScriptRoot/gcloud-api.ps1" -ProjectId $ProjectId -Region $Region -Image $ImmutableImage `
  -RuntimeServiceAccount $RuntimeServiceAccount -DashboardOrigin $DashboardOrigin -SupabaseUrl $SupabaseUrl `
  -ReleaseId $ReleaseId -Environment $Environment

& "$PSScriptRoot/gcloud-worker.ps1" -ProjectId $ProjectId -Region $Region -Image $ImmutableImage `
  -RuntimeServiceAccount $RuntimeServiceAccount -LoginCustomerId $LoginCustomerId `
  -ReleaseId $ReleaseId -Environment $Environment

$ApiUrl = gcloud run services describe recovery-api --project $ProjectId --region $Region --format "value(status.url)"
Assert-NativeSuccess "Resolving API URL"
$ApiUrl = $ApiUrl.Trim()
if (-not $ApiUrl) { throw "Cloud Run API URL could not be resolved" }

if ($DeployDashboard) {
  Push-Location "$PSScriptRoot/../web"
  try {
    $deployOutput = vercel deploy --prod --yes
    Assert-NativeSuccess "Dashboard deployment"
    $DashboardUrl = ($deployOutput | Select-Object -Last 1).Trim()
  } finally { Pop-Location }
}
if (-not $DashboardUrl) { $DashboardUrl = $DashboardOrigin }

$Manifest = [ordered]@{
  release_id = $ReleaseId
  source_revision = $SourceRevision
  environment = $Environment
  image = $ImmutableImage
  image_digest = $Digest
  api_url = $ApiUrl
  dashboard_url = $DashboardUrl
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 "phase19-release-manifest.json"

if ($env:RECOVERY_ACCEPTANCE_TENANT_ID -and $env:RECOVERY_ACCEPTANCE_BEARER_TOKEN) {
  $args = @(
    "--api-url", $ApiUrl,
    "--dashboard-url", $DashboardUrl,
    "--tenant-id", $env:RECOVERY_ACCEPTANCE_TENANT_ID,
    "--expected-release-id", $ReleaseId,
    "--require-build-identity",
    "--report", "phase19-acceptance-report.json"
  )
  if ($RequireBillingFull) { $args += "--require-billing-full" }
  if ($env:RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID) { $args += @("--google-ads-account-id", $env:RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID) }
  if ($RequireGoogleAdsRead) { $args += "--require-google-ads-read" }
  if ($RequireGoogleTestAccount) { $args += "--require-google-test-account" }
  recovery-staging-accept @args
  Assert-NativeSuccess "Deployed acceptance"
} else {
  Write-Warning "Deployment completed, but acceptance was not run because RECOVERY_ACCEPTANCE_TENANT_ID / RECOVERY_ACCEPTANCE_BEARER_TOKEN are not set."
}

Write-Host "Release ID: $ReleaseId"
Write-Host "Image: $ImmutableImage"
Write-Host "API: $ApiUrl"
Write-Host "Dashboard: $DashboardUrl"
