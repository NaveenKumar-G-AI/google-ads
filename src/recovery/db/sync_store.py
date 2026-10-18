from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence
from uuid import UUID

from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.waste_intelligence import CampaignPerformanceSegmentObservation, UserLocationObservation
from recovery.monitoring import CampaignHealthObservation
from recovery.measurement_integrity import (ConversionActionObservation,CustomerConversionGoalObservation,CampaignConversionGoalObservation,CampaignGoalConfigObservation,ConversionLagObservation)
from recovery.google_ads.adapter import GOOGLE_ADS_API_VERSION
from recovery.google_ads.sync import CustomerProfile, SYNC_SCHEMA_VERSION, SyncChunk
from recovery.negative_keywords import ExistingNegativeKeyword, PositiveKeyword

from .postgres import PostgresRecoveryRepository, SyncRunHandle


class PostgresSyncStore:
    """Database-backed store matching the Phase-7 sync-store contract."""

    def __init__(
        self,
        *,
        repository: PostgresRecoveryRepository,
        handle: SyncRunHandle,
    ) -> None:
        self.repository = repository
        self.handle = handle
        self.location = f"postgres://sync-runs/{handle.sync_run_id}"

    def chunk_complete(self, chunk: SyncChunk) -> bool:
        return self.repository.chunk_complete(handle=self.handle, chunk=chunk)

    def commit_chunk(
        self,
        *,
        chunk: SyncChunk,
        search_terms: Sequence[SearchTermObservation],
        campaign_spend: Sequence[CampaignSpendObservation],
    ) -> None:
        self.repository.commit_sync_chunk(
            handle=self.handle,
            chunk=chunk,
            search_terms=search_terms,
            campaign_spend=campaign_spend,
        )

    def commit_dimension_chunk(
        self, *, chunk: SyncChunk,
        campaign_segments: Sequence[CampaignPerformanceSegmentObservation],
        user_locations: Sequence[UserLocationObservation],
    ) -> None:
        self.repository.commit_waste_dimension_chunk(
            handle=self.handle, chunk=chunk, campaign_segments=campaign_segments, user_locations=user_locations
        )

    def commit_monitoring_snapshot(
        self, *, campaign_health: Sequence[CampaignHealthObservation]
    ) -> None:
        self.repository.commit_monitoring_snapshot(
            handle=self.handle, campaign_health=campaign_health
        )

    def commit_measurement_snapshot(
        self, *, conversion_actions: Sequence[ConversionActionObservation],
        customer_goals: Sequence[CustomerConversionGoalObservation],
        campaign_goals: Sequence[CampaignConversionGoalObservation],
        campaign_goal_configs: Sequence[CampaignGoalConfigObservation],
        lag_observations: Sequence[ConversionLagObservation],
    ) -> None:
        self.repository.commit_measurement_snapshot(
            handle=self.handle,conversion_actions=conversion_actions,customer_goals=customer_goals,
            campaign_goals=campaign_goals,campaign_goal_configs=campaign_goal_configs,lag_observations=lag_observations,
        )

    def commit_inventory(
        self,
        *,
        positive_keywords: Sequence[PositiveKeyword],
        existing_negatives: Sequence[ExistingNegativeKeyword],
    ) -> None:
        self.repository.commit_inventory_snapshot(
            handle=self.handle,
            positive_keywords=positive_keywords,
            existing_negatives=existing_negatives,
        )


@dataclass(frozen=True, slots=True)
class PostgresSyncStoreFactory:
    repository: PostgresRecoveryRepository
    tenant_id: UUID
    request_id: str
    credential_ref: str | None = None
    credential_fingerprint: str | None = None

    def __call__(
        self,
        *,
        profile: CustomerProfile,
        start: date,
        end: date,
    ) -> PostgresSyncStore:
        account_id = self.repository.upsert_google_ads_account(
            tenant_id=self.tenant_id,
            profile=profile,
            credential_ref=self.credential_ref,
            credential_fingerprint=self.credential_fingerprint,
        )
        handle = self.repository.begin_sync_run(
            tenant_id=self.tenant_id,
            account_id=account_id,
            request_id=self.request_id,
            profile=profile,
            start=start,
            end=end,
            api_version=GOOGLE_ADS_API_VERSION,
            sync_schema_version=SYNC_SCHEMA_VERSION,
        )
        return PostgresSyncStore(repository=self.repository, handle=handle)
