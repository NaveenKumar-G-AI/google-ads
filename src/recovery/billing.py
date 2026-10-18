from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import base64
import hashlib
import hmac
import json
import os
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from uuid import UUID


class BillingError(RuntimeError):
    pass


class BillingProviderError(BillingError):
    pass


class BillingAccessError(BillingError):
    pass


class BillingWebhookAuthError(BillingError):
    pass


class CheckoutAmbiguousError(BillingError):
    pass


class BillingMutationAmbiguousError(BillingError):
    pass


class EntitlementState(str, Enum):
    FULL = "full"
    GRACE = "grace"
    BILLING_PENDING = "billing_pending"
    READ_ONLY = "read_only"
    UNSUBSCRIBED = "unsubscribed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class BillingPlan:
    key: str
    display_name: str
    provider_plan_id: str
    currency: str
    amount_subunits: int
    total_count: int
    max_google_ads_accounts: int
    max_sync_range_days: int

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 64:
            raise ValueError("billing plan key must be 1..64 characters")
        if not self.provider_plan_id.startswith("plan_"):
            raise ValueError("Razorpay provider_plan_id must start with plan_")
        if self.amount_subunits <= 0 or self.total_count <= 0:
            raise ValueError("billing plan amount/total_count must be positive")
        if self.max_google_ads_accounts <= 0 or self.max_sync_range_days <= 0:
            raise ValueError("billing plan limits must be positive")

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "currency": self.currency,
            "amount_subunits": self.amount_subunits,
            "max_google_ads_accounts": self.max_google_ads_accounts,
            "max_sync_range_days": self.max_sync_range_days,
        }


class BillingPlanCatalog:
    def __init__(self, plans: list[BillingPlan]) -> None:
        if not plans:
            raise ValueError("at least one billing plan is required")
        self._by_key: dict[str, BillingPlan] = {}
        self._by_provider: dict[str, BillingPlan] = {}
        for plan in plans:
            if plan.key in self._by_key or plan.provider_plan_id in self._by_provider:
                raise ValueError("duplicate billing plan key/provider id")
            self._by_key[plan.key] = plan
            self._by_provider[plan.provider_plan_id] = plan

    @classmethod
    def from_json(cls, raw: str) -> "BillingPlanCatalog":
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("BILLING_PLANS_JSON must be valid JSON") from exc
        if not isinstance(obj, list):
            raise ValueError("BILLING_PLANS_JSON must be an array")
        plans = []
        for item in obj:
            if not isinstance(item, dict):
                raise ValueError("each billing plan must be an object")
            plans.append(BillingPlan(
                key=str(item["key"]), display_name=str(item["display_name"]),
                provider_plan_id=str(item["provider_plan_id"]),
                currency=str(item.get("currency", "INR")).upper(),
                amount_subunits=int(item["amount_subunits"]),
                total_count=int(item["total_count"]),
                max_google_ads_accounts=int(item["max_google_ads_accounts"]),
                max_sync_range_days=int(item["max_sync_range_days"]),
            ))
        return cls(plans)

    @classmethod
    def from_env(cls) -> "BillingPlanCatalog":
        raw = os.environ.get("BILLING_PLANS_JSON", "").strip()
        if not raw:
            raise RuntimeError("BILLING_PLANS_JSON is required when billing is enabled")
        return cls.from_json(raw)

    def get(self, key: str) -> BillingPlan:
        try:
            return self._by_key[key]
        except KeyError as exc:
            raise BillingAccessError("unknown billing plan") from exc

    def by_provider_plan_id(self, provider_plan_id: str) -> BillingPlan:
        try:
            return self._by_provider[provider_plan_id]
        except KeyError as exc:
            raise BillingAccessError("provider subscription uses an unmapped plan") from exc

    def public_plans(self) -> list[dict[str, Any]]:
        return [self._by_key[k].public_dict() for k in sorted(self._by_key)]


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    id: str
    plan_id: str
    status: str
    short_url: str | None
    current_start: datetime | None
    current_end: datetime | None
    quantity: int
    notes: dict[str, Any]
    customer_id: str | None = None
    payment_method: str | None = None
    total_count: int | None = None
    paid_count: int | None = None
    remaining_count: int | None = None
    has_scheduled_changes: bool = False
    change_scheduled_at: datetime | None = None
    charge_at: datetime | None = None
    ended_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderInvoice:
    id: str
    subscription_id: str
    payment_id: str | None
    status: str
    currency: str
    amount: int
    amount_paid: int
    amount_due: int
    issued_at: datetime | None
    paid_at: datetime | None
    raw: dict[str, Any]


def _unix_dt(value: Any) -> datetime | None:
    if value in (None, 0, ""):
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def parse_provider_subscription(obj: dict[str, Any]) -> ProviderSubscription:
    sid = str(obj.get("id", ""))
    plan_id = str(obj.get("plan_id", ""))
    status = str(obj.get("status", "")).lower()
    if not sid.startswith("sub_") or not plan_id.startswith("plan_") or not status:
        raise BillingProviderError("Razorpay subscription response is missing required identity fields")
    notes = obj.get("notes") or {}
    if not isinstance(notes, dict):
        notes = {}
    return ProviderSubscription(
        id=sid, plan_id=plan_id, status=status,
        short_url=str(obj["short_url"]) if obj.get("short_url") else None,
        current_start=_unix_dt(obj.get("current_start")),
        current_end=_unix_dt(obj.get("current_end")),
        quantity=int(obj.get("quantity") or 1),
        notes=dict(notes),
        customer_id=str(obj["customer_id"]) if obj.get("customer_id") else None,
        payment_method=str(obj["payment_method"]).lower() if obj.get("payment_method") else None,
        total_count=int(obj["total_count"]) if obj.get("total_count") is not None else None,
        paid_count=int(obj["paid_count"]) if obj.get("paid_count") is not None else None,
        remaining_count=int(obj["remaining_count"]) if obj.get("remaining_count") is not None else None,
        has_scheduled_changes=bool(obj.get("has_scheduled_changes", False)),
        change_scheduled_at=_unix_dt(obj.get("change_scheduled_at")),
        charge_at=_unix_dt(obj.get("charge_at")),
        ended_at=_unix_dt(obj.get("ended_at")),
        raw=dict(obj),
    )


def parse_provider_invoice(obj: dict[str, Any], *, expected_subscription_id: str) -> ProviderInvoice:
    iid=str(obj.get("id", "")); sid=str(obj.get("subscription_id", ""))
    if not iid.startswith("inv_") or sid != expected_subscription_id:
        raise BillingProviderError("Razorpay invoice response has invalid subscription identity")
    currency=str(obj.get("currency") or "").upper()
    if len(currency)!=3:
        raise BillingProviderError("Razorpay invoice response has invalid currency")
    amount=int(obj.get("amount") or 0); paid=int(obj.get("amount_paid") or 0); due=int(obj.get("amount_due") or 0)
    if min(amount,paid,due)<0:
        raise BillingProviderError("Razorpay invoice response has invalid amount")
    return ProviderInvoice(
        id=iid,subscription_id=sid,payment_id=str(obj["payment_id"]) if obj.get("payment_id") else None,
        status=str(obj.get("status") or "unknown").lower(),currency=currency,amount=amount,amount_paid=paid,amount_due=due,
        issued_at=_unix_dt(obj.get("issued_at") or obj.get("date") or obj.get("created_at")),
        paid_at=_unix_dt(obj.get("paid_at")),raw=dict(obj),
    )


def entitlement_for_status(status: str) -> EntitlementState:
    normalized = status.strip().lower()
    if normalized == "active":
        return EntitlementState.FULL
    if normalized in {"created", "authenticated", "pending"}:
        return EntitlementState.BILLING_PENDING
    if normalized in {"paused", "halted", "cancelled", "completed", "expired"}:
        return EntitlementState.READ_ONLY
    return EntitlementState.BLOCKED


class BillingProvider(Protocol):
    def fetch_plan(self, plan_id: str) -> dict[str, Any]: ...
    def create_subscription(self, *, plan: BillingPlan, tenant_id: UUID,
                            checkout_intent_id: UUID) -> ProviderSubscription: ...
    def fetch_subscription(self, subscription_id: str) -> ProviderSubscription: ...
    def update_subscription_plan(self, *, subscription_id: str, plan_id: str, schedule_change_at: str) -> ProviderSubscription: ...
    def fetch_pending_update(self, subscription_id: str) -> ProviderSubscription: ...
    def cancel_scheduled_update(self, subscription_id: str) -> ProviderSubscription: ...
    def cancel_subscription(self, *, subscription_id: str, cancel_at_cycle_end: bool) -> ProviderSubscription: ...
    def fetch_subscription_invoices(self, subscription_id: str) -> list[ProviderInvoice]: ...


class RazorpayProvider:
    """Minimal server-only Razorpay Subscriptions adapter.

    Uses Basic Auth and intentionally does not depend on a browser SDK. The API secret
    must never be exposed to the web frontend.
    """
    def __init__(self, *, key_id: str, key_secret: str,
                 base_url: str = "https://api.razorpay.com/v1", timeout_seconds: int = 20) -> None:
        if not key_id or not key_secret:
            raise ValueError("Razorpay key id/secret are required")
        self.key_id = key_id
        self.key_secret = key_secret
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "RazorpayProvider":
        key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
        if not key_id or not key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required")
        return cls(key_id=key_id, key_secret=key_secret)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, ambiguous_on_transport: bool = False) -> dict[str, Any]:
        raw = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        req = Request(
            f"{self.base_url}{path}", data=raw, method=method,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except HTTPError as exc:
            safe = exc.read(4096).decode("utf-8", "replace")
            if ambiguous_on_transport and (exc.code >= 500 or exc.code in {408, 429}):
                raise CheckoutAmbiguousError(f"Razorpay API HTTP {exc.code}; create outcome may be uncertain") from exc
            raise BillingProviderError(f"Razorpay API HTTP {exc.code}: {safe}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if ambiguous_on_transport:
                raise CheckoutAmbiguousError("Razorpay create outcome is unknown due to transport failure") from exc
            raise BillingProviderError("Razorpay API is temporarily unavailable") from exc
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            if ambiguous_on_transport:
                raise CheckoutAmbiguousError("Razorpay create may have succeeded but returned invalid JSON") from exc
            raise BillingProviderError("Razorpay returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            if ambiguous_on_transport:
                raise CheckoutAmbiguousError("Razorpay create may have succeeded but returned an unexpected response")
            raise BillingProviderError("Razorpay returned unexpected response shape")
        return parsed

    def fetch_plan(self, plan_id: str) -> dict[str, Any]:
        if not plan_id.startswith("plan_"):
            raise ValueError("invalid Razorpay plan id")
        return self._request("GET", f"/plans/{plan_id}")

    def create_subscription(self, *, plan: BillingPlan, tenant_id: UUID,
                            checkout_intent_id: UUID) -> ProviderSubscription:
        obj = self._request("POST", "/subscriptions", {
            "plan_id": plan.provider_plan_id,
            "total_count": plan.total_count,
            "quantity": 1,
            "customer_notify": 1,
            "notes": {
                "recovery_tenant_id": str(tenant_id),
                "recovery_checkout_intent_id": str(checkout_intent_id),
                "recovery_plan_key": plan.key,
            },
        }, ambiguous_on_transport=True)
        try:
            return parse_provider_subscription(obj)
        except BillingProviderError as exc:
            raise CheckoutAmbiguousError("Razorpay subscription may exist but response identity was invalid") from exc

    def fetch_subscription(self, subscription_id: str) -> ProviderSubscription:
        if not subscription_id.startswith("sub_"):
            raise ValueError("invalid Razorpay subscription id")
        return parse_provider_subscription(self._request("GET", f"/subscriptions/{subscription_id}"))

    def _mutation_subscription(self, method: str, path: str, body: dict[str, Any] | None = None) -> ProviderSubscription:
        try:
            obj=self._request(method,path,body,ambiguous_on_transport=True)
        except CheckoutAmbiguousError as exc:
            raise BillingMutationAmbiguousError(str(exc).replace("create outcome", "provider mutation outcome")) from exc
        try:
            return parse_provider_subscription(obj)
        except BillingProviderError as exc:
            raise BillingMutationAmbiguousError("Razorpay mutation may have succeeded but returned invalid subscription identity") from exc

    def update_subscription_plan(self, *, subscription_id: str, plan_id: str, schedule_change_at: str) -> ProviderSubscription:
        if not subscription_id.startswith("sub_") or not plan_id.startswith("plan_"):
            raise ValueError("invalid Razorpay subscription/plan id")
        if schedule_change_at not in {"now","cycle_end"}:
            raise ValueError("schedule_change_at must be now or cycle_end")
        return self._mutation_subscription("PATCH",f"/subscriptions/{subscription_id}",{"plan_id":plan_id,"schedule_change_at":schedule_change_at,"customer_notify":1})

    def fetch_pending_update(self, subscription_id: str) -> ProviderSubscription:
        if not subscription_id.startswith("sub_"):
            raise ValueError("invalid Razorpay subscription id")
        return parse_provider_subscription(self._request("GET",f"/subscriptions/{subscription_id}/retrieve_scheduled_changes"))

    def cancel_scheduled_update(self, subscription_id: str) -> ProviderSubscription:
        if not subscription_id.startswith("sub_"):
            raise ValueError("invalid Razorpay subscription id")
        return self._mutation_subscription("POST",f"/subscriptions/{subscription_id}/cancel_scheduled_changes",{})

    def cancel_subscription(self, *, subscription_id: str, cancel_at_cycle_end: bool) -> ProviderSubscription:
        if not subscription_id.startswith("sub_"):
            raise ValueError("invalid Razorpay subscription id")
        return self._mutation_subscription("POST",f"/subscriptions/{subscription_id}/cancel",{"cancel_at_cycle_end":bool(cancel_at_cycle_end)})

    def fetch_subscription_invoices(self, subscription_id: str) -> list[ProviderInvoice]:
        if not subscription_id.startswith("sub_"):
            raise ValueError("invalid Razorpay subscription id")
        # Razorpay supports count/skip; page until the provider returns less than 100.
        out:list[ProviderInvoice]=[]; skip=0
        while True:
            query=urlencode({"subscription_id":subscription_id,"count":100,"skip":skip})
            obj=self._request("GET",f"/invoices?{query}")
            items=obj.get("items") or obj.get("item") or []
            if not isinstance(items,list):
                raise BillingProviderError("Razorpay invoices response is not a collection")
            page=[parse_provider_invoice(x,expected_subscription_id=subscription_id) for x in items if isinstance(x,dict)]
            out.extend(page)
            if len(items)<100:
                break
            skip += len(items)
            if skip>10000:
                raise BillingProviderError("Razorpay invoices pagination exceeded safety limit")
        return out


def verify_razorpay_webhook(*, raw_body: bytes, signature: str, secret: str) -> None:
    if not secret:
        raise RuntimeError("RAZORPAY_WEBHOOK_SECRET is not configured")
    if not signature:
        raise BillingWebhookAuthError("missing Razorpay webhook signature")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        raise BillingWebhookAuthError("invalid Razorpay webhook signature")


def safe_webhook_event_id(*, raw_body: bytes, header_event_id: str | None) -> str:
    value = (header_event_id or "").strip()
    if value:
        if len(value) > 200:
            raise BillingAccessError("Razorpay event id is too long")
        return value
    # Some delivery contexts may omit an event id. Raw-body digest still gives exact
    # duplicate suppression without trusting JSON field ordering.
    return "sha256:" + hashlib.sha256(raw_body).hexdigest()
