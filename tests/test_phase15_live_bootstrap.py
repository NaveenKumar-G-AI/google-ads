from argparse import Namespace
from pathlib import Path

import pytest

import recovery.staging_live as live
from recovery.staging_preflight import PreflightCheck, PreflightReport, PreflightStatus
from datetime import datetime, timezone


def args(tmp_path: Path, **overrides):
    data = dict(
        start="2026-10-01",
        end="2026-10-07",
        business_truth=None,
        conversion_lag_days=14,
        gemini_sample_size=5,
        skip_analysis=False,
        skip_gemini=False,
        no_replay_probe=False,
        no_apply_migrations=False,
        non_interactive=True,
        report_dir=str(tmp_path / "reports"),
    )
    data.update(overrides)
    return Namespace(**data)


def seed_required_env(monkeypatch, tmp_path: Path):
    key = tmp_path / "service-account.json"
    key.write_text("{}", encoding="utf-8")
    truth = tmp_path / "truth.json"
    truth.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RECOVERY_STAGING_DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.setenv("RECOVERY_STAGING_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("RECOVERY_STAGING_TENANT_SLUG", "phase15-staging")
    monkeypatch.setenv("RECOVERY_STAGING_TENANT_NAME", "Phase 15 Staging")
    monkeypatch.setenv("RECOVERY_STAGING_CUSTOMER_ID", "1234567890")
    monkeypatch.setenv("GOOGLE_ADS_JSON_KEY_FILE_PATH", str(key))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("RECOVERY_STAGING_BUSINESS_TRUTH_PATH", str(truth))
    return truth


def test_noninteractive_collection_uses_environment_without_developer_token(monkeypatch, tmp_path):
    truth = seed_required_env(monkeypatch, tmp_path)
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    result = live._collect_environment(args(tmp_path))
    assert result == truth.resolve()
    assert live.os.environ["RECOVERY_PHASE15_READ_ONLY_ACK"] == "READ_ONLY_ONLY"
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" not in live.os.environ


def test_noninteractive_collection_fails_when_required_database_url_missing(monkeypatch, tmp_path):
    seed_required_env(monkeypatch, tmp_path)
    monkeypatch.delenv("RECOVERY_STAGING_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="RECOVERY_STAGING_DATABASE_URL"):
        live._collect_environment(args(tmp_path))


def test_skip_analysis_and_gemini_does_not_require_business_truth_or_gemini(monkeypatch, tmp_path):
    seed_required_env(monkeypatch, tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("RECOVERY_STAGING_BUSINESS_TRUTH_PATH", raising=False)
    result = live._collect_environment(args(tmp_path, skip_analysis=True, skip_gemini=True, conversion_lag_days=None))
    assert result is None


def test_preflight_failure_stops_before_staging(monkeypatch, tmp_path):
    seed_required_env(monkeypatch, tmp_path)
    started = datetime(2026, 10, 15, tzinfo=timezone.utc)
    fake_report = PreflightReport(
        started,
        started,
        (PreflightCheck("google_ads_live", PreflightStatus.FAIL, "denied"),),
    )

    class FakePreflight:
        def __init__(self, config):
            self.config = config
        def run(self):
            self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.report_path.write_text("{}", encoding="utf-8")
            return fake_report

    class MustNotStart:
        def __init__(self, config):
            raise AssertionError("staging validator must not start after failed preflight")

    monkeypatch.setattr(live, "Phase15Preflight", FakePreflight)
    monkeypatch.setattr(live, "Phase15StagingValidator", MustNotStart)
    result = live.run_live_bootstrap(args(tmp_path))
    assert result.preflight_failed is True
    assert result.staging_report is None
    assert result.exit_code == 2


def test_powershell_wrapper_never_mentions_developer_token():
    root = Path(__file__).resolve().parents[1]
    text = (root / "run-phase15-live.ps1").read_text(encoding="utf-8")
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" not in text
    assert "examples_phase15_live.py" in text
