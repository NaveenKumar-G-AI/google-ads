from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_request_sha256(*, method: str, path: str, payload: Any) -> str:
    envelope = {
        "method": method.upper().strip(),
        "path": path,
        "payload": payload,
    }
    raw = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_idempotency_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise ValueError("Idempotency-Key is required")
    if len(key) > 128:
        raise ValueError("Idempotency-Key must be <= 128 characters")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise ValueError("Idempotency-Key must contain printable ASCII without spaces")
    return key
