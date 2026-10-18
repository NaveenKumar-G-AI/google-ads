from pathlib import Path
from recovery import launch_public_surface as m


def test_public_surface_collector_emits_three_machine_evidence_files(monkeypatch,tmp_path):
    def fake(url,**k):
        if url.endswith('/buildz'): return url,b'build',{'release_id':'r1'}
        if url.endswith('/v1/launch/status'): return url,b'status',{'terms_url':'https://app.example.com/terms','terms_version':'t1','privacy_url':'https://app.example.com/privacy','privacy_version':'p1','legal_acceptance_ready':True,'signup_abuse_ready':True,'turnstile_site_key':'site','public_workspace_max_per_user_24h':1}
        return url,b'html',None
    monkeypatch.setattr(m,'_get',fake)
    ok=m.run(api_url='https://api.example.com',dashboard_url='https://app.example.com',data_deletion_url='https://app.example.com/delete',operator='op@example.com',release_id='r1',evidence_dir=tmp_path)
    assert ok
    for kind in ('production_domain_tls','legal_privacy_publication','public_signup_abuse_controls'):
        text=(tmp_path/f'{kind}.json').read_text();assert '"status": "pass"' in text and '"schema_version": "recovery-launch-evidence.v1"' in text


def test_public_surface_collector_fails_release_mismatch(monkeypatch,tmp_path):
    def fake(url,**k):
        if url.endswith('/buildz'): return url,b'build',{'release_id':'old'}
        if url.endswith('/v1/launch/status'): return url,b'status',{'terms_url':'https://app.example.com/terms','terms_version':'t1','privacy_url':'https://app.example.com/privacy','privacy_version':'p1','legal_acceptance_ready':True,'signup_abuse_ready':True,'turnstile_site_key':'site','public_workspace_max_per_user_24h':1}
        return url,b'x',None
    monkeypatch.setattr(m,'_get',fake)
    assert not m.run(api_url='https://api.example.com',dashboard_url='https://app.example.com',data_deletion_url='https://app.example.com/delete',operator='op',release_id='r1',evidence_dir=tmp_path)
    assert '"status": "fail"' in (tmp_path/'production_domain_tls.json').read_text()


def test_public_surface_requires_https(tmp_path):
    try:m.run(api_url='http://api.example.com',dashboard_url='https://app.example.com',data_deletion_url='https://app.example.com/delete',operator='op',release_id='r1',evidence_dir=tmp_path)
    except ValueError as e:assert 'HTTPS' in str(e)
    else:raise AssertionError('expected HTTPS validation failure')
