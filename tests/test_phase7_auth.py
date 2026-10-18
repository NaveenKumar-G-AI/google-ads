from pathlib import Path

import pytest

from recovery.google_ads.auth import (
    ServiceAccountConfig,
    normalize_customer_id,
    redacted_config_summary,
)


def test_normalize_customer_id_accepts_google_ui_format_and_digits():
    assert normalize_customer_id("123-456-7890") == "1234567890"
    assert normalize_customer_id("1234567890") == "1234567890"


@pytest.mark.parametrize(
    "value",
    ["123", "123_456_7890", "123-45-67890", "123456789x", " 123 456 7890 "],
)
def test_normalize_customer_id_rejects_noncanonical_shapes(value):
    with pytest.raises(ValueError):
        normalize_customer_id(value)


def test_service_account_config_is_redacted(tmp_path: Path):
    key = tmp_path / "service-account.json"
    key.write_text('{"private_key":"SECRET"}', encoding="utf-8")
    cfg = ServiceAccountConfig(
        json_key_file_path=str(key),
        developer_token="very-secret-token",
        login_customer_id="123-456-7890",
    )
    summary = redacted_config_summary(cfg)
    assert summary["login_customer_id"] == "1234567890"
    assert summary["json_key_file"] == "service-account.json"
    assert "very-secret-token" not in repr(summary)
    assert "SECRET" not in repr(summary)


def test_service_account_config_requires_existing_key_file(tmp_path: Path):
    with pytest.raises(ValueError):
        ServiceAccountConfig(
            json_key_file_path=str(tmp_path / "missing.json"),
            developer_token="x",
        )


def test_service_account_config_does_not_require_legacy_developer_token(tmp_path: Path):
    key = tmp_path / "service-account.json"
    key.write_text('{"private_key":"SECRET"}', encoding="utf-8")
    cfg = ServiceAccountConfig(json_key_file_path=str(key))
    assert cfg.developer_token is None
    assert "developer_token" not in cfg.client_configuration()


def test_service_account_config_keeps_legacy_developer_token_when_supplied(tmp_path: Path):
    key = tmp_path / "service-account.json"
    key.write_text('{"private_key":"SECRET"}', encoding="utf-8")
    cfg = ServiceAccountConfig(json_key_file_path=str(key), developer_token="legacy")
    assert cfg.client_configuration()["developer_token"] == "legacy"
