from datetime import datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership
TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();CASE=uuid4();REQ=uuid4();SNAP=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc));HEAD={'Authorization':'Bearer token'}
class Repo:
    def __init__(self,role):self.role=role
    def touch_user(self,**k):return True
    def list_memberships(self,**k):return [{'tenant_id':TENANT,'tenant_name':'T','role':self.role.value,'status':'active'}]
    def membership(self,*,user_id,tenant_id):return Membership(TENANT,self.role,'active')
    def ensure_account(self,**k):return None
    def truth(self):return {'id':SNAP,'account_id':ACCOUNT,'truth_fingerprint':'a'*64,'schema_version':1,'version':1,'business_id':'b','business_name':'Acme','supersedes_version':None,'created_by':'user','created_at':NOW,'offer_count':1,'non_offer_count':0,'intent_policy_count':3,'audience_policy_count':0,'service_area_count':0,'outcome_count':1,'protected_query_count':1,'readiness':{'offering_mismatch':{'ready':True,'issues':[]}},'changed_sections':[],'payload':{'business_id':'b'}}
    def business_truth_version(self,**k):return self.truth()
    def business_truth_versions(self,**k):return [self.truth()]
    def case(self):return {'id':CASE,'account_id':ACCOUNT,'created_by':USER,'created_by_email':'u@test','category':'product','subject':'Need help','initial_body':'Issue','created_at':NOW,'state':'open','comment_count':0,'last_event_at':NOW,'events':[]}
    def customer_support_cases(self,**k):return [self.case()]
    def customer_support_case(self,**k):return self.case()
    def create_customer_support_case(self,**k):return self.case()
    def customer_support_case_event(self,**k):return self.case()
    def security_data_overview(self,**k):return {'membership':{'role':self.role.value},'google_connections':[],'legal_acceptances':[],'security_events':[],'data_requests':[],'retention':{}}
    def create_customer_data_request(self,**k):return {'id':REQ,'account_id':None,'created_by':USER,'created_by_email':'u@test','request_type':k['request_type'],'reason':k['reason'],'created_at':NOW,'state':'requested','last_event_at':NOW}
    def cancel_customer_data_request(self,**k):return {'id':REQ,'account_id':None,'created_by':USER,'created_by_email':'u@test','request_type':'full_data_export','reason':'x','created_at':NOW,'state':'cancelled','last_event_at':NOW}
    def security_configuration_export(self,**k):return {'schema_version':'x','tenant':{'id':str(TENANT)},'exclusions':['secrets']}
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'token':P})))


def test_viewer_can_read_business_truth_and_use_own_support_channel():
    c=client(TenantRole.VIEWER)
    assert c.get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/business-truth',headers=HEAD).status_code==200
    assert c.get(f'/v1/tenants/{TENANT}/support/cases',headers=HEAD).status_code==200
    assert c.post(f'/v1/tenants/{TENANT}/support/cases',headers=HEAD,json={'account_id':str(ACCOUNT),'category':'product','subject':'Need help','body':'Issue'}).status_code==201
    assert c.get(f'/v1/tenants/{TENANT}/security-data',headers=HEAD).status_code==200


def test_viewer_cannot_create_data_operation_request_or_export():
    c=client(TenantRole.VIEWER)
    assert c.post(f'/v1/tenants/{TENANT}/security-data/requests',headers=HEAD,json={'request_type':'full_data_export','reason':'need it'}).status_code==403
    assert c.get(f'/v1/tenants/{TENANT}/security-data/configuration-export',headers=HEAD).status_code==403


def test_admin_can_export_and_request_data_but_not_org_deletion():
    c=client(TenantRole.ADMIN)
    assert c.get(f'/v1/tenants/{TENANT}/security-data/configuration-export',headers=HEAD).status_code==200
    assert c.post(f'/v1/tenants/{TENANT}/security-data/requests',headers=HEAD,json={'request_type':'full_data_export','reason':'finance request'}).status_code==201
    assert c.post(f'/v1/tenants/{TENANT}/security-data/requests',headers=HEAD,json={'request_type':'organization_deletion','reason':'close'}).status_code==403


def test_owner_can_request_controlled_organization_deletion():
    c=client(TenantRole.OWNER)
    assert c.post(f'/v1/tenants/{TENANT}/security-data/requests',headers=HEAD,json={'request_type':'organization_deletion','reason':'close business'}).status_code==201


def test_v1_completion_permission_contract():
    assert Permission.BUSINESS_TRUTH_READ in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.SECURITY_DATA_READ in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.SUPPORT_CREATE in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.DATA_REQUEST_MANAGE not in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.DATA_REQUEST_MANAGE in ROLE_PERMISSIONS[TenantRole.ADMIN]
