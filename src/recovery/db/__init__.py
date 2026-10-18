"""Production PostgreSQL persistence and provenance layer (Phase 8)."""

from .canonical import canonical_json_text, canonical_payload, payload_sha256
from .identity import (
    campaign_spend_identity_sha256,
    stable_chunk_payload,
    stable_inventory_payload,
)
from .postgres import (
    IdempotencyConflict,
    MigrationDriftError,
    PostgresRecoveryRepository,
)
from .sync_store import PostgresSyncStore, PostgresSyncStoreFactory

__all__ = [
    "IdempotencyConflict",
    "MigrationDriftError",
    "PostgresRecoveryRepository",
    "PostgresSyncStore",
    "PostgresSyncStoreFactory",
    "canonical_json_text",
    "canonical_payload",
    "payload_sha256",
    "campaign_spend_identity_sha256",
    "stable_chunk_payload",
    "stable_inventory_payload",
]
