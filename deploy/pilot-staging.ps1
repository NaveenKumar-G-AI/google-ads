param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$Region,
  [Parameter(Mandatory=$true)][string]$ArtifactRepository,
  [Parameter(Mandatory=$true)][string]$RuntimeServiceAccount,
  [Parameter(Mandatory=$true)][string]$DashboardOrigin,
  [Parameter(Mandatory=$true)][string]$SupabaseUrl,
  [string]$LoginCustomerId = "",
  [string]$DashboardUrl = "",
  [switch]$DeployDashboard
)
$ErrorActionPreference = "Stop"
if (-not $env:RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID) { throw "RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID is required for pilot staging." }
if (-not $env:RECOVERY_ACCEPTANCE_TENANT_ID -or -not $env:RECOVERY_ACCEPTANCE_BEARER_TOKEN) { throw "Pilot staging requires RECOVERY_ACCEPTANCE_TENANT_ID and RECOVERY_ACCEPTANCE_BEARER_TOKEN." }
& "$PSScriptRoot/release-staging.ps1" -ProjectId $ProjectId -Region $Region -ArtifactRepository $ArtifactRepository `
  -RuntimeServiceAccount $RuntimeServiceAccount -DashboardOrigin $DashboardOrigin -SupabaseUrl $SupabaseUrl `
  -LoginCustomerId $LoginCustomerId -Environment staging -DashboardUrl $DashboardUrl `
  -DeployDashboard:$DeployDashboard -RequireBillingFull -RequireGoogleAdsRead -RequireGoogleTestAccount
