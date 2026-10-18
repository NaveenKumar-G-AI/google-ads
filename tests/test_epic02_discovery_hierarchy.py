from recovery.google_ads.gaql import customer_descendants_query


def test_onboarding_hierarchy_query_does_not_truncate_nested_manager_descendants():
    q=customer_descendants_query().lower()
    assert "from customer_client" in q
    assert "level <= 1" not in q
    assert "customer_client.level" in q
