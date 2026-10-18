-- Phase 19: zero-external-effect deployment acceptance probe

ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
ALTER TABLE recovery.api_jobs
    ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
        'google_ads_sync','analysis_run','apply_negative','rollback_negative',
        'semantic_shadow','deployment_probe'
    ));
