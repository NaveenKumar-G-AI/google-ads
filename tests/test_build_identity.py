import json

from fastapi.testclient import TestClient
import pytest

from recovery import build_identity
from recovery.api.app import create_app, create_app_from_env
from recovery.worker.cli import build_runtime
from recovery.worker.deployment_probe import DeploymentProbeJobRunner


REVISION = "a" * 40


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    files = {
        "pyproject.toml": "[project]\nname = 'recovery'\n",
        "README.md": "Backend build\n",
        "deploy/Dockerfile.backend": "FROM python:3.13-slim\n",
        "src/recovery/example.py": "VALUE = 1\n",
        "src/recovery/db/migrations/0001.sql": "SELECT 1;\n",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(build_identity, "_METADATA_PATH", tmp_path / "src/recovery/_build_metadata.json")
    return tmp_path


def stamp(root):
    return build_identity.write_build_metadata(root, release_id="release-1", revision=REVISION)


def test_unstamped_source_is_explicitly_unavailable(source_tree, monkeypatch):
    monkeypatch.setenv("RECOVERY_BUILD_REVISION", REVISION)
    monkeypatch.setenv("RECOVERY_RELEASE_ID", "forged-runtime-label")
    assert build_identity.get_build_identity() == {
        "build_identity": "unavailable", "build_release_id": "",
        "build_revision": "", "build_source_sha256": "",
    }


def test_stamp_is_deterministic_and_excludes_generated_and_unshipped_files(source_tree):
    first = stamp(source_tree).read_bytes()
    (source_tree / "src/recovery/private.txt").write_text("ignored", encoding="utf-8")
    assert stamp(source_tree).read_bytes() == first
    assert build_identity.get_build_identity()["build_revision"] == REVISION


@pytest.mark.parametrize("path", ["pyproject.toml", "README.md", "deploy/Dockerfile.backend", "src/recovery/example.py", "src/recovery/db/migrations/0001.sql"])
def test_source_identity_covers_every_backend_input_kind(source_tree, path):
    before = build_identity.source_sha256(source_tree)
    target = source_tree / path
    target.write_bytes(target.read_bytes() + b"\nchanged\n")
    assert build_identity.source_sha256(source_tree) != before


def test_source_identity_frames_paths_as_well_as_bytes(source_tree):
    before = build_identity.source_sha256(source_tree)
    (source_tree / "src/recovery/example.py").rename(source_tree / "src/recovery/renamed.py")
    assert build_identity.source_sha256(source_tree) != before


@pytest.mark.parametrize("contents", ["not-json-secret", "[]", '{"schema_version":"unexpected-secret"}'])
def test_malformed_stamp_fails_without_disclosing_contents(source_tree, contents):
    build_identity._METADATA_PATH.write_text(contents, encoding="utf-8")
    with pytest.raises(RuntimeError) as error:
        build_identity.get_build_identity()
    assert str(error.value) == "embedded build metadata is invalid"


@pytest.mark.parametrize("key,value", [("release_id", "secret\nvalue"), ("revision", "abc123"), ("source_sha256", "x" * 64), ("schema_version", "future")])
def test_stamp_schema_is_validated(source_tree, key, value):
    path = stamp(source_tree)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="embedded build metadata is invalid"):
        build_identity.get_build_identity()


def test_runtime_labels_cannot_replace_embedded_identity(source_tree, monkeypatch):
    stamp(source_tree)
    monkeypatch.setenv("RECOVERY_RELEASE_ID", "different-release")
    assert build_identity.get_build_identity()["build_release_id"] == "release-1"
    with pytest.raises(RuntimeError, match="RECOVERY_RELEASE_ID does not match"):
        build_identity.validate_build_identity()
    with pytest.raises(RuntimeError, match="RENDER_GIT_COMMIT does not match"):
        build_identity.validate_build_identity({"RECOVERY_RELEASE_ID": "release-1", "RENDER_GIT_COMMIT": "b" * 40})
    build_identity.validate_build_identity({"RECOVERY_RELEASE_ID": "release-1", "RENDER_GIT_COMMIT": REVISION})


def test_api_and_worker_reject_relabelled_artifact_before_provider_setup(source_tree, monkeypatch):
    stamp(source_tree)
    monkeypatch.setenv("RECOVERY_RELEASE_ID", "different-release")
    with pytest.raises(RuntimeError, match="RECOVERY_RELEASE_ID does not match"):
        create_app_from_env()
    with pytest.raises(RuntimeError, match="RECOVERY_RELEASE_ID does not match"):
        build_runtime(worker_id="test", lease_seconds=300)


def test_api_and_worker_publish_identical_embedded_fields(source_tree, monkeypatch):
    from uuid import uuid4

    stamp(source_tree)
    monkeypatch.setenv("RECOVERY_RELEASE_ID", "release-1")
    with TestClient(create_app(repository=object(), verifier=object())) as client:
        response = client.get("/buildz")
    assert response.status_code == 200
    worker = DeploymentProbeJobRunner()(tenant_id=uuid4(), job_id=uuid4(), payload={"probe": "deployment_round_trip"})
    for key, value in build_identity.get_build_identity().items():
        assert response.json()[key] == worker[key] == value
    assert "no-store" in response.headers["Cache-Control"]
