import pytest
from recovery.api.idempotency import canonical_request_sha256, validate_idempotency_key


def test_request_hash_is_order_independent_for_json_objects():
    a = canonical_request_sha256(method="post", path="/x", payload={"b": 2, "a": 1})
    b = canonical_request_sha256(method="POST", path="/x", payload={"a": 1, "b": 2})
    assert a == b


def test_path_changes_request_hash():
    assert canonical_request_sha256(method="POST", path="/a", payload={}) != canonical_request_sha256(method="POST", path="/b", payload={})


def test_idempotency_key_validation():
    assert validate_idempotency_key("abc-123") == "abc-123"
    for bad in ("", "has space", "x" * 129, "line\nbreak"):
        with pytest.raises(ValueError):
            validate_idempotency_key(bad)
