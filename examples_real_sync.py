"""Run a read-only Phase-7 sync against a real Google Ads advertiser account.

This script DOES NOT mutate Google Ads. It downloads Search-only audit inputs and the
current keyword/negative inventory into a resumable local sync directory.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Allow this read-only example to run directly from an extracted source checkout
# before `pip install -e .` has been run.
_PROJECT_SRC = Path(__file__).resolve().parent / "src"
if _PROJECT_SRC.is_dir() and str(_PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(_PROJECT_SRC))

from recovery.google_ads import (
    GoogleAdsSyncEngine,
    GoogleAdsV26Adapter,
    ServiceAccountConfig,
    build_service_account_client,
)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only real Google Ads Phase-7 sync")
    parser.add_argument("--customer-id", required=True, help="Advertiser customer ID")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--output", default="real-sync-data", help="Output directory")
    parser.add_argument("--chunk-days", type=int, default=7)
    args = parser.parse_args()

    config = ServiceAccountConfig(
        json_key_file_path=required_env("GOOGLE_ADS_JSON_KEY_FILE_PATH"),
        developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None,
        login_customer_id=os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None,
    )
    client = build_service_account_client(config)
    adapter = GoogleAdsV26Adapter(client)
    engine = GoogleAdsSyncEngine(adapter, chunk_days=args.chunk_days)
    result = engine.sync(
        customer_id=args.customer_id,
        start=args.start,
        end=args.end,
        output_root=args.output,
    )

    print("Read-only sync complete")
    print(f"Customer: {result.profile.customer_id} — {result.profile.descriptive_name}")
    print(f"Currency: {result.profile.currency_code}")
    print(f"Timezone: {result.profile.time_zone}")
    print(f"Downloaded chunks: {result.downloaded_chunks}/{result.requested_chunks}")
    print(f"Resumed/skipped chunks: {result.skipped_completed_chunks}")
    print(f"Positive keywords: {result.positive_keyword_count}")
    print(f"Effective negatives: {result.existing_negative_count}")
    print(f"Data directory: {result.output_directory}")


if __name__ == "__main__":
    main()
