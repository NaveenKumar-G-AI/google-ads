from datetime import date,datetime,timezone
from uuid import uuid4
import pytest
from recovery.reporting import (
    ReportRequest,ReportType,ReportScope,financial_disclosure,new_share_token,parse_share_tenant,
    report_snapshot_sha256,render_report_csv,render_report_pdf,next_schedule_due,scheduled_period,
)


def snapshot():
    return {
        'schema_version':'recovery-report.v1','template_version':'t1','generation_id':str(uuid4()),
        'report_type':'executive_recovery','title':'Executive Recovery Report',
        'scope':{'kind':'organization','id':'x','name':'Acme'},'period':{'start':None,'end':None},
        'generated_at':'2026-10-16T06:00:00+00:00','financial_disclosure':financial_disclosure(),
        'sections':[{'key':'money','title':'Recovery proof','time_basis':'current', 'data':{
            'current_observed_candidate_micros':1000000,'projected_prevented_micros':900000,
            'observed_post_action_query_spend_micros':100000,'verified_recovery_micros':0,
        }}],
        'disclosures':['Projection is not verified recovery.'],
    }


def test_report_scope_and_period_contracts():
    with pytest.raises(ValueError): ReportRequest(ReportType.WASTE,ReportScope.ORGANIZATION,'x',date(2026,1,1),date(2026,1,2))
    with pytest.raises(ValueError): ReportRequest(ReportType.WASTE,ReportScope.ACCOUNT,str(uuid4()))
    with pytest.raises(ValueError): ReportRequest(ReportType.SEARCH_DEMAND,ReportScope.ACCOUNT,str(uuid4()),date(2026,2,2),date(2026,2,1))
    ReportRequest(ReportType.EXECUTIVE_RECOVERY,ReportScope.ORGANIZATION,str(uuid4()))


def test_financial_contract_is_non_additive_and_snapshot_hashes_exact_version():
    d=financial_disclosure();assert d['classes_are_non_additive'] is True
    s=snapshot();a=report_snapshot_sha256(s);s['sections'][0]['data']['verified_recovery_micros']=1;b=report_snapshot_sha256(s)
    assert a!=b


def test_share_tokens_expose_tenant_for_rls_context_but_store_hash_not_secret():
    tenant=uuid4();token,digest=new_share_token(tenant)
    assert parse_share_tenant(token)==tenant
    assert token not in digest and len(digest)==64
    assert len(token.split('.',1)[1])>=32


def test_static_pdf_and_csv_are_real_artifacts():
    s=snapshot();pdf=render_report_pdf(s);csv=render_report_csv(s)
    assert pdf.startswith(b'%PDF-') and len(pdf)>1000
    assert csv.startswith(b'\xef\xbb\xbf')
    text=csv.decode('utf-8-sig')
    assert 'verified_recovery_micros' in text and 'projected_prevented_micros' in text


def test_schedule_periods_use_complete_prior_calendar_periods():
    scheduled=datetime(2026,10,16,8,0,tzinfo=timezone.utc)
    assert scheduled_period(frequency='daily',scheduled_for=scheduled,timezone_name='UTC')==(date(2026,10,15),date(2026,10,15))
    assert scheduled_period(frequency='monthly',scheduled_for=scheduled,timezone_name='UTC')==(date(2026,9,1),date(2026,9,30))


def test_schedule_due_honors_timezone_weekday_and_month_day():
    after=datetime(2026,10,16,6,0,tzinfo=timezone.utc) # Fri
    weekly=next_schedule_due(frequency='weekly',timezone_name='UTC',hour=8,minute=0,weekday=0,after=after)
    assert weekly.weekday()==0 and weekly.hour==8
    monthly=next_schedule_due(frequency='monthly',timezone_name='UTC',hour=9,minute=30,day_of_month=5,after=after)
    assert monthly.day==5 and monthly.hour==9 and monthly.minute==30
