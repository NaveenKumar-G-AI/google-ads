param(
  [Parameter(Mandatory=$true)][string]$DatabaseUrl
)
$ErrorActionPreference = "Stop"
$env:DATABASE_URL = $DatabaseUrl
recovery-migrate
