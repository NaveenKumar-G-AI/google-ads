from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from recovery.api.auth import Principal
from recovery.api.billing_service import BillingApplicationService, BillingRuntime
from recovery.api.policy import TenantRole, TenantAccess
from recovery.billing import BillingAccessError, BillingPlan, BillingPlanCatalog, EntitlementState


class Provider:
    pass

class Repo:
    def __init__(self,current): self.current=current
    def billing_current(self,*,tenant_id): return self.current


def access():
    u=uuid4()
    p=Principal(user_id=u,subject=str(u),email="a@example.com",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
    return TenantAccess(principal=p,tenant_id=uuid4(),role=TenantRole.OWNER)


def runtime():
    plan=BillingPlan(key="starter",display_name="Starter",provider_plan_id="plan_abc",currency="INR",amount_subunits=499900,total_count=12,max_google_ads_accounts=2,max_sync_range_days=90)
    return BillingRuntime(provider=Provider(),catalog=BillingPlanCatalog([plan]),webhook_secret="x")


def test_account_selection_limit_comes_from_reconciled_active_plan():
    current={"entitlement_state":EntitlementState.FULL.value,"plan_key":"starter","current_end":datetime.now(timezone.utc)+timedelta(days=30)}
    svc=BillingApplicationService(repository=Repo(current),runtime=runtime())
    assert svc.account_selection_limit(access=access())==2


def test_account_selection_fails_closed_without_active_subscription():
    svc=BillingApplicationService(repository=Repo(None),runtime=runtime())
    with pytest.raises(BillingAccessError):
        svc.account_selection_limit(access=access())
