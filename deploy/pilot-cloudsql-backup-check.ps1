param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$Instance,
  [string]$Operator = $env:USERNAME,
  [string]$ReleaseId = "",
  [string]$Output = "deploy/pilot-evidence/backup_configuration.json"
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw "gcloud is required" }
$json = gcloud sql instances describe $Instance --project $ProjectId --format=json | ConvertFrom-Json
$backup = $json.settings.backupConfiguration
$enabled = [bool]$backup.enabled
$pitr = [bool]$backup.pointInTimeRecoveryEnabled
$status = if ($enabled -and $pitr) { "pass" } else { "fail" }
$detail = if ($status -eq "pass") { "Cloud SQL automated backups and point-in-time recovery are enabled." } else { "Cloud SQL backup/PITR configuration is incomplete." }
$evidence = [ordered]@{schema_version="recovery-pilot-evidence.v1";kind="backup_configuration";status=$status;performed_at=(Get-Date).ToUniversalTime().ToString("o");operator=$Operator;detail=$detail;release_id=if ([string]::IsNullOrWhiteSpace($ReleaseId)) {$null}else{$ReleaseId};evidence_refs=@("gcloud sql instances describe $Instance","project:$ProjectId","instance:$Instance")}
$dir=Split-Path -Parent $Output;if($dir){New-Item -ItemType Directory -Force -Path $dir|Out-Null};$evidence|ConvertTo-Json -Depth 6|Set-Content -Encoding UTF8 $Output;$evidence|ConvertTo-Json -Depth 6;if($status-ne"pass"){exit 2}
