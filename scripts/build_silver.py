"""Build the validated silver layer from bronze (Phase 3).

Usage: uv run python scripts/build_silver.py
Expects bronze.transactions in the warehouse (run scripts/ingest.py first).
"""

from churnlens.config.settings import get_settings
from churnlens.io.silver import build_silver
from churnlens.utils.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    result = build_silver(settings)
    accounting = result.accounting
    print(
        f"Built silver.transactions: {accounting.silver_rows:,} rows "
        f"({accounting.bronze_rows:,} bronze "
        f"- {accounting.duplicate_rows_dropped:,} inter-sheet duplicates "
        f"- {accounting.anonymous_rows_dropped:,} anonymous)"
    )
    print(f"  warehouse:       {result.duckdb_path}")
    print(f"  parquet export:  {result.parquet_path}")
    print(f"  quality report:  {result.quality_report_path}")
    print(f"  data dictionary: {result.dictionary_path}")


if __name__ == "__main__":
    main()
