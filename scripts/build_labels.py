"""Build the gold.labels slice(s) for a snapshot date or monthly range (Phase 5).

Usage:
  uv run python scripts/build_labels.py 2011-03-01                 # one snapshot
  uv run python scripts/build_labels.py --start 2010-03-01 --end 2011-03-01   # monthly

Each snapshot needs its gold.customer_360 slice built first (run
scripts/build_customer360.py for the same date). The snapshot date is required and
explicit — labeling never defaults to today (D18).
"""

import argparse

from churnlens.config.settings import get_settings
from churnlens.io.labels import build_labels
from churnlens.utils.dates import monthly_snapshots
from churnlens.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the gold.labels slice(s) for a date.")
    parser.add_argument("snapshot_date", nargs="?", help="Single snapshot date, e.g. 2011-03-01")
    parser.add_argument("--start", help="First month of a monthly backfill, e.g. 2010-03-01")
    parser.add_argument("--end", help="Last month of a monthly backfill, e.g. 2011-03-01")
    args = parser.parse_args()

    if args.start and args.end:
        snapshots = monthly_snapshots(args.start, args.end)
    elif args.snapshot_date:
        snapshots = [args.snapshot_date]
    else:
        parser.error("provide a single snapshot_date or both --start and --end")

    settings = get_settings()
    configure_logging(settings.log_level)
    for snapshot in snapshots:
        result = build_labels(settings, snapshot)
        print(
            f"{result.snapshot_date}: {result.label_rows:,} labels "
            f"({result.churned_count:,} churned, {result.censored_count:,} censored)"
        )
    print(f"  warehouse:       {settings.duckdb_path}")
    print(f"  parquet export:  {settings.gold_dir / 'labels.parquet'}")
    print(f"  profile report:  {settings.reports_dir / 'labels.md'}")


if __name__ == "__main__":
    main()
