"""Build-time source identity; independent of editable runtime environment labels.

The source hash covers the packaged Python/SQL sources and build inputs. It is
not an OCI image digest: deploy the same registry digest to guarantee identical
OS libraries and resolved dependencies as well.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

_METADATA_PATH = Path(__file__).with_name("_build_metadata.json")
_SCHEMA = "recovery-build.v1"
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _validate_labels(release_id: str, revision: str) -> None:
    if release_id and not _RELEASE.fullmatch(release_id):
        raise ValueError("build release ID must be a bounded identifier")
    if revision and not _REVISION.fullmatch(revision):
        raise ValueError("build revision must be a full lowercase Git commit SHA")


def get_build_identity() -> dict[str, str]:
    """Read only the installed build stamp, never runtime identity overrides."""
    if not _METADATA_PATH.exists():
        return {
            "build_identity": "unavailable",
            "build_release_id": "",
            "build_revision": "",
            "build_source_sha256": "",
        }
    try:
        metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or set(metadata) != {
            "schema_version", "release_id", "revision", "source_sha256"
        }:
            raise ValueError()
        if any(not isinstance(value, str) for value in metadata.values()):
            raise ValueError()
        if metadata["schema_version"] != _SCHEMA:
            raise ValueError()
        _validate_labels(metadata["release_id"], metadata["revision"])
        if not _SHA256.fullmatch(metadata["source_sha256"]):
            raise ValueError()
    except (OSError, ValueError, TypeError):
        # Do not include malformed contents or filesystem paths in public errors.
        raise RuntimeError("embedded build metadata is invalid") from None
    return {
        "build_identity": "embedded",
        "build_release_id": metadata["release_id"],
        "build_revision": metadata["revision"],
        "build_source_sha256": metadata["source_sha256"],
    }


def validate_build_identity(env: Mapping[str, str] | None = None) -> None:
    """Reject relabeling an already stamped artifact as a different release."""
    values = os.environ if env is None else env
    identity = get_build_identity()
    runtime_release = values.get("RECOVERY_RELEASE_ID", "").strip()
    if identity["build_release_id"] and runtime_release and identity["build_release_id"] != runtime_release:
        raise RuntimeError("RECOVERY_RELEASE_ID does not match the embedded build release; deploy the matching artifact")
    render_revision = values.get("RENDER_GIT_COMMIT", "").strip()
    if identity["build_revision"] and render_revision and identity["build_revision"] != render_revision:
        raise RuntimeError("RENDER_GIT_COMMIT does not match the embedded build revision")


def source_sha256(root: Path) -> str:
    """Hash framed relative paths and bytes of inputs shipped in the backend."""
    paths = [
        root / "pyproject.toml",
        root / "README.md",
        root / "deploy" / "Dockerfile.backend",
    ]
    paths.extend(
        path for path in (root / "src" / "recovery").rglob("*")
        if path.is_file() and path.suffix in {".py", ".sql"}
        and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def write_build_metadata(root: Path, *, release_id: str, revision: str) -> Path:
    """Called inside the image build before setuptools packages the source."""
    _validate_labels(release_id, revision)
    metadata = {
        "schema_version": _SCHEMA,
        "release_id": release_id,
        "revision": revision,
        "source_sha256": source_sha256(root),
    }
    destination = root / "src" / "recovery" / "_build_metadata.json"
    destination.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    build_revision = os.environ.get("RECOVERY_BUILD_REVISION", "").strip() or os.environ.get("RENDER_GIT_COMMIT", "").strip()
    build_release = os.environ.get("RECOVERY_RELEASE_ID", "").strip() or build_revision
    write_build_metadata(Path.cwd(), release_id=build_release, revision=build_revision)
