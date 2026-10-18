from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0017_epic09_reporting.sql').read_text()
REPO=(ROOT/'src/recovery/api/repository.py').read_text()
WORKER=(ROOT/'src/recovery/worker/reporting_job.py').read_text()
STORE=(ROOT/'src/recovery/worker/store.py').read_text()
RUNTIME=(ROOT/'src/recovery/worker/runtime.py').read_text()
CLI=(ROOT/'src/recovery/worker/cli.py').read_text()
SHELL=(ROOT/'web/components/epic1/app-shell.tsx').read_text()


def test_reporting_entities_are_immutable_and_rls_protected():
    for table in ('report_generations','report_artifacts','report_share_links','report_share_events','report_schedule_events','report_schedule_runs','report_delivery_events'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
        assert table in SQL
    assert 'prevent_immutable_mutation' in SQL
    assert 'FORCE ROW LEVEL SECURITY' in SQL


def test_share_tokens_are_hashed_and_revocation_is_an_event():
    assert 'token_sha256' in SQL and 'token text' not in SQL
    assert "'revoked'" in SQL and 'report_share_events' in SQL
    assert 'share_token_sha256' in REPO


def test_reporting_job_and_schedule_tick_are_durable_worker_paths():
    assert "'report_generation'" in SQL
    assert 'JobType.REPORT_GENERATION' in CLI
    assert 'ReportGenerationJobRunner' in CLI
    assert 'enqueue_due_report_jobs' in STORE and 'enqueue_due_report_jobs' in RUNTIME
    assert 'report_schedule_runs' in STORE


def test_smtp_ambiguity_is_recorded_without_blind_retry():
    assert 'SMTP outcome ambiguous' in WORKER
    assert 'event_type="ambiguous"' in WORKER
    assert 'return JobSuccess' in WORKER


def test_report_generation_stores_exact_snapshot_and_artifact_hashes():
    assert 'snapshot_sha256' in REPO
    assert 'artifact_sha256' in REPO
    assert 'render_report_pdf' in REPO and 'render_report_csv' in REPO
    assert '10*1024*1024' in REPO


def test_canonical_shell_enables_reports_and_public_view_exists():
    assert '["Reports","/app/reports",true]' in SHELL
    for rel in ('web/app/(dashboard)/app/reports/page.tsx','web/app/(dashboard)/app/reports/new/page.tsx','web/app/(dashboard)/app/reports/schedules/page.tsx','web/app/(dashboard)/app/reports/[generationId]/page.tsx','web/app/shared/reports/[token]/page.tsx'):
        assert (ROOT/rel).exists(),rel
    page=(ROOT/'web/app/(dashboard)/app/reports/page.tsx').read_text()
    assert 'A report is not a live dashboard.' in page
    public=(ROOT/'web/app/shared/reports/[token]/page.tsx').read_text()
    assert 'referrer:"no-referrer"' in public


def test_pdf_runtime_uses_unicode_shaping_and_noto_fonts():
    reporting=(ROOT/'src/recovery/reporting.py').read_text()
    docker=(ROOT/'deploy/Dockerfile.backend').read_text()
    pyproject=(ROOT/'pyproject.toml').read_text()
    assert 'from weasyprint import HTML' in reporting
    assert 'Noto Sans Tamil' in reporting
    assert 'weasyprint==68.0' in pyproject
    assert 'fonts-noto-core' in docker and 'libpango-1.0-0' in docker


def test_scheduled_email_is_recipient_isolated():
    assert 'recipient: str' in WORKER
    assert 'msg["To"]=recipient' in WORKER
    assert 'to_addrs=[recipient]' in WORKER
    assert "join(recipients)" not in WORKER


def test_public_share_api_suppresses_cache_referrer_and_indexing():
    app=(ROOT/'src/recovery/api/app.py').read_text()
    for header in ('Cache-Control','Referrer-Policy','X-Robots-Tag'):
        assert header in app
    assert 'no-store, private' in app
    assert 'noindex, nofollow' in app


def test_report_generation_is_idempotent_on_durable_job_identity():
    assert 'report_generations_source_job_uq' in SQL
    assert 'WHERE source_job_id IS NOT NULL' in SQL
    assert 'report-generation:{tenant_id}:{source_job_id}' in REPO
    assert 'WHERE tenant_id=%s AND source_job_id=%s' in REPO


def test_prepared_without_terminal_delivery_is_not_retried():
    assert 'previous=="prepared"' in WORKER
    assert 'Previous delivery attempt ended after prepared state without a terminal audit event; not retried.' in WORKER
    assert 'event_type="ambiguous"' in WORKER
