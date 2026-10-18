from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from recovery.billing import (
    BillingAccessError,
    BillingPlanCatalog,
    BillingProvider,
    BillingProviderError,
    CheckoutAmbiguousError,
    BillingMutationAmbiguousError,
    EntitlementState,
    entitlement_for_status,
    safe_webhook_event_id,
    verify_razorpay_webhook,
)

from .idempotency import validate_idempotency_key
from .policy import Permission, TenantAccess
from .repository import ApiConflict, ApiRepository


@dataclass(frozen=True, slots=True)
class BillingRuntime:
    provider: BillingProvider
    catalog: BillingPlanCatalog
    webhook_secret: str
    grace_hours: int = 0

    def __post_init__(self) -> None:
        if self.grace_hours < 0 or self.grace_hours > 24 * 30:
            raise ValueError("billing grace_hours must be between 0 and 720")


class BillingApplicationService:
    def __init__(self, *, repository: ApiRepository, runtime: BillingRuntime | None) -> None:
        self.repo = repository
        self.runtime = runtime

    @property
    def enabled(self) -> bool:
        return self.runtime is not None

    def _require_provider_mutations_enabled(self, tenant_id: UUID) -> None:
        gate=getattr(self.repo,"internal_feature_enabled",None)
        if gate is not None and not gate(tenant_id=tenant_id,feature_key="billing_mutations"):
            raise BillingAccessError("billing provider mutations are temporarily disabled by a platform operational control")

    def public_plans(self) -> list[dict[str, Any]]:
        if self.runtime is None:
            return []
        verified: list[dict[str, Any]] = []
        for item in self.runtime.catalog.public_plans():
            plan = self.runtime.catalog.get(str(item["key"]))
            provider_plan = self.runtime.provider.fetch_plan(plan.provider_plan_id)
            provider_item = provider_plan.get("item") or {}
            amount = int(provider_item.get("amount") or provider_item.get("unit_amount") or 0)
            currency = str(provider_item.get("currency") or "").upper()
            if amount != plan.amount_subunits or currency != plan.currency:
                raise BillingProviderError("configured billing catalog does not match Razorpay plan pricing")
            verified.append(item)
        return verified

    def status(self, *, access: TenantAccess) -> dict[str, Any]:
        access.require(Permission.BILLING_READ)
        current_fn=getattr(self.repo,"billing_current",None)
        row=current_fn(tenant_id=access.tenant_id) if current_fn else None
        base={
            "enabled":self.enabled,"plan_key":None,"provider_status":None,"entitlement_state":EntitlementState.UNSUBSCRIBED.value,
            "current_start":None,"current_end":None,"provider_subscription_id":None,"payment_method":None,"grace_until":None,
            "has_scheduled_changes":False,"pending_plan_key":None,"pending_plan_effective_at":None,
            "cancellation_scheduled":False,"cancellation_effective_at":None,"account_slots":[],"billing_profile":None,
        }
        if row is not None:
            # Never expose the entire mutable billing projection through the API. Keep
            # provider/internal fields explicit so future schema additions fail closed.
            for key in ("plan_key","provider_status","entitlement_state","current_start","current_end","provider_subscription_id","payment_method","grace_until","has_scheduled_changes"):
                if key in row: base[key]=row.get(key)
        profile_fn=getattr(self.repo,"billing_profile",None)
        if profile_fn: base["billing_profile"]=profile_fn(tenant_id=access.tenant_id)
        slots_fn=getattr(self.repo,"list_billing_account_slots",None)
        if slots_fn: base["account_slots"]=slots_fn(tenant_id=access.tenant_id)
        if row is not None and row.get("provider_subscription_id"):
            sid=str(row["provider_subscription_id"])
            if bool(row.get("has_scheduled_changes")):
                pending_fn=getattr(self.repo,"latest_billing_pending_change",None)
                pending=pending_fn(tenant_id=access.tenant_id,subscription_id=sid) if pending_fn else None
                if pending:
                    base["pending_plan_key"]=pending.get("target_plan_key")
                    base["pending_plan_effective_at"]=row.get("change_scheduled_at") or row.get("current_end")
            ops_fn=getattr(self.repo,"latest_billing_lifecycle_operations",None)
            ops=ops_fn(tenant_id=access.tenant_id,provider_subscription_id=sid,limit=50) if ops_fn else []
            terminal={"cancelled","completed","expired"}
            if str(row.get("provider_status") or "").lower() not in terminal:
                for op in ops:
                    if op.get("operation_type")=="cancel_cycle_end" and op.get("state") in {"provider_observed","reconciled"}:
                        base["cancellation_scheduled"]=True
                        base["cancellation_effective_at"]=op.get("effective_at") or row.get("current_end")
                        break
        return base

    def require_full(self, *, access: TenantAccess, capability: str,
                     account_id: UUID | None = None, sync_start: date | None = None,
                     sync_end: date | None = None, reserve_account: bool = False) -> None:
        """Fail closed only when billing is explicitly enabled.

        Legacy/offline tests that construct create_app() without billing runtime keep working;
        production create_app_from_env() enables this gate when BILLING_ENABLED=true.
        """
        if self.runtime is None:
            return
        current = self.repo.billing_current(tenant_id=access.tenant_id)
        if current is None or current.get("entitlement_state") not in {EntitlementState.FULL.value,EntitlementState.GRACE.value}:
            raise BillingAccessError(f"active subscription required for {capability}")
        if current.get("entitlement_state")==EntitlementState.GRACE.value:
            grace_until=current.get("grace_until")
            if grace_until is None or grace_until<=datetime.now(timezone.utc):
                raise BillingAccessError("billing grace period has ended; payment recovery is required")
        plan = self.runtime.catalog.get(str(current["plan_key"]))
        current_end = current.get("current_end")
        if current_end is not None and current_end <= datetime.now(timezone.utc):
            raise BillingAccessError("subscription period has ended; reconcile billing before starting new work")
        if sync_start is not None and sync_end is not None:
            days = (sync_end - sync_start).days + 1
            if days <= 0:
                raise ValueError("sync date range is invalid")
            if days > plan.max_sync_range_days:
                raise BillingAccessError(
                    f"billing plan allows at most {plan.max_sync_range_days} days per sync"
                )
        if account_id is not None:
            if reserve_account:
                self.repo.reserve_billing_account_slot(
                    tenant_id=access.tenant_id, account_id=account_id,
                    max_accounts=plan.max_google_ads_accounts,
                )
            else:
                checker = getattr(self.repo, "billing_account_slot_allowed", None)
                if checker is not None and not checker(
                    tenant_id=access.tenant_id, account_id=account_id,
                    max_accounts=plan.max_google_ads_accounts,
                ):
                    raise BillingAccessError("Google Ads account is not active within the current billing plan slots")

    def account_selection_limit(self, *, access: TenantAccess) -> int | None:
        """Return the paid account limit for onboarding, or None when billing is disabled.

        Account selection is a value-producing entitlement boundary just like sync. We
        fail closed when billing is enabled but no active reconciled subscription exists,
        and expose only the numeric limit—not provider secrets or checkout internals.
        """
        if self.runtime is None:
            return None
        access.require(Permission.TENANT_READ)
        current = self.repo.billing_current(tenant_id=access.tenant_id)
        if current is None or current.get("entitlement_state") not in {EntitlementState.FULL.value,EntitlementState.GRACE.value}:
            raise BillingAccessError("active subscription required for Google Ads account selection")
        if current.get("entitlement_state")==EntitlementState.GRACE.value:
            grace_until=current.get("grace_until")
            if grace_until is None or grace_until<=datetime.now(timezone.utc):
                raise BillingAccessError("billing grace period has ended; payment recovery is required")
        current_end = current.get("current_end")
        if current_end is not None and current_end <= datetime.now(timezone.utc):
            raise BillingAccessError("subscription period has ended; reconcile billing before selecting accounts")
        plan = self.runtime.catalog.get(str(current["plan_key"]))
        return plan.max_google_ads_accounts

    def start_checkout(self, *, access: TenantAccess, plan_key: str,
                       idempotency_key: str, endpoint: str) -> dict[str, Any]:
        self._require_provider_mutations_enabled(access.tenant_id)
        if self.runtime is None:
            raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE)
        key = validate_idempotency_key(idempotency_key)
        plan = self.runtime.catalog.get(plan_key)

        existing_lookup = getattr(self.repo, "billing_checkout_by_request", None)
        existing = existing_lookup(
            tenant_id=access.tenant_id, user_id=access.principal.user_id, idempotency_key=key
        ) if existing_lookup is not None else None
        if existing is not None:
            if str(existing.get("plan_key")) != plan.key:
                raise ApiConflict("Idempotency-Key was already used with a different billing plan")
            state = str(existing.get("state"))
            if state == "provider_created":
                return {
                    "checkout_intent_id": existing["id"], "plan_key": plan.key,
                    "provider_subscription_id": existing["provider_subscription_id"],
                    "checkout_url": existing.get("checkout_url"), "state": state,
                    "idempotency_replay": True,
                }
            if state in {"in_flight", "ambiguous"}:
                raise ApiConflict("billing checkout outcome is ambiguous; do not retry with a new key until reconciled")
            if state == "failed":
                raise ApiConflict("billing checkout failed; start a new checkout with a new idempotency key")
            # 'prepared' is safe to continue: provider create is only called after the
            # durable state transitions to in_flight.

        current = self.repo.billing_current(tenant_id=access.tenant_id)
        if current is not None and current.get("entitlement_state") in {
            EntitlementState.FULL.value, EntitlementState.BILLING_PENDING.value
        }:
            raise ApiConflict("tenant already has a current subscription; use a future plan-change flow instead of creating another")
        if current is None and existing is None:
            latest = self.repo.latest_billing_checkout(tenant_id=access.tenant_id)
            if latest is not None and latest.get("state") in {"in_flight", "provider_created", "ambiguous"}:
                raise ApiConflict("an earlier billing checkout is still unresolved; reconcile it before creating another")

        provider_plan = self.runtime.provider.fetch_plan(plan.provider_plan_id)
        item = provider_plan.get("item") or {}
        provider_amount = int(item.get("amount") or item.get("unit_amount") or 0)
        provider_currency = str(item.get("currency") or "").upper()
        if provider_amount != plan.amount_subunits or provider_currency != plan.currency:
            raise ApiConflict("configured billing price does not match the Razorpay plan; checkout blocked")

        intent, replay = self.repo.prepare_billing_checkout(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=key,
            plan_key=plan.key,
        )
        state = str(intent["state"])
        if replay and state == "provider_created":
            return {
                "checkout_intent_id": intent["id"], "plan_key": plan.key,
                "provider_subscription_id": intent["provider_subscription_id"],
                "checkout_url": intent["checkout_url"], "state": state,
                "idempotency_replay": True,
            }
        if replay and state in {"in_flight", "ambiguous"}:
            raise ApiConflict("billing checkout outcome is ambiguous; do not retry with a new key until reconciled")
        if replay and state == "failed":
            raise ApiConflict("billing checkout failed; start a new checkout with a new idempotency key")

        intent_id = UUID(str(intent["id"]))
        self.repo.set_billing_checkout_state(
            tenant_id=access.tenant_id, intent_id=intent_id, state="in_flight"
        )
        try:
            subscription = self.runtime.provider.create_subscription(
                plan=plan, tenant_id=access.tenant_id, checkout_intent_id=intent_id
            )
        except CheckoutAmbiguousError:
            self.repo.set_billing_checkout_state(
                tenant_id=access.tenant_id, intent_id=intent_id, state="ambiguous",
                failure_code="PROVIDER_OUTCOME_UNKNOWN",
            )
            raise
        except BillingProviderError:
            self.repo.set_billing_checkout_state(
                tenant_id=access.tenant_id, intent_id=intent_id, state="failed",
                failure_code="PROVIDER_REJECTED",
            )
            raise

        if subscription.plan_id != plan.provider_plan_id:
            self.repo.set_billing_checkout_state(
                tenant_id=access.tenant_id, intent_id=intent_id, state="ambiguous",
                provider_subscription_id=subscription.id,
                provider_plan_id=subscription.plan_id,
                failure_code="PROVIDER_PLAN_MISMATCH",
            )
            raise ApiConflict("Razorpay returned a subscription for an unexpected plan")

        self.repo.set_billing_checkout_state(
            tenant_id=access.tenant_id,
            intent_id=intent_id,
            state="provider_created",
            provider_subscription_id=subscription.id,
            provider_plan_id=subscription.plan_id,
            checkout_url=subscription.short_url,
        )
        return {
            "checkout_intent_id": intent_id, "plan_key": plan.key,
            "provider_subscription_id": subscription.id,
            "checkout_url": subscription.short_url, "state": "provider_created",
            "idempotency_replay": False,
        }

    def reconcile(self, *, access: TenantAccess) -> dict[str, Any]:
        if self.runtime is None:
            raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE)
        current = self.repo.billing_current(tenant_id=access.tenant_id)
        if current is not None:
            subscription_id = str(current["provider_subscription_id"])
        else:
            latest = self.repo.latest_billing_checkout(tenant_id=access.tenant_id)
            if latest is None or not latest.get("provider_subscription_id"):
                raise ApiConflict("no provider subscription is currently linked to this tenant")
            subscription_id = str(latest["provider_subscription_id"])
        return self._reconcile_subscription(
            tenant_id=access.tenant_id, subscription_id=subscription_id,
        )

    def reconcile_provider_subscription(self, *, tenant_id: UUID, subscription_id: str) -> dict[str, Any]:
        if self.runtime is None:
            raise BillingAccessError("billing is not configured")
        return self._reconcile_subscription(tenant_id=tenant_id, subscription_id=subscription_id)

    def _reconcile_subscription(self, *, tenant_id: UUID, subscription_id: str) -> dict[str, Any]:
        assert self.runtime is not None
        checkout = self.repo.billing_checkout_by_provider(
            tenant_id=tenant_id, provider_subscription_id=subscription_id
        )
        if checkout is None:
            raise ApiConflict("Razorpay subscription is not linked to a checkout created by this tenant")
        subscription = self.runtime.provider.fetch_subscription(subscription_id)
        if subscription.id != subscription_id:
            raise BillingProviderError("provider returned the wrong subscription")
        plan = self.runtime.catalog.by_provider_plan_id(subscription.plan_id)
        # The checkout plan establishes subscription ownership, not a permanent plan lock.
        # Legitimate Epic-11 cycle-end plan changes may move the same owned subscription
        # to another catalog plan while retaining the original checkout ownership notes.
        note_tenant = str(subscription.notes.get("recovery_tenant_id", ""))
        note_intent = str(subscription.notes.get("recovery_checkout_intent_id", ""))
        if note_tenant != str(tenant_id) or note_intent != str(checkout["id"]):
            raise ApiConflict("provider subscription ownership notes do not match local checkout")
        entitlement=entitlement_for_status(subscription.status)
        grace_until=None
        if subscription.status=="pending" and self.runtime.grace_hours>0:
            previous=self.repo.billing_current(tenant_id=tenant_id)
            now=datetime.now(timezone.utc)
            if previous and previous.get("entitlement_state")==EntitlementState.FULL.value:
                grace_until=now+timedelta(hours=self.runtime.grace_hours); entitlement=EntitlementState.GRACE
            elif previous and previous.get("entitlement_state")==EntitlementState.GRACE.value and previous.get("grace_until") and previous["grace_until"]>now:
                grace_until=previous["grace_until"]; entitlement=EntitlementState.GRACE
        reconcile_fn=self.repo.reconcile_billing_subscription
        reconcile_kwargs={"tenant_id":tenant_id,"subscription":subscription,"plan":plan,"entitlement_state":entitlement}
        # Compatibility with Phase-17 repository adapters used by embedders/tests: grace
        # is additive and older adapters remain valid when the feature is disabled.
        if "grace_until" in inspect.signature(reconcile_fn).parameters:
            reconcile_kwargs["grace_until"]=grace_until
        snapshot_id=reconcile_fn(**reconcile_kwargs)
        return {
            "snapshot_id": snapshot_id,
            "plan_key": plan.key,
            "provider_status": subscription.status,
            "entitlement_state": entitlement.value,
            "current_start": subscription.current_start,
            "current_end": subscription.current_end,
            "payment_method": subscription.payment_method,
            "grace_until": grace_until,
            "has_scheduled_changes": subscription.has_scheduled_changes,
        }

    def _provider_plan_verified(self, plan_key: str):
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        plan=self.runtime.catalog.get(plan_key)
        obj=self.runtime.provider.fetch_plan(plan.provider_plan_id); item=obj.get("item") or {}
        amount=int(item.get("amount") or item.get("unit_amount") or 0); currency=str(item.get("currency") or "").upper()
        if amount!=plan.amount_subunits or currency!=plan.currency:
            raise ApiConflict("configured billing price does not match the Razorpay plan")
        return plan

    def _owned_provider_subscription(self, *, access: TenantAccess):
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        current=self.repo.billing_current(tenant_id=access.tenant_id)
        if current is None or not current.get("provider_subscription_id"):
            raise ApiConflict("tenant has no reconciled provider subscription")
        sid=str(current["provider_subscription_id"])
        checkout=self.repo.billing_checkout_by_provider(tenant_id=access.tenant_id,provider_subscription_id=sid)
        if checkout is None: raise ApiConflict("provider subscription is not owned by this tenant")
        sub=self.runtime.provider.fetch_subscription(sid)
        if sub.id!=sid: raise BillingProviderError("provider returned the wrong subscription")
        if str(sub.notes.get("recovery_tenant_id", ""))!=str(access.tenant_id) or str(sub.notes.get("recovery_checkout_intent_id", ""))!=str(checkout["id"]):
            raise ApiConflict("provider subscription ownership notes do not match local checkout")
        return current,sub

    @staticmethod
    def _operation_replay(op: dict[str, Any], replay: bool) -> dict[str, Any] | None:
        if not replay: return None
        state=str(op.get("state") or "prepared")
        if state in {"provider_observed","reconciled"}: return op
        if state in {"in_flight","ambiguous"}: raise ApiConflict("billing lifecycle outcome is unresolved; reconcile provider state before retrying")
        if state=="failed": raise ApiConflict("billing lifecycle operation failed; start a new request with a new idempotency key")
        return None

    def plan_change_preview(self, *, access: TenantAccess, target_plan_key: str) -> dict[str, Any]:
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE)
        current,sub=self._owned_provider_subscription(access=access)
        target=self._provider_plan_verified(target_plan_key)
        if target.key==str(current.get("plan_key")): raise ApiConflict("target plan is already active")
        if sub.status not in {"authenticated","active"}: raise ApiConflict("Razorpay allows subscription updates only while authenticated or active")
        method=(sub.payment_method or "").lower()
        supported=method=="card"
        slots_fn=getattr(self.repo,"list_billing_account_slots",None); slots=slots_fn(tenant_id=access.tenant_id) if slots_fn else []
        ordered=sorted(slots,key=lambda x:(x.get("occurred_at") or datetime.min.replace(tzinfo=timezone.utc),str(x.get("account_id"))))
        affected=ordered[target.max_google_ads_accounts:]
        return {
            "current_plan_key":current.get("plan_key"),"target_plan":target.public_dict(),"provider_status":sub.status,
            "payment_method":sub.payment_method,"automated_change_supported":supported,"schedule_change_at":"cycle_end",
            "effective_at":sub.current_end,"active_account_slots":len(ordered),
            "accounts_over_target_limit":[{"account_id":x.get("account_id"),"customer_id":x.get("customer_id"),"descriptive_name":x.get("descriptive_name")} for x in affected],
            "note":"V1 schedules plan changes at cycle end only. Razorpay currently documents live subscription updates for card-authorized subscriptions only.",
        }

    def schedule_plan_change(self, *, access: TenantAccess, target_plan_key: str, idempotency_key: str, endpoint: str) -> dict[str, Any]:
        self._require_provider_mutations_enabled(access.tenant_id)
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE); key=validate_idempotency_key(idempotency_key)
        prior=self.repo.billing_lifecycle_operation_by_request(tenant_id=access.tenant_id,user_id=access.principal.user_id,idempotency_key=key)
        if prior is not None:
            if prior.get("operation_type")!="plan_change_cycle_end" or prior.get("target_plan_key")!=target_plan_key:
                raise ApiConflict("Idempotency-Key was already used with a different billing lifecycle request")
            replayed=self._operation_replay(prior,True)
            if replayed is not None: return replayed
        current,sub=self._owned_provider_subscription(access=access); target=self._provider_plan_verified(target_plan_key)
        if target.key==str(current.get("plan_key")): raise ApiConflict("target plan is already active")
        if sub.status not in {"authenticated","active"}: raise ApiConflict("subscription must be authenticated or active to change plans")
        if (sub.payment_method or "").lower()!="card": raise ApiConflict("automated Razorpay plan changes are supported only for provider-reported card subscriptions; UPI/eMandate require cancel-and-resubscribe in V1")
        if sub.has_scheduled_changes: raise ApiConflict("subscription already has scheduled provider changes")
        op,replay=self.repo.prepare_billing_lifecycle_operation(tenant_id=access.tenant_id,user_id=access.principal.user_id,endpoint=endpoint,idempotency_key=key,operation_type="plan_change_cycle_end",provider_subscription_id=sub.id,target_plan_key=target.key,effective_at=sub.current_end)
        existing=self._operation_replay(op,replay)
        if existing: return existing
        op_id=UUID(str(op["id"])); actor=access.actor_id
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="in_flight",actor=actor,payload={"target_provider_plan_id":target.provider_plan_id,"schedule_change_at":"cycle_end"})
        try:
            self.runtime.provider.update_subscription_plan(subscription_id=sub.id,plan_id=target.provider_plan_id,schedule_change_at="cycle_end")
        except BillingMutationAmbiguousError:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_update_outcome_unknown"}); raise
        except BillingProviderError as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="failed",actor=actor,payload={"error":type(exc).__name__}); raise
        try:
            current_provider=self.runtime.provider.fetch_subscription(sub.id)
            pending=self.runtime.provider.fetch_pending_update(sub.id)
            if pending.plan_id!=target.provider_plan_id:
                raise BillingMutationAmbiguousError("provider pending update does not match requested target plan")
        except (BillingProviderError,BillingMutationAmbiguousError) as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_readback_unavailable_or_mismatched"});
            if isinstance(exc,BillingMutationAmbiguousError): raise
            raise BillingMutationAmbiguousError("plan change may be scheduled but exact provider read-back failed") from exc
        self.repo.record_billing_pending_change(tenant_id=access.tenant_id,subscription_id=sub.id,pending=pending,target_plan=target)
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="provider_observed",actor=actor,payload={"pending_plan_id":pending.plan_id,"effective_at":(current_provider.current_end.isoformat() if current_provider.current_end else None)})
        self._reconcile_subscription(tenant_id=access.tenant_id,subscription_id=sub.id)
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="reconciled",actor=actor,payload={"target_plan_key":target.key})
        return self.repo.billing_lifecycle_operation(tenant_id=access.tenant_id,operation_id=op_id)

    def cancel_scheduled_plan_change(self, *, access: TenantAccess, idempotency_key: str, endpoint: str) -> dict[str, Any]:
        self._require_provider_mutations_enabled(access.tenant_id)
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE); key=validate_idempotency_key(idempotency_key)
        prior=self.repo.billing_lifecycle_operation_by_request(tenant_id=access.tenant_id,user_id=access.principal.user_id,idempotency_key=key)
        if prior is not None:
            if prior.get("operation_type")!="cancel_plan_change": raise ApiConflict("Idempotency-Key was already used with a different billing lifecycle request")
            replayed=self._operation_replay(prior,True)
            if replayed is not None: return replayed
        current,sub=self._owned_provider_subscription(access=access)
        if not sub.has_scheduled_changes: raise ApiConflict("provider subscription has no scheduled plan change")
        op,replay=self.repo.prepare_billing_lifecycle_operation(tenant_id=access.tenant_id,user_id=access.principal.user_id,endpoint=endpoint,idempotency_key=key,operation_type="cancel_plan_change",provider_subscription_id=sub.id,target_plan_key=None,effective_at=None)
        existing=self._operation_replay(op,replay)
        if existing: return existing
        op_id=UUID(str(op["id"])); actor=access.actor_id
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="in_flight",actor=actor,payload={})
        try: self.runtime.provider.cancel_scheduled_update(sub.id)
        except BillingMutationAmbiguousError:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_cancel_change_outcome_unknown"}); raise
        except BillingProviderError as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="failed",actor=actor,payload={"error":type(exc).__name__}); raise
        try:
            observed=self.runtime.provider.fetch_subscription(sub.id)
            if observed.has_scheduled_changes: raise BillingMutationAmbiguousError("provider still reports scheduled changes after cancellation")
        except (BillingProviderError,BillingMutationAmbiguousError) as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_readback_unavailable_or_still_scheduled"})
            if isinstance(exc,BillingMutationAmbiguousError): raise
            raise BillingMutationAmbiguousError("scheduled change cancellation may have succeeded but read-back failed") from exc
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="provider_observed",actor=actor,payload={"has_scheduled_changes":False})
        self._reconcile_subscription(tenant_id=access.tenant_id,subscription_id=sub.id)
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="reconciled",actor=actor,payload={})
        return self.repo.billing_lifecycle_operation(tenant_id=access.tenant_id,operation_id=op_id)

    def cancel_at_cycle_end(self, *, access: TenantAccess, idempotency_key: str, endpoint: str) -> dict[str, Any]:
        self._require_provider_mutations_enabled(access.tenant_id)
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE); key=validate_idempotency_key(idempotency_key)
        prior=self.repo.billing_lifecycle_operation_by_request(tenant_id=access.tenant_id,user_id=access.principal.user_id,idempotency_key=key)
        if prior is not None:
            if prior.get("operation_type")!="cancel_cycle_end": raise ApiConflict("Idempotency-Key was already used with a different billing lifecycle request")
            replayed=self._operation_replay(prior,True)
            if replayed is not None: return replayed
        current,sub=self._owned_provider_subscription(access=access)
        if sub.status not in {"authenticated","active","pending","halted"}: raise ApiConflict("subscription is not in a cancellable lifecycle state")
        if sub.current_end is None: raise ApiConflict("provider does not expose a current cycle end; cycle-end cancellation is blocked")
        ops=self.repo.latest_billing_lifecycle_operations(tenant_id=access.tenant_id,provider_subscription_id=sub.id,limit=50)
        if any(x.get("operation_type")=="cancel_cycle_end" and x.get("state") in {"provider_observed","reconciled"} for x in ops): raise ApiConflict("cycle-end cancellation is already scheduled")
        op,replay=self.repo.prepare_billing_lifecycle_operation(tenant_id=access.tenant_id,user_id=access.principal.user_id,endpoint=endpoint,idempotency_key=key,operation_type="cancel_cycle_end",provider_subscription_id=sub.id,target_plan_key=None,effective_at=sub.current_end)
        existing=self._operation_replay(op,replay)
        if existing: return existing
        op_id=UUID(str(op["id"])); actor=access.actor_id
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="in_flight",actor=actor,payload={"cancel_at_cycle_end":True})
        try:
            accepted=self.runtime.provider.cancel_subscription(subscription_id=sub.id,cancel_at_cycle_end=True)
            if accepted.id!=sub.id:
                raise BillingMutationAmbiguousError("Razorpay cancellation response identity does not match the requested subscription")
            if accepted.current_end is not None and accepted.current_end!=sub.current_end:
                raise BillingMutationAmbiguousError("Razorpay cancellation response changed the expected cycle boundary")
        except BillingMutationAmbiguousError:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_cancellation_outcome_unknown_or_identity_mismatch"}); raise
        except BillingProviderError as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="failed",actor=actor,payload={"error":type(exc).__name__}); raise
        try:
            observed=self.runtime.provider.fetch_subscription(sub.id)
            if observed.id!=sub.id:
                raise BillingMutationAmbiguousError("Razorpay cancellation read-back identity does not match the requested subscription")
            if observed.current_end is not None and observed.current_end!=sub.current_end:
                raise BillingMutationAmbiguousError("Razorpay cancellation read-back contradicts the expected cycle boundary")
        except (BillingProviderError,BillingMutationAmbiguousError) as exc:
            self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="ambiguous",actor=actor,payload={"reason":"provider_cancellation_readback_failed_or_contradictory"})
            if isinstance(exc,BillingMutationAmbiguousError): raise
            raise BillingMutationAmbiguousError("cycle-end cancellation may have succeeded but provider read-back failed") from exc
        # Razorpay does not expose a dedicated pending-cancellation flag in this response shape.
        # Evidence here means the provider accepted the cycle-end request and subsequent read-back
        # did not contradict subscription identity/cycle. It is not a fabricated provider flag.
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="provider_observed",actor=actor,payload={"provider_status":observed.status,"effective_at":sub.current_end.isoformat(),"evidence":"accepted_cycle_end_request_plus_non_contradictory_readback"})
        self._reconcile_subscription(tenant_id=access.tenant_id,subscription_id=sub.id)
        self.repo.append_billing_lifecycle_event(tenant_id=access.tenant_id,operation_id=op_id,event_type="reconciled",actor=actor,payload={})
        return self.repo.billing_lifecycle_operation(tenant_id=access.tenant_id,operation_id=op_id)

    def refresh_invoices(self, *, access: TenantAccess) -> dict[str, Any]:
        if self.runtime is None: raise BillingAccessError("billing is not configured")
        access.require(Permission.BILLING_MANAGE); _,sub=self._owned_provider_subscription(access=access)
        invoices=self.runtime.provider.fetch_subscription_invoices(sub.id)
        inserted=self.repo.record_billing_invoices(tenant_id=access.tenant_id,subscription_id=sub.id,invoices=invoices)
        return {"provider_subscription_id":sub.id,"provider_count":len(invoices),"new_snapshots":inserted,"invoices":self.repo.list_billing_invoices(tenant_id=access.tenant_id,subscription_id=sub.id,limit=200)}

    def invoices(self, *, access: TenantAccess, limit: int = 100) -> list[dict[str, Any]]:
        access.require(Permission.BILLING_READ); current=self.repo.billing_current(tenant_id=access.tenant_id)
        if current is None or not current.get("provider_subscription_id"): return []
        return self.repo.list_billing_invoices(tenant_id=access.tenant_id,subscription_id=str(current["provider_subscription_id"]),limit=limit)

    def entitlement_history(self, *, access: TenantAccess, limit: int = 100) -> list[dict[str, Any]]:
        access.require(Permission.BILLING_READ); return self.repo.billing_entitlement_history(tenant_id=access.tenant_id,limit=limit)

    def profile(self, *, access: TenantAccess) -> dict[str, Any] | None:
        access.require(Permission.BILLING_READ); return self.repo.billing_profile(tenant_id=access.tenant_id)

    def save_profile(self, *, access: TenantAccess, legal_name: str, billing_email: str, tax_country: str, tax_region: str | None, gstin: str | None) -> dict[str, Any]:
        access.require(Permission.BILLING_MANAGE)
        name=legal_name.strip(); email=billing_email.strip().lower(); country=tax_country.strip().upper(); region=(tax_region or "").strip() or None; gst=(gstin or "").strip().upper() or None
        if not 1<=len(name)<=200: raise ValueError("legal_name is required and must be <=200 characters")
        if len(email)>320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email): raise ValueError("billing_email is invalid")
        if not re.fullmatch(r"[A-Z]{2}",country): raise ValueError("tax_country must be a two-letter ISO code")
        if region and len(region)>120: raise ValueError("tax_region is too long")
        if gst and (country!="IN" or not re.fullmatch(r"[0-9A-Z]{15}",gst)): raise ValueError("GSTIN must be a 15-character uppercase identifier and is only accepted for India")
        return self.repo.save_billing_profile(tenant_id=access.tenant_id,user_id=access.principal.user_id,legal_name=name,billing_email=email,tax_country=country,tax_region=region,gstin=gst)

    def account_slots(self, *, access: TenantAccess) -> list[dict[str, Any]]:
        access.require(Permission.BILLING_READ); return self.repo.list_billing_account_slots(tenant_id=access.tenant_id)

    def release_account_slot(self, *, access: TenantAccess, account_id: UUID) -> None:
        access.require(Permission.BILLING_MANAGE); self.repo.release_billing_account_slot(tenant_id=access.tenant_id,account_id=account_id,actor=access.actor_id)

    def handle_webhook(self, *, raw_body: bytes, signature: str,
                       provider_event_id_header: str | None) -> dict[str, Any]:
        if self.runtime is None:
            raise BillingAccessError("billing is not configured")
        verify_razorpay_webhook(
            raw_body=raw_body, signature=signature, secret=self.runtime.webhook_secret
        )
        event_id = safe_webhook_event_id(
            raw_body=raw_body, header_event_id=provider_event_id_header
        )
        digest = hashlib.sha256(raw_body).hexdigest()
        webhook_id, claimed = self.repo.claim_billing_webhook(
            provider_event_id=event_id, raw_body_sha256=digest
        )
        if not claimed and self.repo.billing_webhook_has_result(webhook_event_id=webhook_id):
            return {"duplicate": True, "status": "already_processed"}
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self.repo.record_billing_webhook_result(
                webhook_event_id=webhook_id, tenant_id=None,
                provider_subscription_id=None, event_type=None,
                reconcile_status="failed", error_code="INVALID_JSON",
            )
            raise BillingAccessError("invalid Razorpay webhook JSON")

        event_type = str(payload.get("event", "")) or None
        entity = (((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {})
        if not isinstance(entity, dict) or not entity.get("id"):
            self.repo.record_billing_webhook_result(
                webhook_event_id=webhook_id, tenant_id=None,
                provider_subscription_id=None, event_type=event_type,
                reconcile_status="ignored",
            )
            return {"duplicate": False, "status": "ignored"}
        subscription_id = str(entity["id"])
        notes = entity.get("notes") or {}
        try:
            tenant_id = UUID(str(notes.get("recovery_tenant_id", "")))
        except (ValueError, TypeError):
            self.repo.record_billing_webhook_result(
                webhook_event_id=webhook_id, tenant_id=None,
                provider_subscription_id=subscription_id, event_type=event_type,
                reconcile_status="unknown_subscription", error_code="MISSING_TENANT_BINDING",
            )
            return {"duplicate": False, "status": "unknown_subscription"}

        checkout = self.repo.billing_checkout_by_provider(
            tenant_id=tenant_id, provider_subscription_id=subscription_id
        )
        if checkout is None:
            self.repo.record_billing_webhook_result(
                webhook_event_id=webhook_id, tenant_id=tenant_id,
                provider_subscription_id=subscription_id, event_type=event_type,
                reconcile_status="unknown_subscription",
            )
            return {"duplicate": False, "status": "unknown_subscription"}
        try:
            result = self._reconcile_subscription(
                tenant_id=tenant_id, subscription_id=subscription_id
            )
        except Exception as exc:
            self.repo.record_billing_webhook_result(
                webhook_event_id=webhook_id, tenant_id=tenant_id,
                provider_subscription_id=subscription_id, event_type=event_type,
                reconcile_status="failed", error_code=type(exc).__name__[:120],
            )
            raise
        self.repo.record_billing_webhook_result(
            webhook_event_id=webhook_id, tenant_id=tenant_id,
            provider_subscription_id=subscription_id, event_type=event_type,
            reconcile_status="reconciled",
        )
        return {"duplicate": False, "status": "reconciled", **result}
