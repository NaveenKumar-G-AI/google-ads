from importlib import resources


def sql():
    return resources.files("recovery.db.migrations").joinpath("0004_phase13_shadow_release.sql").read_text(encoding="utf-8").lower()


def test_shadow_job_type_and_tables_exist():
    s=sql()
    assert "semantic_shadow" in s
    assert "semantic_shadow_runs" in s
    assert "semantic_shadow_predictions" in s
    assert "semantic_human_reviews" in s
    assert "semantic_gold_case_versions" in s
    assert "semantic_evaluation_runs" in s
    assert "semantic_release_definitions" in s
    assert "semantic_release_events" in s


def test_shadow_prediction_is_structurally_non_production():
    s=sql()
    assert "production_effect_allowed boolean not null default false" in s
    assert "check (production_effect_allowed = false)" in s
    # Shadow prediction table intentionally has no financial evidence columns.
    block=s.split("create table if not exists recovery.semantic_shadow_predictions",1)[1].split("create index",1)[0]
    for forbidden in ("cost_micros","conversions_value","verified_recovery_micros","potentially_avoidable"):
        assert forbidden not in block


def test_release_evidence_is_append_only_and_rls_protected():
    s=sql()
    assert "prevent_immutable_mutation" in s
    for table in (
        "semantic_shadow_predictions","semantic_human_reviews","semantic_gold_case_versions",
        "semantic_dataset_snapshots","semantic_evaluation_runs","semantic_release_definitions","semantic_release_events",
    ):
        assert table in s
    assert "enable row level security" in s
    assert "force row level security" in s


def test_release_pass_requires_provider_revision_and_threshold():
    s=sql()
    assert "not gate_passed or (provider_model_version is not null and selected_confidence_threshold is not null)" in s


def test_reviews_and_dataset_membership_are_versioned_relational_evidence():
    s=sql()
    assert "review_version integer" in s
    assert "supersedes_id uuid" in s
    assert "semantic_dataset_case_members" in s
    assert "gold_case_version_id uuid not null" in s
    assert "require_passing_semantic_evaluation" in s
    assert "validate_semantic_release_transition" in s
