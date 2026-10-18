from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import UUID

from recovery.google_ads.adapter import GOOGLE_ADS_API_VERSION, GoogleAdsV26Adapter
from recovery.worker.domain import PermanentWorkerError
from recovery.worker.google_jobs import GoogleAdsClientResolver
from recovery.db.postgres import PostgresRecoveryRepository


class GoogleAdsPilotReadProbeJobRunner:
    """Read-only deployed-provider proof for pilot qualification."""

    def __init__(self, *, core: PostgresRecoveryRepository, client_resolver: GoogleAdsClientResolver) -> None:
        self.core=core
        self.client_resolver=client_resolver

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            account_id=UUID(str(payload["account_id"]))
        except (KeyError,ValueError,TypeError) as exc:
            raise PermanentWorkerError("invalid pilot Google Ads read probe payload",code="BAD_PILOT_PROBE_PAYLOAD") from exc
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""
                SELECT id,customer_id,credential_ref
                FROM recovery.google_ads_accounts
                WHERE tenant_id=%s AND id=%s
            """,(tenant_id,account_id))
            row=cur.fetchone()
            if row is None:
                raise PermanentWorkerError("Google Ads account no longer exists",code="ACCOUNT_NOT_FOUND")
        client=self.client_resolver.client_for(
            tenant_id=tenant_id,credential_ref=row["credential_ref"],customer_id=row["customer_id"]
        )
        adapter=GoogleAdsV26Adapter.from_google_ads_client(client)
        profile=adapter.get_customer_profile(str(row["customer_id"]))
        observed=asdict(profile) if is_dataclass(profile) else dict(profile)
        if str(observed.get("customer_id")) != str(row["customer_id"]):
            raise PermanentWorkerError("Google Ads pilot probe returned a different customer identity",code="GOOGLE_CUSTOMER_IDENTITY_MISMATCH")
        return {
            "probe":"google_ads_read_ok","job_id":str(job_id),"account_id":str(account_id),
            "customer_id":str(observed["customer_id"]),"descriptive_name_present":bool(str(observed.get("descriptive_name") or "").strip()),
            "currency_code":str(observed.get("currency_code") or ""),"time_zone":str(observed.get("time_zone") or ""),
            "manager":bool(observed.get("manager")),"status":str(observed.get("status") or ""),"test_account":bool(observed.get("test_account")),
            "google_ads_api_version":GOOGLE_ADS_API_VERSION,"external_effect":"read_only",
        }
