"""Build the gold.customer_360 slice for an as_of_date (Phase 4).

Usage: uv run python scripts/build_customer360.py 2011-03-01
Expects silver.transactions in the warehouse (run scripts/build_silver.py first).
The as_of_date is required and explicit — Customer360 never defaults to today (D18).
"""

import argparse

from churnlens.config.settings import get_settings
from churnlens.io.customer360 import build_customer_360
from churnlens.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the gold.customer_360 slice for a date.")
    parser.add_argument("as_of_date", help="Cutoff date in ISO format, e.g. 2011-03-01")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    result = build_customer_360(settings, args.as_of_date)
    print(f"Built {result.customer_rows:,} customer rows for as_of_date={result.as_of_date}")
    print(f"  warehouse:       {result.duckdb_path}")
    print(f"  parquet export:  {result.parquet_path}")
    print(f"  profile report:  {result.report_path}")
    print(f"  data dictionary: {result.dictionary_path}")


if __name__ == "__main__":
    main()
