param(
  [Parameter(Mandatory=$true)][string]$DatabaseUrl
)
$ErrorActionPreference = "Stop"
$env:DATABASE_URL = $DatabaseUrl
recovery-migrate
if ($LASTEXITCODE -ne 0) { throw "Database migrations failed (exit $LASTEXITCODE)." }
