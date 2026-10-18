from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0016_epic08_monitoring_alerts.sql').read_text()
GAQL=(ROOT/'src/recovery/google_ads/gaql.py').read_text()
SYNC=(ROOT/'src/recovery/google_ads/sync.py').read_text()
WORKER=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
CLI=(ROOT/'src/recovery/worker/cli.py').read_text()
SHELL=(ROOT/'web/components/epic1/app-shell.tsx').read_text()
REPO=(ROOT/'src/recovery/api/repository.py').read_text()


def test_monitoring_tables_are_append_only_and_rls_protected():
    for table in ('monitoring_snapshots','campaign_health_observations','monitor_policy_events','monitor_alert_instances','monitor_alert_events'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
        assert table in SQL
    assert 'prevent_immutable_mutation' in SQL
    assert 'FORCE ROW LEVEL SECURITY' in SQL


def test_monitoring_job_type_is_registered_in_db_contract_and_worker():
    assert "'monitoring_evaluation'" in SQL
    assert 'JobType.MONITORING_EVALUATION' in CLI
    assert 'MonitoringEvaluationJobRunner' in CLI


def test_campaign_health_uses_current_provider_primary_status_fields():
    assert 'campaign.primary_status' in GAQL
    assert 'campaign.primary_status_reasons' in GAQL
    assert "campaign.advertising_channel_type = 'SEARCH'" in GAQL


def test_monitoring_snapshot_is_committed_before_inventory_completion():
    assert 'commit_monitoring_snapshot' in SYNC
    assert SYNC.index('health_iter=getattr') < SYNC.rindex('store.commit_inventory')


def test_successful_sync_enqueues_durable_monitoring_evaluation():
    assert 'JobType.MONITORING_EVALUATION' in WORKER
    assert 'post-sync-monitor:' in WORKER


def test_conversion_monitor_uses_mature_window_and_measurement_gate():
    assert 'configured_conversion_lag_days' in REPO
    assert 'conversion_dependent_claims_allowed' in REPO
    assert 'mature_end=latest["window_end"]-timedelta(days=lag)' in REPO


def test_alert_and_policy_truth_are_event_sourced_not_mutable_status_rows():
    assert 'monitor_policy_events' in SQL
    assert 'monitor_alert_instances' in SQL
    assert 'monitor_alert_events' in SQL
    assert 'monitor_alerts (' not in SQL
    assert "'auto_resolved'" in SQL
    assert 'incident_observation_action' in REPO
    assert 'derive_alert_state' in REPO


def test_canonical_shell_enables_monitoring_and_ui_states_truth_boundary():
    assert '["Monitoring & Alerts","/app/monitoring",true]' in SHELL
    for rel in ('web/app/(dashboard)/app/monitoring/page.tsx','web/app/(dashboard)/app/monitoring/alerts/page.tsx','web/app/(dashboard)/app/monitoring/policies/page.tsx'):
        assert (ROOT/rel).exists()
    page=(ROOT/'web/app/(dashboard)/app/monitoring/page.tsx').read_text()
    assert 'No hidden anomaly score.' in page
    assert 'not automatically a waste or recovery claim' in page


def test_recurrence_requires_evaluator_observed_clear_after_manual_close():
    assert 'condition_cleared_after_close' in REPO
    assert 'last_manual_close' in REPO
    assert 'last_auto_clear' in REPO
    assert 'condition_not_observed_in_latest_evaluation' in REPO


def test_reserved_query_recurrence_is_disabled_until_exact_case_linkage_exists():
    assert '"query_recurrence": {"enabled": False' in REPO
    assert 'query recurrence monitoring is not available until exact recurrence evidence is implemented' in REPO
    policies=(ROOT/'web/app/(dashboard)/app/monitoring/policies/page.tsx').read_text()
    assert 'value="query_recurrence"' not in policies


def test_statistical_minimum_evidence_gates_are_inspectable_policy_config():
    for key in ('min_baseline_daily_cost_micros','min_baseline_daily_conversions','min_recent_spend_ratio'):
        assert key in REPO
    policies=(ROOT/'web/app/(dashboard)/app/monitoring/policies/page.tsx').read_text()
    for label in ('Minimum baseline daily spend','Minimum baseline daily conversions','Minimum recent spend ratio'):
        assert label in policies
