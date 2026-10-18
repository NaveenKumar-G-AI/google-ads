from pathlib import Path

PYPROJECT = Path("pyproject.toml").read_text(encoding="utf-8")


def test_phase9_runtime_versions_are_pinned():
    assert 'fastapi==0.143.1' in PYPROJECT
    assert 'PyJWT[crypto]==2.15.1' in PYPROJECT
    assert 'uvicorn[standard]==0.54.0' in PYPROJECT
