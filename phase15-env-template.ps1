# Phase 15 staging environment template — DO NOT commit a filled copy.
# Fill values in your current PowerShell session or in a private local copy.

$env:RECOVERY_STAGING_DATABASE_URL="postgresql://..."
# Optional but strongly recommended for real behavioral RLS proof.
$env:RECOVERY_STAGING_APP_DATABASE_URL="postgresql://..."

$env:RECOVERY_STAGING_TENANT_ID="00000000-0000-0000-0000-000000000000"
$env:RECOVERY_STAGING_TENANT_SLUG="phase15-staging"
$env:RECOVERY_STAGING_TENANT_NAME="Phase 15 Staging"
$env:RECOVERY_STAGING_CUSTOMER_ID="1234567890"

$env:GOOGLE_ADS_LOGIN_CUSTOMER_ID="1234567890" # Only when access is through a manager account.
$env:GOOGLE_ADS_JSON_KEY_FILE_PATH="C:\secure\google-ads-service-account.json"
# Developer tokens were sunset on 2026-09-09. Do not set GOOGLE_ADS_DEVELOPER_TOKEN for new setups.

# Prefer setting only the intended Gemini credential variable.
$env:GEMINI_API_KEY="REPLACE_ME"
# $env:GOOGLE_API_KEY="REPLACE_ME"

$env:RECOVERY_PHASE15_READ_ONLY_ACK="READ_ONLY_ONLY"

Write-Host "Environment template loaded. Run Phase-15 preflight next."
