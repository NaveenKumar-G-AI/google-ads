import pytest
from recovery.deployment_contract import check_deployment, https_origin


def healthy(url):
    if url.endswith('/healthz'): return 200, {'status': 'ok'}
    if url.endswith('/readyz'): return 200, {'status': 'ready', 'database': 'ready'}
    if url.endswith('/buildz'): return 200, {'service': 'recovery-api', 'release_id': 'candidate', 'build_identity': 'embedded', 'build_source_sha256': 'a'*64, 'build_release_id': 'candidate', 'build_revision': 'b'*40}
    if url.endswith('/v1/me') or url.endswith('/v1/launch/status/me'): return 401, {'error': {'code': 'AUTHENTICATION_FAILED'}}
    if url.endswith('/openapi.json'): return 200, {'paths': {'/v1/me': {'get': {}}, '/v1/launch/status/me': {'get': {}}}}
    if url.endswith('/v1/launch/status'): return 200, {'launch_mode': 'closed', 'workspace_creation_open': False, 'legal_acceptance_ready': False, 'signup_abuse_ready': False}
    return 200, {}


def test_public_contract_accepts_closed_infrastructure_but_never_calls_it_public_ready():
    result = check_deployment(api_url='https://api.example.com/', dashboard_url='https://app.example.com', expected_release_id='candidate', require_build_identity=True, fetch=healthy)
    assert result['passed']
    assert not check_deployment(api_url='https://api.example.com', require_public=True, fetch=healthy)['passed']


@pytest.mark.parametrize('path', ['/v1/me', '/v1/launch/status/me'])
def test_missing_route_fails_even_when_health_and_readiness_are_green(path):
    result = check_deployment(api_url='https://api.example.com', fetch=lambda url: (404, {'detail': 'Not Found'}) if url.endswith(path) else healthy(url))
    assert not result['passed']
    assert any(check['name'] == path and check['status'] == 'fail' for check in result['checks'])


def test_release_environment_cannot_substitute_for_embedded_identity():
    result = check_deployment(api_url='https://api.example.com', require_build_identity=True, fetch=lambda url: (200, {'service': 'recovery-api', 'release_id': 'candidate'}) if url.endswith('/buildz') else healthy(url))
    assert not result['passed']


@pytest.mark.parametrize('field,value', [('build_revision', ''), ('build_revision', 'short'), ('build_release_id', 'different'), ('build_source_sha256', 'invalid')])
def test_incomplete_or_mismatched_build_stamp_fails_without_expected_release(field, value):
    def fetch(url):
        code, body = healthy(url)
        if url.endswith('/buildz'):
            body[field] = value
        return code, body
    assert not check_deployment(api_url='https://api.example.com', require_build_identity=True, fetch=fetch)['passed']


@pytest.mark.parametrize('value', ['', 'http://api.example.com', 'https://user:secret@api.example.com', 'https://api.example.com/v1', 'https://api.example.com?secret=1', 'https://api.example.com#fragment', 'https://api.example.com\\@other.example'])
def test_origin_rejects_accidental_paths_and_credentials(value):
    with pytest.raises(ValueError): https_origin(value)


def test_diagnostics_do_not_expose_exception_credentials():
    def failure(url): raise RuntimeError('SECRET_PROVIDER_TEXT')
    report = check_deployment(api_url='https://api.example.com', fetch=failure)
    assert not report['passed']
    assert 'SECRET_PROVIDER_TEXT' not in str(report)
