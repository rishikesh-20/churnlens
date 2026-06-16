"""Load Online Retail II into the bronze layer (Phase 2).

Usage: uv run python scripts/ingest.py
Expects the source workbook at data/raw/online_retail_II.xlsx (see README).
"""

from churnlens.config.settings import get_settings
from churnlens.io.ingest import ingest_bronze
from churnlens.utils.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    result = ingest_bronze(settings)
    print(f"Loaded {result.rows_loaded:,} rows into bronze.transactions")
    print(f"  warehouse:       {result.duckdb_path}")
    print(f"  parquet export:  {result.parquet_path}")
    print(f"  data dictionary: {result.dictionary_path}")


if __name__ == "__main__":
    main()
