from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from recovery.db.canonical import canonical_payload, payload_sha256
from recovery.staging_validation import (
    CheckStatus,
    StagingConfig,
    ValidationCheck,
    ValidationReport,
    redact_dsn,
    verify_audit_chain_rows,
)


def test_redact_dsn_removes_password_and_query():
    text = redact_dsn("postgresql://alice:secret@db.example.com:5432/postgres?sslmode=require")
    assert "secret" not in text
    assert "sslmode" not in text
    assert "alice:***@db.example.com:5432" in text


def test_validation_report_fails_only_on_fail():
    now = datetime.now(timezone.utc)
    report = ValidationReport(
        "run", now, now,
        (
            ValidationCheck("a", CheckStatus.PASS, "ok"),
            ValidationCheck("b", CheckStatus.WARN, "warn"),
            ValidationCheck("c", CheckStatus.SKIP, "skip"),
        ),
    )
    assert report.failed is False
    report2 = ValidationReport("run2", now, now, report.checks + (ValidationCheck("d", CheckStatus.FAIL, "bad"),))
    assert report2.failed is True


def test_validation_report_fingerprint_changes_with_result():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    a = ValidationReport("x", now, now, (ValidationCheck("a", CheckStatus.PASS, "ok"),))
    b = ValidationReport("x", now, now, (ValidationCheck("a", CheckStatus.FAIL, "bad"),))
    assert a.fingerprint_sha256 != b.fingerprint_sha256


def test_staging_config_requires_truth_for_analysis():
    with pytest.raises(ValueError, match="business_truth_path"):
        StagingConfig(
            database_url="postgresql://x",
            tenant_id=uuid4(), tenant_slug="s", tenant_name="n", customer_id="1234567890",
            start=datetime(2026,1,1).date(), end=datetime(2026,1,2).date(),
            conversion_lag_days=7, run_analysis=True, run_gemini=False,
        )


def test_staging_config_requires_conversion_lag_for_analysis(tmp_path):
    p=tmp_path/"truth.json"; p.write_text("{}")
    with pytest.raises(ValueError, match="conversion_lag_days"):
        StagingConfig(
            database_url="postgresql://x", tenant_id=uuid4(), tenant_slug="s", tenant_name="n",
            customer_id="1234567890", start=datetime(2026,1,1).date(), end=datetime(2026,1,2).date(),
            business_truth_path=p, run_analysis=True, run_gemini=False,
        )


def test_staging_config_can_skip_truth_dependent_checks():
    cfg = StagingConfig(
        database_url="postgresql://x", tenant_id=uuid4(), tenant_slug="s", tenant_name="n",
        customer_id="1234567890", start=datetime(2026,1,1).date(), end=datetime(2026,1,2).date(),
        run_analysis=False, run_gemini=False,
    )
    assert cfg.business_truth_path is None


def _audit_rows():
    tenant=uuid4(); occurred=datetime(2026,10,15,12,0,tzinfo=timezone.utc)
    base=[]; previous=None
    for i in range(2):
        body={
            "tenant_id":tenant,
            "aggregate_type":"phase15",
            "aggregate_id":"run",
            "event_type":f"e{i}",
            "actor":"tester",
            "occurred_at":occurred,
            "previous_event_hash":previous,
            "payload":{"i":i},
        }
        event_hash=payload_sha256(body)
        row=dict(body); row["event_hash"]=event_hash
        base.append(row); previous=event_hash
    return base


def test_verify_audit_chain_rows_accepts_valid_chain():
    ok, reason = verify_audit_chain_rows(_audit_rows())
    assert ok is True and reason is None


def test_verify_audit_chain_rows_rejects_broken_previous_hash():
    rows=_audit_rows(); rows[1]["previous_event_hash"]="0"*64
    ok, reason = verify_audit_chain_rows(rows)
    assert ok is False and "previous_event_hash" in reason


def test_verify_audit_chain_rows_rejects_tampered_payload():
    rows=_audit_rows(); rows[0]["payload"]={"i":999}
    ok, reason = verify_audit_chain_rows(rows)
    assert ok is False and "event_hash" in reason


def test_report_serialization_contains_no_enum_objects():
    now=datetime.now(timezone.utc)
    r=ValidationReport("x",now,now,(ValidationCheck("a",CheckStatus.PASS,"ok",{"x":1}),))
    encoded=r.to_dict()
    assert encoded["checks"][0]["status"] == "pass"
    assert isinstance(encoded["fingerprint_sha256"], str)
