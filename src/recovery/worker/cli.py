from __future__ import annotations

import argparse
import os
import signal
import socket
import threading

from recovery.api.jobs import JobType
from recovery.build_identity import validate_build_identity
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.semantic_ai import CandidateSemanticAI, GeminiInteractionsTransport
from recovery.semantic_production import PostgresSemanticProductionStore, PostgresSemanticReleaseResolver
from recovery.semantic_router import ProductionSemanticRouter
from recovery.onboarding import GoogleSecretManagerCredentialVault
from recovery.api.onboarding_service import GoogleAdsAccountDiscoveryJobRunner, PostgresOnboardingStore

from .analysis_job import ConservativeAnalysisJobRunner
from .deployment_probe import DeploymentProbeJobRunner
from .monitoring_job import MonitoringEvaluationJobRunner
from .reporting_job import ReportGenerationJobRunner
from .pilot_probe import GoogleAdsPilotReadProbeJobRunner
from .google_jobs import (
    EnvServiceAccountClientResolver, PostgresOAuthAwareClientResolver,
    GoogleAdsNegativeMutationJobRunner, GoogleAdsSyncJobRunner,
)
from .handlers import DurableMutationHandler, HandlerRegistry, SafeJobHandler
from .health import WorkerHealthServer, WorkerHealthState
from .runtime import WorkerRuntime
from .shadow_job import SemanticShadowJobRunner
from .store import PostgresWorkerStore


def build_runtime(*, worker_id: str, lease_seconds: int) -> WorkerRuntime:
    validate_build_identity()
    dsn = os.environ.get("RECOVERY_WORKER_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("RECOVERY_WORKER_DATABASE_URL is required")

    core = PostgresRecoveryRepository(dsn)
    store = PostgresWorkerStore(core)

    oauth_client_id = os.environ.get("GOOGLE_ADS_OAUTH_CLIENT_ID", "").strip()
    oauth_client_secret = os.environ.get("GOOGLE_ADS_OAUTH_CLIENT_SECRET", "").strip()
    oauth_secret_project = os.environ.get("GOOGLE_OAUTH_SECRET_MANAGER_PROJECT", "").strip()
    oauth_configured = bool(oauth_client_id and oauth_client_secret and oauth_secret_project)
    if any((oauth_client_id, oauth_client_secret, oauth_secret_project)) and not oauth_configured:
        raise SystemExit(
            "GOOGLE_ADS_OAUTH_CLIENT_ID, GOOGLE_ADS_OAUTH_CLIENT_SECRET and "
            "GOOGLE_OAUTH_SECRET_MANAGER_PROJECT must be configured together for worker OAuth access"
        )

    legacy_resolver = EnvServiceAccountClientResolver()
    oauth_vault = GoogleSecretManagerCredentialVault(project_id=oauth_secret_project) if oauth_configured else None
    resolver = (
        PostgresOAuthAwareClientResolver(
            core=core, oauth_client_id=oauth_client_id, oauth_client_secret=oauth_client_secret,
            vault=oauth_vault, fallback=legacy_resolver,
        ) if oauth_configured and oauth_vault is not None else legacy_resolver
    )
    sync_runner = GoogleAdsSyncJobRunner(core=core, client_resolver=resolver)
    production_candidate = CandidateSemanticAI(transport=GeminiInteractionsTransport())
    production_store = PostgresSemanticProductionStore(core)

    def production_router_factory(*, tenant_id, account_id, fit_evaluator):
        resolver = PostgresSemanticReleaseResolver(core, tenant_id=tenant_id, account_id=account_id)
        return ProductionSemanticRouter(
            candidate=production_candidate,
            release_resolver=resolver,
            fit_evaluator=fit_evaluator,
            on_hard_release_failure=resolver.trip_release,
        )

    analysis_runner = ConservativeAnalysisJobRunner(
        core=core, semantic_router_factory=production_router_factory,
        semantic_production_store=production_store,
    )
    shadow_runner = SemanticShadowJobRunner(
        core=core, candidate=CandidateSemanticAI(transport=GeminiInteractionsTransport())
    )
    mutation_runner = GoogleAdsNegativeMutationJobRunner(core=core, client_resolver=resolver)
    monitoring_runner = MonitoringEvaluationJobRunner(core=core)
    reporting_runner = ReportGenerationJobRunner(core=core)
    pilot_read_runner = GoogleAdsPilotReadProbeJobRunner(core=core,client_resolver=resolver)
    discovery_handler = None
    if oauth_configured and oauth_vault is not None:
        discovery_handler = SafeJobHandler(GoogleAdsAccountDiscoveryJobRunner(
            store=PostgresOnboardingStore(core),
            vault=oauth_vault,
            oauth_client_id=oauth_client_id, oauth_client_secret=oauth_client_secret,
        ))

    handlers = {
        JobType.GOOGLE_ADS_SYNC: SafeJobHandler(sync_runner),
        JobType.ANALYSIS_RUN: SafeJobHandler(analysis_runner),
        JobType.SEMANTIC_SHADOW: SafeJobHandler(shadow_runner),
        JobType.APPLY_NEGATIVE: DurableMutationHandler(store=store, runner=mutation_runner),
        JobType.ROLLBACK_NEGATIVE: DurableMutationHandler(store=store, runner=mutation_runner, rollback=True),
        JobType.DEPLOYMENT_PROBE: SafeJobHandler(DeploymentProbeJobRunner()),
        JobType.MONITORING_EVALUATION: SafeJobHandler(monitoring_runner),
        JobType.REPORT_GENERATION: SafeJobHandler(reporting_runner),
        JobType.PILOT_GOOGLE_ADS_READ_PROBE: SafeJobHandler(pilot_read_runner),
    }
    if discovery_handler is not None:
        handlers[JobType.GOOGLE_ADS_ACCOUNT_DISCOVERY] = discovery_handler
    registry = HandlerRegistry(handlers)
    return WorkerRuntime(
        store=store,
        registry=registry,
        worker_id=worker_id,
        worker_version="0.35.0",
        lease_seconds=lease_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Ads Recovery durable worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job then exit")
    default_id = os.environ.get("RECOVERY_WORKER_ID", "").strip() or f"{socket.gethostname()}:{os.getpid()}"
    parser.add_argument("--worker-id", default=default_id)
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--idle-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if args.once:
        runtime = build_runtime(worker_id=args.worker_id, lease_seconds=args.lease_seconds)
        print("processed" if runtime.run_once() else "idle")
    else:
        health_port=int(os.environ.get("RECOVERY_WORKER_HEALTH_PORT","0") or "0")
        health_state=WorkerHealthState.create(worker_version="0.35.0")
        health_server=WorkerHealthServer(state=health_state,port=health_port) if health_port else None
        if health_server is not None: health_server.start()
        try:
            runtime = build_runtime(worker_id=args.worker_id, lease_seconds=args.lease_seconds)
            health_state.startup_complete=True
            stop_event = threading.Event()
            def request_stop(signum, frame):
                health_state.stopping=True;stop_event.set()
            signal.signal(signal.SIGTERM, request_stop);signal.signal(signal.SIGINT, request_stop)
            runtime.run_forever(idle_sleep_seconds=args.idle_seconds, stop_event=stop_event)
        finally:
            health_state.stopping=True
            if health_server is not None: health_server.close()


if __name__ == "__main__":
    main()
