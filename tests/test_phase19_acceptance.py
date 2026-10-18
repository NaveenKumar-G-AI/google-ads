from __future__ import annotations

from pathlib import Path

from recovery.api.jobs import JobType
from recovery.api.policy import Permission, ROLE_PERMISSIONS, TenantRole
from recovery.worker.deployment_probe import DeploymentProbeJobRunner


def test_deployment_probe_is_a_real_job_type_and_admin_only_permission():
    assert JobType.DEPLOYMENT_PROBE.value == "deployment_probe"
    assert Permission.DEPLOYMENT_PROBE in ROLE_PERMISSIONS[TenantRole.ADMIN]
    assert Permission.DEPLOYMENT_PROBE in ROLE_PERMISSIONS[TenantRole.OWNER]
    assert Permission.DEPLOYMENT_PROBE not in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.DEPLOYMENT_PROBE not in ROLE_PERMISSIONS[TenantRole.VIEWER]


def test_probe_runner_has_no_external_effects(monkeypatch):
    monkeypatch.setenv("RECOVERY_RELEASE_ID", "release-123")
    from uuid import uuid4
    r=DeploymentProbeJobRunner()(tenant_id=uuid4(), job_id=uuid4(), payload={"probe":"deployment_round_trip"})
    assert r["probe"] == "ok"
    assert r["release_id"] == "release-123"


def test_phase19_migration_allows_probe_job_type():
    root=Path(__file__).resolve().parents[1]
    sql=(root/'src/recovery/db/migrations/0008_phase19_deployment_probe.sql').read_text()
    assert "'deployment_probe'" in sql


def test_deploy_scripts_pin_release_identity():
    root=Path(__file__).resolve().parents[1]
    api=(root/'deploy/gcloud-api.ps1').read_text()
    worker=(root/'deploy/gcloud-worker.ps1').read_text()
    assert 'RECOVERY_RELEASE_ID=$ReleaseId' in api
    assert 'RECOVERY_RELEASE_ID=$ReleaseId' in worker
    assert '[Parameter(Mandatory=$true)][string]$ReleaseId' in api
    assert '[Parameter(Mandatory=$true)][string]$ReleaseId' in worker


def test_acceptance_module_does_not_import_google_mutation_executor():
    root=Path(__file__).resolve().parents[1]
    src=(root/'src/recovery/acceptance.py').read_text()
    assert 'GoogleAdsNegativeMutationExecutor' not in src
    assert 'google_ads.mutation' not in src

def test_release_script_builds_once_pins_digest_and_runs_acceptance():
    root=Path(__file__).resolve().parents[1]
    src=(root/'deploy/release-staging.ps1').read_text()
    assert 'gcloud builds submit' in src
    assert 'gcloud artifacts docker images describe' in src
    assert '$ImmutableImage = "$ImageBase@$Digest"' in src
    assert 'recovery-migrate' in src
    assert 'gcloud-api.ps1' in src and 'gcloud-worker.ps1' in src
    assert '-Image $ImmutableImage' in src
    assert 'recovery-staging-accept' in src
    assert 'phase19-release-manifest.json' in src


def test_cloud_run_templates_support_staging_and_production_environment():
    root=Path(__file__).resolve().parents[1]
    for name in ('gcloud-api.ps1','gcloud-worker.ps1'):
        src=(root/'deploy'/name).read_text()
        assert 'ValidateSet("staging","production")' in src
        assert 'RECOVERY_ENVIRONMENT=$Environment' in src

def test_api_buildz_and_deployment_probe_endpoint(monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from recovery.api.app import create_app
    from recovery.api.auth import Principal, StaticTokenVerifier
    from recovery.api.jobs import JobReceipt, JobStatus
    from recovery.api.policy import TenantRole
    from recovery.api.repository import Membership

    tenant=uuid4(); user=uuid4()
    class Repo:
        def touch_user(self, *, user_id, email): return True
        def list_memberships(self, *, user_id): return [{"tenant_id":tenant,"role":"admin","status":"active"}]
        def membership(self, *, user_id, tenant_id):
            return Membership(tenant, TenantRole.ADMIN, "active") if user_id==user and tenant_id==tenant else None
        def enqueue_job(self, **kwargs):
            assert kwargs["job_type"] is JobType.DEPLOYMENT_PROBE
            assert kwargs["payload"] == {"probe":"deployment_round_trip"}
            return JobReceipt(uuid4(), JobType.DEPLOYMENT_PROBE, JobStatus.QUEUED)
    principal=Principal(user_id=user,subject=str(user),email="admin@example.test",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
    monkeypatch.setenv("RECOVERY_RELEASE_ID","release-xyz")
    c=TestClient(create_app(repository=Repo(), verifier=StaticTokenVerifier({"token":principal})))
    assert c.get('/buildz').json()["release_id"] == "release-xyz"
    r=c.post(f'/v1/tenants/{tenant}/deployment-probe',headers={"Authorization":"Bearer token","Idempotency-Key":"deploy-probe-1"})
    assert r.status_code == 202
    assert r.json()["job_type"] == "deployment_probe"
