-- Epic 13: pilot hardening. Adds only the durable read-only Google Ads pilot probe job type.
-- The probe has no Google Ads mutation path and persists only its normal api_jobs result.
ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
ALTER TABLE recovery.api_jobs ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
    'google_ads_sync','analysis_run','apply_negative','rollback_negative','semantic_shadow',
    'deployment_probe','google_ads_account_discovery','monitoring_evaluation','report_generation',
    'pilot_google_ads_read_probe'
));
