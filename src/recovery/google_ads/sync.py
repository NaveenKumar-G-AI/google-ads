from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from recovery.domain import CampaignSpendObservation, CoverageSummary, SearchTermObservation, summarize_coverage
from recovery.waste_intelligence import CampaignPerformanceSegmentObservation, UserLocationObservation
from recovery.monitoring import CampaignHealthObservation
from recovery.measurement_integrity import (
    ConversionActionObservation, CustomerConversionGoalObservation, CampaignConversionGoalObservation,
    CampaignGoalConfigObservation, ConversionLagObservation,
)
from recovery.negative_keywords import ExistingNegativeKeyword, PositiveKeyword

from .adapter import GOOGLE_ADS_API_VERSION, GoogleAdsV26Adapter
from .auth import normalize_customer_id

SYNC_SCHEMA_VERSION = 1
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    manager: bool
    status: str
    test_account: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "customer_id", normalize_customer_id(self.customer_id))
        code = self.currency_code.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("customer profile currency must be a 3-letter code")
        object.__setattr__(self, "currency_code", code)
        if not self.time_zone.strip():
            raise ValueError("customer time_zone is required")
        try:
            ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA time zone: {self.time_zone}") from exc
        if not self.status.strip():
            raise ValueError("customer status is required")

    def local_today(self, now: datetime | None = None) -> date:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(ZoneInfo(self.time_zone)).date()


@dataclass(frozen=True, slots=True)
class SyncChunk:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("chunk start must be <= end")

    @property
    def key(self) -> str:
        return f"{self.start.isoformat()}__{self.end.isoformat()}"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    jitter_fraction: float = 0.10

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be >= 1")
        if not (0 <= self.jitter_fraction <= 1):
            raise ValueError("jitter_fraction must be in [0, 1]")


class RetryClassifier(Protocol):
    def __call__(self, exc: BaseException) -> bool: ...


class SyncStore(Protocol):
    """Persistence contract used by the real Google Ads sync engine."""

    location: str

    def chunk_complete(self, chunk: "SyncChunk") -> bool: ...

    def commit_chunk(
        self,
        *,
        chunk: "SyncChunk",
        search_terms: Sequence[SearchTermObservation],
        campaign_spend: Sequence[CampaignSpendObservation],
    ) -> None: ...

    def commit_dimension_chunk(
        self, *, chunk: "SyncChunk",
        campaign_segments: Sequence[CampaignPerformanceSegmentObservation],
        user_locations: Sequence[UserLocationObservation],
    ) -> None: ...

    def commit_monitoring_snapshot(
        self, *, campaign_health: Sequence[CampaignHealthObservation]
    ) -> None: ...

    def commit_measurement_snapshot(
        self, *,
        conversion_actions: Sequence[ConversionActionObservation],
        customer_goals: Sequence[CustomerConversionGoalObservation],
        campaign_goals: Sequence[CampaignConversionGoalObservation],
        campaign_goal_configs: Sequence[CampaignGoalConfigObservation],
        lag_observations: Sequence[ConversionLagObservation],
    ) -> None: ...

    def commit_inventory(
        self,
        *,
        positive_keywords: Sequence[PositiveKeyword],
        existing_negatives: Sequence[ExistingNegativeKeyword],
    ) -> None: ...


class SyncStoreFactory(Protocol):
    def __call__(
        self, *, profile: "CustomerProfile", start: date, end: date
    ) -> SyncStore: ...


def _enum_or_message_text(value: Any) -> str:
    name = getattr(value, "name", None)
    if name:
        return str(name)
    return str(value)


def is_retryable_google_ads_error(exc: BaseException) -> bool:
    """Conservative retry classifier for documented transient Google Ads failures.

    It deliberately does *not* retry generic RESOURCE_EXHAUSTED, because that can mean
    a daily quota has been exhausted. Short-term quota exhaustion is retried only when
    the GoogleAdsFailure contains RESOURCE_TEMPORARILY_EXHAUSTED.
    """

    grpc_error = getattr(exc, "error", None)
    code_method = getattr(grpc_error, "code", None)
    if callable(code_method):
        try:
            code = _enum_or_message_text(code_method()).upper()
        except Exception:  # diagnostic extraction must never mask the original error
            code = ""
        if any(x in code for x in ("DEADLINE_EXCEEDED", "UNAVAILABLE", "INTERNAL")):
            return True

    failure = getattr(exc, "failure", None)
    errors = getattr(failure, "errors", ()) if failure is not None else ()
    for error in errors or ():
        code_obj = getattr(error, "error_code", None)
        text = _enum_or_message_text(code_obj).upper()
        if any(
            x in text
            for x in (
                "RESOURCE_TEMPORARILY_EXHAUSTED",
                "TRANSIENT_ERROR",
                "INTERNAL_ERROR",
                "DEADLINE_EXCEEDED",
            )
        ):
            return True
    return False


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    retryable: RetryClassifier = is_retryable_google_ads_error,
    sleeper: Callable[[float], None] = time.sleep,
    random_unit: Callable[[], float] = random.random,
) -> T:
    attempt = 1
    delay = policy.initial_delay_seconds
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= policy.max_attempts or not retryable(exc):
                raise
            jitter = delay * policy.jitter_fraction * ((random_unit() * 2) - 1)
            sleeper(max(0.0, min(policy.max_delay_seconds, delay + jitter)))
            attempt += 1
            delay = min(policy.max_delay_seconds, delay * policy.multiplier)


def split_date_window(start: date, end: date, *, chunk_days: int = 7) -> tuple[SyncChunk, ...]:
    if start > end:
        raise ValueError("sync start must be <= end")
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    chunks: list[SyncChunk] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
        chunks.append(SyncChunk(cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return tuple(chunks)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        _jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


class FileSyncStore:
    """Small resumable on-disk store for founder-operated V1 syncs.

    This is intentionally *not* the Phase-8 database. Its purpose is to make real API
    imports restart-safe now. Each completed chunk is written atomically and recorded
    in a manifest only after its checksum is known.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        profile: CustomerProfile,
        start: date,
        end: date,
    ) -> None:
        seed = f"{profile.customer_id}|{start}|{end}|{GOOGLE_ADS_API_VERSION}|{SYNC_SCHEMA_VERSION}"
        run_id = hashlib.sha256(seed.encode()).hexdigest()[:20]
        self.currency_code = profile.currency_code
        self.directory = Path(root).expanduser().resolve() / profile.customer_id / run_id
        self.location = str(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.directory / "manifest.json"
        self._initialize_or_validate(profile, start, end)

    def _atomic_json(self, path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(_canonical_json_bytes(payload))
        os.replace(tmp, path)

    def _read_manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _initialize_or_validate(self, profile: CustomerProfile, start: date, end: date) -> None:
        expected = {
            "schema_version": SYNC_SCHEMA_VERSION,
            "api_version": GOOGLE_ADS_API_VERSION,
            "customer_id": profile.customer_id,
            "currency_code": profile.currency_code,
            "time_zone": profile.time_zone,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
        }
        if self.manifest_path.exists():
            current = self._read_manifest()
            for key, value in expected.items():
                if current.get(key) != value:
                    raise ValueError(f"existing sync manifest mismatch for {key}")
            return
        self._atomic_json(
            self.manifest_path,
            {
                **expected,
                "profile": _jsonable(profile),
                "completed_chunks": {},
                "waste_dimension_chunks": {},
                "measurement": None,
                "monitoring": None,
                "inventory": None,
            },
        )

    def chunk_complete(self, chunk: SyncChunk) -> bool:
        manifest = self._read_manifest()
        meta = manifest["completed_chunks"].get(chunk.key)
        if not meta:
            return False
        path = self.directory / meta["file"]
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return _sha256(payload) == meta["sha256"]

    def commit_chunk(
        self,
        *,
        chunk: SyncChunk,
        search_terms: Sequence[SearchTermObservation],
        campaign_spend: Sequence[CampaignSpendObservation],
    ) -> None:
        payload = {
            "schema_version": SYNC_SCHEMA_VERSION,
            "api_version": GOOGLE_ADS_API_VERSION,
            "chunk": {"start": chunk.start, "end": chunk.end},
            "search_terms": list(search_terms),
            "campaign_spend": list(campaign_spend),
            "coverage": (
                summarize_coverage(search_terms, campaign_spend)
                if search_terms or campaign_spend
                else CoverageSummary(0, 0, self.currency_code)
            ),
        }
        filename = f"chunk_{chunk.key}.json"
        path = self.directory / filename
        self._atomic_json(path, payload)
        manifest = self._read_manifest()
        manifest["completed_chunks"][chunk.key] = {
            "file": filename,
            "sha256": _sha256(payload),
            "search_term_rows": len(search_terms),
            "campaign_spend_rows": len(campaign_spend),
        }
        self._atomic_json(self.manifest_path, manifest)

    def commit_dimension_chunk(
        self, *, chunk: SyncChunk,
        campaign_segments: Sequence[CampaignPerformanceSegmentObservation],
        user_locations: Sequence[UserLocationObservation],
    ) -> None:
        payload={
            "schema_version":1,"api_version":GOOGLE_ADS_API_VERSION,
            "chunk":{"start":chunk.start,"end":chunk.end},
            "campaign_segments":list(campaign_segments),"user_locations":list(user_locations),
        }
        filename=f"waste_dimensions_{chunk.key}.json"
        path=self.directory/filename
        self._atomic_json(path,payload)
        manifest=self._read_manifest()
        manifest.setdefault("waste_dimension_chunks",{})[chunk.key]={
            "file":filename,"sha256":_sha256(payload),
            "campaign_segment_rows":len(campaign_segments),"user_location_rows":len(user_locations),
        }
        self._atomic_json(self.manifest_path,manifest)

    def commit_monitoring_snapshot(
        self, *, campaign_health: Sequence[CampaignHealthObservation]
    ) -> None:
        payload={
            "schema_version":1,"api_version":GOOGLE_ADS_API_VERSION,
            "campaign_health":list(campaign_health),
        }
        path=self.directory/"monitoring.json"
        self._atomic_json(path,payload)
        manifest=self._read_manifest()
        manifest["monitoring"]={
            "file":path.name,"sha256":_sha256(payload),
            "campaign_health_rows":len(campaign_health),
        }
        self._atomic_json(self.manifest_path,manifest)

    def commit_measurement_snapshot(
        self, *,
        conversion_actions: Sequence[ConversionActionObservation],
        customer_goals: Sequence[CustomerConversionGoalObservation],
        campaign_goals: Sequence[CampaignConversionGoalObservation],
        campaign_goal_configs: Sequence[CampaignGoalConfigObservation],
        lag_observations: Sequence[ConversionLagObservation],
    ) -> None:
        payload={
            "schema_version":1,"api_version":GOOGLE_ADS_API_VERSION,
            "conversion_actions":list(conversion_actions),"customer_goals":list(customer_goals),
            "campaign_goals":list(campaign_goals),"campaign_goal_configs":list(campaign_goal_configs),
            "lag_observations":list(lag_observations),
        }
        path=self.directory/"measurement.json"
        self._atomic_json(path,payload)
        manifest=self._read_manifest()
        manifest["measurement"]={
            "file":path.name,"sha256":_sha256(payload),
            "conversion_action_rows":len(conversion_actions),"customer_goal_rows":len(customer_goals),
            "campaign_goal_rows":len(campaign_goals),"campaign_goal_config_rows":len(campaign_goal_configs),
            "conversion_lag_rows":len(lag_observations),
        }
        self._atomic_json(self.manifest_path,manifest)

    def commit_inventory(
        self,
        *,
        positive_keywords: Sequence[PositiveKeyword],
        existing_negatives: Sequence[ExistingNegativeKeyword],
    ) -> None:
        payload = {
            "schema_version": SYNC_SCHEMA_VERSION,
            "api_version": GOOGLE_ADS_API_VERSION,
            "positive_keywords": list(positive_keywords),
            "existing_negatives": list(existing_negatives),
        }
        path = self.directory / "inventory.json"
        self._atomic_json(path, payload)
        manifest = self._read_manifest()
        manifest["inventory"] = {
            "file": path.name,
            "sha256": _sha256(payload),
            "positive_keyword_rows": len(positive_keywords),
            "negative_keyword_rows": len(existing_negatives),
        }
        self._atomic_json(self.manifest_path, manifest)


@dataclass(frozen=True, slots=True)
class SyncResult:
    profile: CustomerProfile
    requested_chunks: int
    downloaded_chunks: int
    skipped_completed_chunks: int
    positive_keyword_count: int
    existing_negative_count: int
    output_directory: str


class GoogleAdsSyncEngine:
    def __init__(
        self,
        adapter: GoogleAdsV26Adapter,
        *,
        retry_policy: RetryPolicy = RetryPolicy(),
        chunk_days: int = 7,
    ) -> None:
        self.adapter = adapter
        self.retry_policy = retry_policy
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")
        self.chunk_days = chunk_days

    @staticmethod
    def _validate_chunk_rows(
        profile: CustomerProfile,
        chunk: SyncChunk,
        search_terms: Sequence[SearchTermObservation],
        campaign_spend: Sequence[CampaignSpendObservation],
    ) -> None:
        allowed_networks = {"SEARCH", "SEARCH_PARTNERS"}
        for row in (*search_terms, *campaign_spend):
            if row.customer_id != profile.customer_id:
                raise ValueError("API row customer ID differs from requested customer")
            if row.currency_code.upper() != profile.currency_code:
                raise ValueError("API row currency differs from immutable customer currency")
            if not (chunk.start <= row.date <= chunk.end):
                raise ValueError("API row date lies outside requested sync chunk")
            if row.network.upper() not in allowed_networks:
                raise ValueError("non-Search network leaked into Search-only sync")

        visible_term_spend = sum(row.cost_micros for row in search_terms)
        denominator_spend = sum(row.cost_micros for row in campaign_spend)
        if visible_term_spend > 0 and denominator_spend <= 0:
            raise ValueError(
                "campaign spend denominator missing for non-zero search-term spend"
            )
        if visible_term_spend > denominator_spend:
            raise ValueError(
                "visible search-term spend exceeds comparable campaign spend denominator"
            )

    def sync(
        self,
        *,
        customer_id: str,
        start: date,
        end: date,
        output_root: str | Path | None = None,
        store_factory: SyncStoreFactory | None = None,
        now: datetime | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> SyncResult:
        customer_id = normalize_customer_id(customer_id)
        profile = call_with_retry(
            lambda: self.adapter.get_customer_profile(customer_id),
            policy=self.retry_policy,
            sleeper=sleeper,
        )
        if profile.customer_id != customer_id:
            raise ValueError("Google returned a different customer than requested")
        if profile.manager:
            raise ValueError("V1 audit target must be an advertiser account, not a manager account")
        if profile.status.upper() != "ENABLED":
            raise ValueError(f"customer is not enabled: {profile.status}")
        if end > profile.local_today(now):
            raise ValueError("sync end date cannot be in the customer's future")

        if store_factory is not None:
            store = store_factory(profile=profile, start=start, end=end)
        else:
            if output_root is None:
                raise ValueError("output_root is required when no store_factory is supplied")
            store = FileSyncStore(output_root, profile=profile, start=start, end=end)
        chunks = split_date_window(start, end, chunk_days=self.chunk_days)
        downloaded = 0
        skipped = 0
        for chunk in chunks:
            if store.chunk_complete(chunk):
                skipped += 1
                continue

            def download() -> tuple[list[SearchTermObservation], list[CampaignSpendObservation], list[CampaignPerformanceSegmentObservation], list[UserLocationObservation]]:
                # Materialize every evidence stream before committing the core chunk. If any
                # Google stream fails midway, the Search chunk remains retryable.
                terms = list(self.adapter.iter_search_terms(customer_id, chunk.start, chunk.end))
                spend = list(self.adapter.iter_campaign_network_spend(customer_id, chunk.start, chunk.end))
                segment_iter=getattr(self.adapter,"iter_campaign_performance_segments",None)
                location_iter=getattr(self.adapter,"iter_user_location_performance",None)
                segments=list(segment_iter(customer_id,chunk.start,chunk.end)) if callable(segment_iter) else []
                locations=list(location_iter(customer_id,chunk.start,chunk.end)) if callable(location_iter) else []
                self._validate_chunk_rows(profile, chunk, terms, spend)
                for row in (*segments,*locations):
                    if row.customer_id != profile.customer_id or row.currency_code.upper() != profile.currency_code:
                        raise ValueError("dimension row differs from requested customer/currency")
                    if not (chunk.start <= row.date <= chunk.end):
                        raise ValueError("dimension row date lies outside requested sync chunk")
                    if row.network.upper() not in {"SEARCH","SEARCH_PARTNERS"}:
                        raise ValueError("non-Search network leaked into waste-dimension sync")
                return terms, spend, segments, locations

            terms, spend, segments, locations = call_with_retry(download, policy=self.retry_policy, sleeper=sleeper)
            commit_dimensions=getattr(store,"commit_dimension_chunk",None)
            if callable(commit_dimensions):
                # Commit this first. If it fails, the core chunk is not marked complete.
                # If core commit later fails, dimension commit is idempotent on retry.
                commit_dimensions(chunk=chunk,campaign_segments=segments,user_locations=locations)
            store.commit_chunk(chunk=chunk, search_terms=terms, campaign_spend=spend)
            downloaded += 1

        # Serving health is a point-in-time provider snapshot. Google primary_status
        # may lag recent changes, so it is persisted as observed provider evidence.
        health_iter=getattr(self.adapter,"iter_campaign_health",None)
        campaign_health=call_with_retry(
            lambda:list(health_iter(customer_id)) if callable(health_iter) else [],
            policy=self.retry_policy,sleeper=sleeper,
        )
        for row in campaign_health:
            if row.customer_id != profile.customer_id:
                raise ValueError("campaign health row differs from requested customer")
        commit_monitoring=getattr(store,"commit_monitoring_snapshot",None)
        if callable(commit_monitoring):
            commit_monitoring(campaign_health=campaign_health)

        # Measurement configuration is a point-in-time provider snapshot bound to this
        # sync run. Older/fake adapters may not expose these methods; an empty snapshot
        # remains explicit and will assess as UNKNOWN rather than being fabricated.
        action_iter=getattr(self.adapter,"iter_conversion_actions",None)
        customer_goal_iter=getattr(self.adapter,"iter_customer_conversion_goals",None)
        campaign_goal_iter=getattr(self.adapter,"iter_campaign_conversion_goals",None)
        campaign_config_iter=getattr(self.adapter,"iter_campaign_goal_configs",None)
        lag_iter=getattr(self.adapter,"iter_conversion_lag",None)
        conversion_actions=call_with_retry(lambda:list(action_iter(customer_id)) if callable(action_iter) else [],policy=self.retry_policy,sleeper=sleeper)
        customer_goals=call_with_retry(lambda:list(customer_goal_iter(customer_id)) if callable(customer_goal_iter) else [],policy=self.retry_policy,sleeper=sleeper)
        campaign_goals=call_with_retry(lambda:list(campaign_goal_iter(customer_id)) if callable(campaign_goal_iter) else [],policy=self.retry_policy,sleeper=sleeper)
        campaign_goal_configs=call_with_retry(lambda:list(campaign_config_iter(customer_id)) if callable(campaign_config_iter) else [],policy=self.retry_policy,sleeper=sleeper)
        lag_observations=call_with_retry(lambda:list(lag_iter(customer_id,start,end)) if callable(lag_iter) else [],policy=self.retry_policy,sleeper=sleeper)
        for row in (*conversion_actions,*customer_goals,*campaign_goals,*campaign_goal_configs,*lag_observations):
            if row.customer_id != profile.customer_id:
                raise ValueError("measurement row differs from requested customer")
        commit_measurement=getattr(store,"commit_measurement_snapshot",None)
        if callable(commit_measurement):
            commit_measurement(
                conversion_actions=conversion_actions,customer_goals=customer_goals,campaign_goals=campaign_goals,
                campaign_goal_configs=campaign_goal_configs,lag_observations=lag_observations,
            )

        positives, negatives = call_with_retry(
            lambda: self.adapter.get_keyword_inventory(customer_id),
            policy=self.retry_policy,
            sleeper=sleeper,
        )
        store.commit_inventory(
            positive_keywords=positives, existing_negatives=negatives
        )
        return SyncResult(
            profile=profile,
            requested_chunks=len(chunks),
            downloaded_chunks=downloaded,
            skipped_completed_chunks=skipped,
            positive_keyword_count=len(positives),
            existing_negative_count=len(negatives),
            output_directory=store.location,
        )
