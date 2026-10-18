from recovery.db.canonical import payload_sha256
from recovery.db.identity import stable_inventory_payload
from recovery.negative_keywords import ExistingNegativeKeyword, NegativeMatchType, NegativeScope, PositiveKeyword


def test_inventory_checksum_is_order_independent():
    p1 = PositiveKeyword("roof repair", "BROAD", "1234567890", "10", "20")
    p2 = PositiveKeyword("roof replacement", "EXACT", "1234567890", "10", "20")
    n1 = ExistingNegativeKeyword(
        "jobs", NegativeMatchType.EXACT, NegativeScope.AD_GROUP,
        "1234567890", campaign_id="10", ad_group_id="20"
    )
    one = stable_inventory_payload(
        api_version="v26", sync_schema_version=1,
        positive_keywords=[p1, p2], existing_negatives=[n1]
    )
    two = stable_inventory_payload(
        api_version="v26", sync_schema_version=1,
        positive_keywords=[p2, p1], existing_negatives=[n1]
    )
    assert payload_sha256(one) == payload_sha256(two)
