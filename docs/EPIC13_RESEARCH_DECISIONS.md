# Epic 13 — Research Decisions

Version target: 0.32.0

- Google test accounts are the safest staging target for API/configuration validation, but their zero serving metrics cannot validate production economics.
- A dedicated read-only provider probe is stronger and safer than reusing sync or mutation code for acceptance.
- Worker startup/liveness checks must measure process/runtime health only; provider/database health belongs in jobs/readiness/alerts.
- Cloud Monitoring/Logging remains infrastructure truth rather than being reimplemented inside Recovery OS.
- Backup/PITR configuration does not prove recoverability; a separate disposable-target restore drill is mandatory.
- Pilot readiness is assembled from fresh deployed reports plus operator-attributed external evidence. Missing or stale evidence is a hard failure.
- Failure drills must actually exercise holds, reconciliation/rollback, incident escalation and restoration rather than merely document that they could be performed.
