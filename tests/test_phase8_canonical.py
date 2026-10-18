from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

import pytest

from recovery.db.canonical import canonical_json_text, canonical_payload, payload_sha256


class E(str, Enum):
    A = "a"


@dataclass(frozen=True)
class Demo:
    amount: Decimal
    when: date
    mode: E


def test_canonical_payload_preserves_decimal_as_string_not_float():
    payload = canonical_payload(Demo(Decimal("1.2300"), date(2026, 10, 15), E.A))
    assert payload == {"amount": "1.2300", "when": "2026-10-15", "mode": "a"}
    assert canonical_json_text(payload) == '{"amount":"1.2300","mode":"a","when":"2026-10-15"}'


def test_binary_float_is_forbidden_in_audit_fingerprint():
    with pytest.raises(TypeError, match="binary float"):
        canonical_payload({"money": 0.1})


def test_fingerprint_is_mapping_order_independent():
    assert payload_sha256({"a": 1, "b": 2}) == payload_sha256({"b": 2, "a": 1})
