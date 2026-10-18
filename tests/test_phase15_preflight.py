from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recovery.staging_preflight import (
    PreflightConfig,
    PreflightReport,
    PreflightCheck,
    PreflightStatus,
    Phase15Preflight,
    classify_postgres_connection,
)


def test_classify_supabase_direct():
    r=classify_postgres_connection('postgresql://postgres:x@db.abc.supabase.co:5432/postgres')
    assert r.kind == 'supabase_direct'


def test_classify_supabase_session_pooler():
    r=classify_postgres_connection('postgresql://postgres.abc:x@aws-0-us.pooler.supabase.com:5432/postgres')
    assert r.kind == 'supabase_session_pooler'


def test_classify_supabase_transaction_pooler():
    r=classify_postgres_connection('postgresql://postgres.abc:x@aws-0-us.pooler.supabase.com:6543/postgres')
    assert r.kind == 'supabase_transaction_pooler'


def test_report_failed_only_on_fail():
    now=datetime.now(timezone.utc)
    r=PreflightReport(now,now,(PreflightCheck('x',PreflightStatus.WARN,'w'),))
    assert r.failed is False
    r2=PreflightReport(now,now,(PreflightCheck('x',PreflightStatus.FAIL,'f'),))
    assert r2.failed is True


def test_preflight_report_serializes_enum():
    now=datetime.now(timezone.utc)
    r=PreflightReport(now,now,(PreflightCheck('x',PreflightStatus.PASS,'ok',{'n':1}),))
    assert r.to_dict()['checks'][0]['status'] == 'pass'


def _base_config(tmp_path: Path) -> PreflightConfig:
    return PreflightConfig(
        database_url='postgresql://postgres:x@db.abc.supabase.co:5432/postgres',
        app_database_url=None,
        tenant_id='11111111-1111-1111-1111-111111111111',
        tenant_slug='stage', tenant_name='Stage', customer_id='1234567890',
        business_truth_path=None, conversion_lag_days=None,
        run_analysis=False, run_gemini=False,
    )


def test_transaction_pooler_admin_is_fail(monkeypatch, tmp_path):
    monkeypatch.setenv('RECOVERY_PHASE15_READ_ONLY_ACK','READ_ONLY_ONLY')
    cfg=_base_config(tmp_path)
    cfg=PreflightConfig(**{**cfg.__dict__} ) if hasattr(cfg,'__dict__') else PreflightConfig(
        database_url='postgresql://postgres.abc:x@aws-0.pooler.supabase.com:6543/postgres',
        app_database_url=None, tenant_id=cfg.tenant_id, tenant_slug=cfg.tenant_slug,
        tenant_name=cfg.tenant_name, customer_id=cfg.customer_id, business_truth_path=None,
        conversion_lag_days=None, run_analysis=False, run_gemini=False)
    p=Phase15Preflight(cfg); p._database_urls()
    assert any(c.name=='database_admin_url' and c.status is PreflightStatus.FAIL for c in p.checks)


def test_missing_ack_fails(monkeypatch, tmp_path):
    monkeypatch.delenv('RECOVERY_PHASE15_READ_ONLY_ACK', raising=False)
    p=Phase15Preflight(_base_config(tmp_path)); p._read_only_ack()
    assert p.checks[-1].status is PreflightStatus.FAIL


def test_google_key_report_never_contains_private_key(monkeypatch, tmp_path):
    key=tmp_path/'sa.json'
    key.write_text(json.dumps({
        'type':'service_account','project_id':'p','private_key_id':'kid',
        'private_key':'-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\n',
        'client_email':'x@p.iam.gserviceaccount.com'
    }))
    monkeypatch.setenv('GOOGLE_ADS_JSON_KEY_FILE_PATH',str(key))
    p=Phase15Preflight(_base_config(tmp_path)); p._google_credentials()
    rendered=json.dumps([c.evidence for c in p.checks])
    assert 'SECRET' not in rendered
    assert any(c.name=='google_ads_credentials' and c.status is PreflightStatus.PASS for c in p.checks)


def test_gemini_both_keys_warns(monkeypatch, tmp_path):
    monkeypatch.setenv('GEMINI_API_KEY','a')
    monkeypatch.setenv('GOOGLE_API_KEY','b')
    cfg=_base_config(tmp_path)
    cfg=PreflightConfig(
        database_url=cfg.database_url, app_database_url=None, tenant_id=cfg.tenant_id,
        tenant_slug=cfg.tenant_slug, tenant_name=cfg.tenant_name, customer_id=cfg.customer_id,
        business_truth_path=None, conversion_lag_days=None, run_analysis=False, run_gemini=True)
    p=Phase15Preflight(cfg); p._gemini_credentials()
    assert p.checks[-1].status is PreflightStatus.WARN
    assert p.checks[-1].evidence['selected_env']=='GOOGLE_API_KEY'


def test_invalid_customer_id_fails_identity(tmp_path):
    cfg=PreflightConfig(
        database_url='postgresql://x', app_database_url=None,
        tenant_id='11111111-1111-1111-1111-111111111111', tenant_slug='s', tenant_name='n',
        customer_id='123', business_truth_path=None, conversion_lag_days=None,
        run_analysis=False, run_gemini=False)
    p=Phase15Preflight(cfg); p._tenant_inputs()
    assert p.checks[-1].status is PreflightStatus.FAIL


def test_google_key_preflight_passes_without_legacy_developer_token(monkeypatch, tmp_path):
    key=tmp_path/'sa.json'
    key.write_text(json.dumps({
        'type':'service_account','project_id':'p','private_key_id':'kid',
        'private_key':'-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\n',
        'client_email':'x@p.iam.gserviceaccount.com'
    }))
    monkeypatch.delenv('GOOGLE_ADS_DEVELOPER_TOKEN', raising=False)
    monkeypatch.setenv('GOOGLE_ADS_JSON_KEY_FILE_PATH',str(key))
    p=Phase15Preflight(_base_config(tmp_path)); p._google_credentials()
    assert any(c.name=='google_ads_credentials' and c.status is PreflightStatus.PASS for c in p.checks)
    assert not any(c.name=='google_ads_developer_token_legacy' for c in p.checks)


def test_google_key_preflight_warns_if_legacy_developer_token_is_still_set(monkeypatch, tmp_path):
    key=tmp_path/'sa.json'
    key.write_text(json.dumps({
        'type':'service_account','project_id':'p','private_key_id':'kid',
        'private_key':'-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\n',
        'client_email':'x@p.iam.gserviceaccount.com'
    }))
    monkeypatch.setenv('GOOGLE_ADS_DEVELOPER_TOKEN','legacy-secret')
    monkeypatch.setenv('GOOGLE_ADS_JSON_KEY_FILE_PATH',str(key))
    p=Phase15Preflight(_base_config(tmp_path)); p._google_credentials()
    rendered=json.dumps([c.evidence for c in p.checks])
    assert 'legacy-secret' not in rendered
    assert any(c.name=='google_ads_developer_token_legacy' and c.status is PreflightStatus.WARN for c in p.checks)
