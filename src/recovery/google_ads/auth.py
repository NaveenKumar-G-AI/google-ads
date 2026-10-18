from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .adapter import GOOGLE_ADS_API_VERSION


def normalize_customer_id(value: str) -> str:
    """Return the canonical 10-digit Google Ads customer ID.

    Human-facing Google Ads IDs are often shown as 123-456-7890. API calls require
    digits only. We reject every other shape instead of silently stripping arbitrary
    characters, which avoids accidentally accepting malformed/injected identifiers.
    """

    if not isinstance(value, str):
        raise TypeError("customer ID must be a string")
    stripped = value.strip()
    if stripped.count("-") == 2:
        parts = stripped.split("-")
        if [len(p) for p in parts] != [3, 3, 4] or not all(p.isdigit() for p in parts):
            raise ValueError("customer ID must be 10 digits or XXX-XXX-XXXX")
        stripped = "".join(parts)
    if len(stripped) != 10 or not stripped.isdigit():
        raise ValueError("customer ID must be exactly 10 digits")
    return stripped


@dataclass(frozen=True, slots=True)
class ServiceAccountConfig:
    json_key_file_path: str
    developer_token: str | None = None
    login_customer_id: str | None = None
    use_proto_plus: bool = True

    def __post_init__(self) -> None:
        # Developer tokens were sunset by Google Ads on 2026-09-09.
        # Current API access levels are attached to the Google Cloud project
        # that owns the service account/OAuth credentials. Keep this optional
        # only for backwards compatibility with older deployments/client configs.
        if self.developer_token is not None and not self.developer_token.strip():
            object.__setattr__(self, "developer_token", None)
        path = Path(self.json_key_file_path).expanduser()
        if not path.is_file():
            raise ValueError("json_key_file_path must point to an existing file")
        object.__setattr__(self, "json_key_file_path", str(path.resolve()))
        if self.login_customer_id is not None:
            object.__setattr__(
                self, "login_customer_id", normalize_customer_id(self.login_customer_id)
            )

    def client_configuration(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "json_key_file_path": self.json_key_file_path,
            "use_proto_plus": self.use_proto_plus,
        }
        if self.developer_token is not None:
            config["developer_token"] = self.developer_token
        if self.login_customer_id is not None:
            config["login_customer_id"] = self.login_customer_id
        return config



@dataclass(frozen=True, slots=True)
class UserOAuthConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None
    use_proto_plus: bool = True

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip() or not self.refresh_token.strip():
            raise ValueError("client_id, client_secret and refresh_token are required")
        if self.login_customer_id is not None:
            object.__setattr__(self, "login_customer_id", normalize_customer_id(self.login_customer_id))

    def client_configuration(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "use_proto_plus": self.use_proto_plus,
        }
        if self.login_customer_id is not None:
            config["login_customer_id"] = self.login_customer_id
        return config


def build_user_oauth_client(config: UserOAuthConfig) -> Any:
    """Build a Google Ads v26 client from one customer's multi-user OAuth grant."""
    from google.ads.googleads.client import GoogleAdsClient
    return GoogleAdsClient.load_from_dict(config.client_configuration(), version=GOOGLE_ADS_API_VERSION)

def build_service_account_client(config: ServiceAccountConfig) -> Any:
    """Build a v26 Google Ads client without loading user OAuth credentials.

    Importing GoogleAdsClient lazily keeps domain tests independent of generated Google
    protobuf modules. The service-account JSON contents are never read or copied by this
    package; the official client library opens the file directly.
    """

    from google.ads.googleads.client import GoogleAdsClient

    return GoogleAdsClient.load_from_dict(
        config.client_configuration(), version=GOOGLE_ADS_API_VERSION
    )


def redacted_config_summary(config: ServiceAccountConfig) -> Mapping[str, Any]:
    """Safe metadata for diagnostics; never returns token or key-file contents."""

    return {
        "api_version": GOOGLE_ADS_API_VERSION,
        "auth_flow": "service_account",
        "json_key_file": Path(config.json_key_file_path).name,
        "login_customer_id": config.login_customer_id,
        "use_proto_plus": config.use_proto_plus,
    }
