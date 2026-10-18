from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


def canonical_payload(value: Any) -> Any:
    """Convert domain values to a deterministic JSON-safe representation.

    Decimal values are serialized as strings, never binary floats. Dataclasses are
    traversed field-by-field so enums and nested dataclasses retain stable semantics.
    This representation is used for fingerprints; changing it is a schema event.
    """

    if is_dataclass(value):
        return {field.name: canonical_payload(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return canonical_payload(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): canonical_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_payload(v) for v in value]
    if isinstance(value, set):
        converted = [canonical_payload(v) for v in value]
        return sorted(converted, key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("binary float is forbidden in canonical financial/audit payloads")
    raise TypeError(f"unsupported canonical payload type: {type(value)!r}")


def canonical_json_text(value: Any) -> str:
    return json.dumps(
        canonical_payload(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_text(value).encode("utf-8")).hexdigest()
