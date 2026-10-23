"""The initial onboarding URLs must resolve in the actual backend route table."""
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from recovery.api.app import create_app
from recovery.api.auth import StaticTokenVerifier


@pytest.mark.parametrize("function", ["getMe", "getPersonalLaunchStatus"])
def test_frontend_initial_onboarding_call_is_an_authenticated_backend_route(function):
    source = (Path(__file__).resolve().parents[1] / "web/lib/recovery-api.ts").read_text(encoding="utf-8")
    declaration = re.search(rf"export const {function}\s*=.*?;", source, re.S)
    assert declaration, f"Update this contract test when {function} is refactored"
    path = re.search(r'apiFetch<[^>]+>\(\s*[\"\']([^\"\']+)[\"\']', declaration.group())
    assert path, f"Unable to extract the actual URL used by {function}"
    client = TestClient(create_app(repository=object(), verifier=StaticTokenVerifier({})))
    response = client.get(path.group(1))
    assert response.status_code == 401, (function, path.group(1), response.text)
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
