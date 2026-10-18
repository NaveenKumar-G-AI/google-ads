from pathlib import Path
from recovery.deployment import ProductionReadiness

ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0022_epic14_v1_launch.sql').read_text()
ONBOARDING=(ROOT/'src/recovery/api/onboarding_service.py').read_text()
GATE=(ROOT/'src/recovery/launch_gate.py').read_text()
DEPLOY=(ROOT/'deploy/gcloud-api.ps1').read_text()
WEB=(ROOT/'web/app/(dashboard)/onboarding/page.tsx').read_text()
API=(ROOT/'src/recovery/api/app.py').read_text()


def test_launch_control_and_legal_history_are_append_only():
    for table in ('platform_launch_qualifications','platform_launch_events','platform_launch_access_events','user_legal_acceptance_events'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
    assert "ARRAY['platform_launch_qualifications','platform_launch_events','platform_launch_access_events']" in SQL
    assert 'prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.user_legal_acceptance_events' in SQL


def test_database_validates_qualification_semantics_not_only_boolean():
    assert 'validate_launch_qualification' in SQL
    for required in ("recovery-launch-gate.v1","expected_release_id","jsonb_array_elements","non-pass checks"):
        assert required in SQL
    assert 'validate_public_launch_event' in SQL
    assert "interval '24 hours'" in SQL


def test_legal_acceptance_records_exact_https_urls_and_versions_in_creation_transaction():
    for field in ('terms_url','terms_version','privacy_url','privacy_version','accepted_at'):
        assert field in SQL
    assert "terms_url ~ '^https://" in SQL and "privacy_url ~ '^https://" in SQL
    assert 'INSERT INTO recovery.user_legal_acceptance_events' in ONBOARDING
    assert "'workspace_creation',now()" in ONBOARDING
    assert 'same transaction as workspace creation' in ONBOARDING


def test_legal_acceptance_audit_visibility_is_self_or_narrow_privileged_roles():
    assert "current_platform_operator_role() IN ('platform_admin','security_auditor')" in SQL
    assert 'support_engineer' not in SQL.split('legal_acceptance_self_select',1)[1].split('legal_acceptance_self_insert',1)[0]


def test_public_launch_gate_requires_external_commercial_security_and_abuse_evidence():
    for kind in ('google_ads_production_access','google_oauth_verification','razorpay_live_activation','razorpay_live_webhook','legal_privacy_publication','data_deletion_process','support_oncall','production_security_access_review','production_backup_restore','release_rollback_rehearsal','public_signup_abuse_controls'):
        assert f'"{kind}"' in GATE
    assert 'pilot gate release does not match the V1 launch release' in GATE


def test_production_readiness_requires_policy_version_ids():
    r=ProductionReadiness({'RECOVERY_TERMS_URL':'https://x/terms','RECOVERY_PRIVACY_URL':'https://x/privacy','RECOVERY_DATA_DELETION_URL':'https://x/delete','RECOVERY_SUPPORT_EMAIL':'support@x.com'})
    r._static_config('production');checks={x.name:x for x in r.checks}
    assert checks['public_legal_versions'].status=='fail'
    r=ProductionReadiness({'RECOVERY_TERMS_URL':'https://x/terms','RECOVERY_TERMS_VERSION':'terms-v1','RECOVERY_PRIVACY_URL':'https://x/privacy','RECOVERY_PRIVACY_VERSION':'privacy-v1','RECOVERY_DATA_DELETION_URL':'https://x/delete','RECOVERY_SUPPORT_EMAIL':'support@x.com'})
    r._static_config('production');checks={x.name:x for x in r.checks}
    assert checks['public_legal_versions'].status=='pass'


def test_cloud_run_production_deploy_requires_and_injects_legal_versions():
    for required in ('$TermsVersion','$PrivacyVersion','RECOVERY_TERMS_VERSION=$TermsVersion','RECOVERY_PRIVACY_VERSION=$PrivacyVersion'):
        assert required in DEPLOY
    assert 'Production requires a non-empty TermsVersion' in DEPLOY
    assert 'Production requires a non-empty PrivacyVersion' in DEPLOY


def test_frontend_uses_backend_launch_legal_identity_not_duplicate_next_public_versions():
    assert 'launch.terms_url' in WEB and 'launch.terms_version' in WEB
    assert 'launch.privacy_url' in WEB and 'launch.privacy_version' in WEB
    assert 'NEXT_PUBLIC_TERMS_VERSION' not in WEB and 'NEXT_PUBLIC_PRIVACY_VERSION' not in WEB
    assert 'legal_acceptance_ready' in WEB
    assert 'fails closed rather than recording an ambiguous acceptance' in WEB


def test_api_requires_explicit_legal_acceptance_confirmation():
    models=(ROOT/'src/recovery/api/models.py').read_text()
    actions=(ROOT/'web/app/(dashboard)/onboarding/actions.ts').read_text()
    assert 'legal_acceptance_confirmed: bool = False' in models
    assert 'legal_acceptance_confirmed=body.legal_acceptance_confirmed' in API
    assert 'createOrganization(name,slug,crypto.randomUUID(),accepted,terms,privacy)' in actions
