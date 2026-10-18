from types import SimpleNamespace

from recovery.google_ads.discovery import GoogleAdsAccountDiscovery

class FakeCustomerService:
    def list_accessible_customers(self):
        return SimpleNamespace(resource_names=["customers/1111111111"])

class FakeAdsService:
    def search_stream(self, *, customer_id, query, timeout=None):
        if 'from customer_client' in query.lower():
            root=SimpleNamespace(id=1111111111,level=0,manager=True,descriptive_name='Agency',currency_code='USD',time_zone='America/New_York',status=SimpleNamespace(name='ENABLED'),test_account=False)
            child=SimpleNamespace(id=2222222222,level=1,manager=False,descriptive_name='Client A',currency_code='USD',time_zone='America/New_York',status=SimpleNamespace(name='ENABLED'),test_account=False)
            return [SimpleNamespace(results=[SimpleNamespace(customer_client=root),SimpleNamespace(customer_client=child)])]
        customer=SimpleNamespace(id=1111111111,descriptive_name='Agency',currency_code='USD',time_zone='America/New_York',manager=True,status=SimpleNamespace(name='ENABLED'),test_account=False)
        return [SimpleNamespace(results=[SimpleNamespace(customer=customer)])]

class FakeClient:
    def get_service(self,name,version=None):
        return FakeCustomerService() if name=='CustomerService' else FakeAdsService()

def test_manager_hierarchy_discovers_child_without_manual_customer_id():
    rows=GoogleAdsAccountDiscovery(FakeClient()).discover()
    by_id={r.customer_id:r for r in rows}
    assert by_id['1111111111'].direct_access is True
    assert by_id['2222222222'].direct_access is False
    assert by_id['2222222222'].login_customer_id == '1111111111'
    assert by_id['2222222222'].hierarchy_level == 1
