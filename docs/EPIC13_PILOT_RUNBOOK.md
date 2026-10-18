# Epic 13 — Pilot Runbook

This runbook produces the external evidence consumed by `recovery-pilot-gate`.

## Staging rehearsal

Run `deploy/pilot-staging.ps1` with a staging Admin bearer token, tenant ID and selected Recovery OS Google Ads account ID. It requires full billing acceptance, read-only Google Ads provider proof and `test_account=true`.

## Worker probes

Preview first:

```bash
python deploy/configure-worker-health.py --project <project> --region <region> --worker-pool recovery-worker
```

Use `--apply` only after reviewing the patch. Re-run deployed acceptance after the new revision becomes healthy.

## Observability

Create meaningful enabled Cloud Monitoring policies for API availability/failure, worker health/resource failure, durable-job risk, and an on-call path. Capture evidence with `pilot-observability-check.ps1`.

## Backup/PITR

Run `pilot-cloudsql-backup-check.ps1`. This is **not** the restore drill.

## Restore drill

Restore a known-good backup or PITR point to a **disposable target**, never the pilot/production primary. Current standard backup CLI supports commands such as:

```bash
gcloud sql backups restore <BACKUP_ID> \
  --restore-instance=<DISPOSABLE_TARGET> \
  --backup-instance=<SOURCE_INSTANCE> \
  --project=<PROJECT_ID>
```

Verify the restored database, `recovery.schema_migrations`, representative data, RLS/append-only objects, and record RTO/RPO evidence before deleting the target.

## Reconciliation/rollback drill

Use a non-production/test advertiser. Set `google_ads_mutations=false`, verify writes block while reads continue, then exercise one known safe human-approved mutation, exact read-back, rollback and an ambiguous/reconciliation fixture. Confirm Internal Admin does not offer unsafe blind replay.

## Incident-response drill

Exercise a real staging alert/incident path through on-call notification, incident creation, affected release/tenant identification, safe operational hold, remediation and resolution timeline.

## First real advertiser

Keep `google_ads_mutations=false`; run the read-only provider probe and sync; verify customer ID, currency and timezone; review Business Truth, Measurement Integrity and query/privacy coverage. Only then explicitly enable writes. First write remains human-approved and operator-observed.

## Razorpay Test Mode

Exercise checkout reconciliation, signed webhook→provider re-fetch, entitlement, invoice/payment history, supported cycle-end change, cycle-end cancellation, ambiguity handling and billing operational hold. Test Mode success is integration evidence, not live merchant activation evidence.

## Final gate

```bash
recovery-pilot-gate \
  --readiness-report <readiness.json> \
  --acceptance-report <acceptance.json> \
  --evidence-dir deploy/pilot-evidence \
  --expected-release-id <release-id> \
  --report pilot-gate-report.json
```

Exit code 0 and `qualified=true` are required. Readiness and deployed-acceptance reports older than 24 hours are rejected and must be regenerated against the current release.
