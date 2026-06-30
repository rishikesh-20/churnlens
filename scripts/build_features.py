"""Build the gold.features slice(s) for an as_of_date or monthly range (Phase 6).

Usage:
  uv run python scripts/build_features.py 2011-03-01                          # one slice
  uv run python scripts/build_features.py --start 2010-03-01 --end 2011-03-01 # monthly

Each slice needs its gold.customer_360 slice built first (run
scripts/build_customer360.py for the same date). The as_of_date is required and
explicit — feature building never defaults to today (D18). The same builder is
used for training backfills and production scoring (D26).
"""

import argparse

from churnlens.config.settings import get_settings
from churnlens.io.features import build_features
from churnlens.utils.dates import monthly_snapshots
from churnlens.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the gold.features slice(s) for a date.")
    parser.add_argument("as_of_date", nargs="?", help="Single as_of_date, e.g. 2011-03-01")
    parser.add_argument("--start", help="First month of a monthly backfill, e.g. 2010-03-01")
    parser.add_argument("--end", help="Last month of a monthly backfill, e.g. 2011-03-01")
    args = parser.parse_args()

    if args.start and args.end:
        slices = monthly_snapshots(args.start, args.end)
    elif args.as_of_date:
        slices = [args.as_of_date]
    else:
        parser.error("provide a single as_of_date or both --start and --end")

    settings = get_settings()
    configure_logging(settings.log_level)
    for as_of in slices:
        result = build_features(settings, as_of)
        print(f"{result.as_of_date}: {result.feature_rows:,} feature rows")
    print(f"  warehouse:       {settings.duckdb_path}")
    print(f"  parquet export:  {settings.gold_dir / 'features.parquet'}")
    print(f"  profile report:  {settings.reports_dir / 'features.md'}")


if __name__ == "__main__":
    main()
