"""Read-only HTTP checks for the public deployment and onboarding route contract.

No bearer token, database connection or mutation is used. Authenticated activation
and provider acceptance remain separate checks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def https_origin(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and parsed.path.strip("/") == "" and parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid or any(ch.isspace() or ch == "\\" for ch in value):
        raise ValueError("deployment URL must be an HTTPS origin without credentials, path, query or fragment")
    return f"https://{parsed.netloc}"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_public(url: str) -> tuple[int, dict]:
    request = Request(url, headers={"Accept": "application/json,text/html"})
    try:
        response = build_opener(NoRedirect).open(request, timeout=25)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("response exceeds diagnostic size limit")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            body = {}
        return response.status, body if isinstance(body, dict) else {}


def check_deployment(*, api_url: str, dashboard_url: str = "", expected_release_id: str = "",
                     require_build_identity: bool = False, require_public: bool = False,
                     fetch=get_public) -> dict:
    api = https_origin(api_url)
    dashboard = https_origin(dashboard_url) if dashboard_url else ""
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})

    def get(name, origin, path):
        try:
            return fetch(origin + path)
        except Exception as exc:
            # Never print provider bodies, URLs, environment values or exception text.
            add(name, False, f"Request failed ({type(exc).__name__})")
            return None, {}

    code, body = get("api_liveness", api, "/healthz")
    add("api_liveness", code == 200 and body.get("status") == "ok", f"GET /healthz: {code}")
    code, body = get("api_readiness", api, "/readyz")
    add("api_readiness", code == 200 and body.get("status") == "ready" and body.get("database") == "ready", f"GET /readyz: {code}; database readiness required")
    code, build = get("api_build", api, "/buildz")
    add("api_build", code == 200 and build.get("service") == "recovery-api", f"GET /buildz: {code}")
    if expected_release_id:
        add("declared_release", build.get("release_id") == expected_release_id, "Configured release must match the candidate")
    if require_build_identity:
        digest = build.get("build_source_sha256", "")
        revision = build.get("build_revision", "")
        release = build.get("build_release_id", "")
        embedded = (build.get("build_identity") == "embedded" and isinstance(digest, str)
                    and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                    and isinstance(revision, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision) is not None
                    and isinstance(release, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", release) is not None
                    and release == build.get("release_id"))
        add("embedded_build_identity", embedded, "Image must include source/revision identity and a matching runtime release")
        if expected_release_id:
            add("embedded_release", build.get("build_release_id") == expected_release_id, "Embedded release must match the candidate")
    for path in ("/v1/me", "/v1/launch/status/me"):
        code, body = get(path, api, path)
        error = body.get("error")
        add(path, code == 401 and isinstance(error, dict) and error.get("code") == "AUTHENTICATION_FAILED", f"Unauthenticated GET {path}: {code}; expected 401")
    code, schema = get("onboarding_openapi", api, "/openapi.json")
    paths = schema.get("paths") if isinstance(schema.get("paths"), dict) else {}
    registered = all(isinstance(paths.get(path), dict) and "get" in paths[path]
                     for path in ("/v1/me", "/v1/launch/status/me"))
    add("onboarding_openapi", code == 200 and registered, "Both initial onboarding GET routes must be in the deployed OpenAPI document")
    code, launch = get("launch_status", api, "/v1/launch/status")
    add("launch_status", code == 200 and launch.get("launch_mode") in {"closed", "pilot_only", "invite_only", "public"}, f"GET /v1/launch/status: {code}")
    if require_public:
        add("public_launch", launch.get("launch_mode") == "public" and launch.get("workspace_creation_open") is True, "Public workspace creation must be deliberately enabled")
        add("public_legal", launch.get("legal_acceptance_ready") is True, "Published Terms and Privacy identities must be ready")
        add("public_abuse", launch.get("signup_abuse_ready") is True and bool(launch.get("turnstile_site_key")), "Server-side public signup abuse protection must be ready")
    if dashboard:
        for path in ("/", "/login", "/signup", "/demo"):
            code, _ = get(f"web{path}", dashboard, path)
            add(f"web{path}", code == 200, f"Dashboard GET {path}: {code}")
    return {"passed": all(check["status"] == "pass" for check in checks), "checks": checks,
            "scope": "Unauthenticated HTTP contract only; no authenticated session, worker, billing or Google acceptance performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("RECOVERY_API_BASE_URL", ""))
    parser.add_argument("--dashboard-url", default=os.environ.get("NEXT_PUBLIC_SITE_URL", ""))
    parser.add_argument("--expected-release-id", default="")
    parser.add_argument("--require-build-identity", action="store_true")
    parser.add_argument("--require-public", action="store_true")
    args = parser.parse_args()
    try:
        report = check_deployment(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
