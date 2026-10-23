from uuid import uuid4

import pytest

from recovery import acceptance


def identity(**overrides):
    return {
        "release_id": "release-1", "version": "test",
        "build_identity": "embedded", "build_release_id": "release-1",
        "build_revision": "a" * 40, "build_source_sha256": "1" * 64,
        **overrides,
    }


def run_acceptance(monkeypatch, api_identity, worker_identity, *, required=True):
    tenant = uuid4()

    def request(url, **kwargs):
        if url.endswith("/healthz"):
            return 200, {"status": "ok"}
        if url.endswith("/readyz"):
            return 200, {"status": "ready"}
        if url.endswith("/buildz"):
            return 200, api_identity
        if url.endswith("/v1/me"):
            return 200, {"memberships": [{"tenant_id": str(tenant)}]}
        if url.endswith("/deployment-probe"):
            return 202, {"job_id": "synthetic-job"}
        if url.endswith("/jobs/synthetic-job"):
            return 200, {"status": "succeeded", "result": {"probe": "ok", **worker_identity}}
        if url.endswith("/billing"):
            return 200, {"entitlement_state": "full"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(acceptance, "_json_request", request)
    monkeypatch.setattr(acceptance, "_http_status", lambda url: 200)
    return acceptance.StagingAcceptance(
        api_url="https://api.example.test", dashboard_url="https://app.example.test",
        tenant_id=tenant, bearer_token="synthetic-token", expected_release_id="release-1",
        require_build_identity=required,
    ).run()


def test_acceptance_compares_embedded_source_and_revision(monkeypatch):
    report = run_acceptance(monkeypatch, identity(), identity())
    assert report.passed
    checks = {item.name: item for item in report.checks}
    assert checks["api_build_identity"].status == "pass"
    assert checks["worker_build_identity"].status == "pass"


@pytest.mark.parametrize("overrides", [
    {"build_source_sha256": "2" * 64}, {"build_revision": "b" * 40},
    {"build_release_id": "other-release"}, {"build_identity": "unavailable"},
    {"build_source_sha256": 123}, {"build_revision": "a" * 50000},
])
def test_acceptance_rejects_same_runtime_label_with_different_or_invalid_worker_build(monkeypatch, overrides):
    report = run_acceptance(monkeypatch, identity(), identity(**overrides))
    assert not report.passed
    checks = {item.name: item for item in report.checks}
    assert checks["worker_round_trip"].status == "pass"
    assert checks["worker_build_identity"].status == "fail"


def test_required_stamp_cannot_pass_on_runtime_labels_alone(monkeypatch):
    legacy = {"release_id": "release-1", "version": "test"}
    assert not run_acceptance(monkeypatch, legacy, legacy).passed
    assert run_acceptance(monkeypatch, legacy, legacy, required=False).passed


def test_mismatched_stamps_fail_even_in_legacy_compatible_mode(monkeypatch):
    assert not run_acceptance(monkeypatch, identity(), identity(build_source_sha256="2" * 64), required=False).passed


def test_missing_api_stamp_cannot_be_replaced_by_worker_stamp(monkeypatch):
    assert not run_acceptance(monkeypatch, {"release_id": "release-1"}, identity()).passed


def test_report_copies_only_validated_build_fields(monkeypatch):
    report = run_acceptance(monkeypatch, identity(unexpected="not-public"), identity(unexpected="not-public"))
    assert report.passed
    assert "not-public" not in str(report.to_dict())
    assert "synthetic-token" not in str(report.to_dict())
