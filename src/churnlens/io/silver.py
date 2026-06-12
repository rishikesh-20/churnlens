"""Silver build: bronze → validated ``silver.transactions`` (D11, D22).

Two-tier semantics at the bronze→silver boundary:

1. **Filter rules** deterministically remove *known* dirt and account for
   every dropped row in the data quality report: inter-sheet duplicate
   copies (the workbook export overlap) and anonymous rows (no customer).
2. **Contracts**: the bronze input and the full silver candidate frame are
   validated against strict Pandera schemas. Any surprise violation aborts
   the build before the table is written — the previous silver stays.

Like bronze (D21), the build takes no ``as_of_date``: silver is a
full-replace, idempotent, deterministic function of bronze, still below
the simulated clock (D1/D18). The clock starts at gold.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from churnlens.config.settings import Settings
from churnlens.io.data_dictionary import write_data_dictionary
from churnlens.io.warehouse import warehouse_connection
from churnlens.validation.runner import validate
from churnlens.validation.schemas import (
    PRODUCT_STOCK_CODE_PATTERN,
    BronzeTransactions,
    SilverTransactions,
)

logger = logging.getLogger(__name__)

BRONZE_TABLE = "bronze.transactions"
SILVER_TABLE = "silver.transactions"
PARQUET_FILENAME = "transactions.parquet"
DATA_QUALITY_FILENAME = "data_quality.md"

# Rows identical on every source column describe the same real-world line.
# When the copies span both workbook sheets, the later sheet's copies are the
# export-overlap artifact and are dropped; within-sheet repeats are legitimate
# invoice lines (same item rung up twice) and survive (D22).
_DEDUPED_SQL = f"""
    SELECT * FROM {BRONZE_TABLE}
    QUALIFY source_sheet = MIN(source_sheet) OVER (
        PARTITION BY invoice, stock_code, description, quantity,
                     invoice_date, unit_price, customer_id, country
    )
"""

_CANDIDATE_SQL = f"""
    WITH deduped AS ({_DEDUPED_SQL})
    SELECT
        invoice,
        stock_code,
        description,
        quantity,
        invoice_date,
        unit_price,
        customer_id,
        country,
        quantity * unit_price AS line_revenue,
        invoice LIKE 'C%' AS is_cancellation,
        regexp_matches(stock_code, '{PRODUCT_STOCK_CODE_PATTERN}') AS is_product,
        source_file,
        source_sheet,
        loaded_at
    FROM deduped
    WHERE customer_id IS NOT NULL
"""


@dataclass(frozen=True)
class RowAccounting:
    """Row-loss waterfall from bronze to silver (D11: row loss is accounted)."""

    bronze_rows: int
    duplicate_rows_dropped: int
    anonymous_rows_dropped: int
    silver_rows: int


@dataclass(frozen=True)
class SilverResult:
    accounting: RowAccounting
    duckdb_path: Path
    parquet_path: Path
    quality_report_path: Path
    dictionary_path: Path


def build_silver(settings: Settings) -> SilverResult:
    """Run the full silver build: validate input → transform → validate → write."""
    with warehouse_connection(settings.duckdb_path) as con:
        bronze_frame = con.execute(f"SELECT * FROM {BRONZE_TABLE}").df()
        validate(bronze_frame, BronzeTransactions, BRONZE_TABLE)

        candidate = con.execute(_CANDIDATE_SQL).df()
        validated = validate(candidate, SilverTransactions, f"{SILVER_TABLE} (candidate)")

        accounting = _row_accounting(con, silver_rows=len(validated))
        _write_silver(con, validated)
        parquet_path = export_silver_parquet(con, settings.silver_dir)
        quality_report_path = write_data_quality_report(con, accounting, settings.reports_dir)
        dictionary_path = write_data_dictionary(con, settings.reports_dir)
    return SilverResult(
        accounting=accounting,
        duckdb_path=settings.duckdb_path,
        parquet_path=parquet_path,
        quality_report_path=quality_report_path,
        dictionary_path=dictionary_path,
    )


def _row_accounting(con: duckdb.DuckDBPyConnection, silver_rows: int) -> RowAccounting:
    bronze_rows = _scalar(con, f"SELECT COUNT(*) FROM {BRONZE_TABLE}")
    deduped_rows = _scalar(con, f"SELECT COUNT(*) FROM ({_DEDUPED_SQL})")
    accounting = RowAccounting(
        bronze_rows=bronze_rows,
        duplicate_rows_dropped=bronze_rows - deduped_rows,
        anonymous_rows_dropped=deduped_rows - silver_rows,
        silver_rows=silver_rows,
    )
    logger.info(
        "Row accounting: %d bronze - %d inter-sheet duplicates - %d anonymous = %d silver",
        accounting.bronze_rows,
        accounting.duplicate_rows_dropped,
        accounting.anonymous_rows_dropped,
        accounting.silver_rows,
    )
    return accounting


def _write_silver(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    """Atomically replace ``silver.transactions`` with the validated frame."""
    con.register("validated_frame", frame)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {SILVER_TABLE} AS
        SELECT
            invoice::VARCHAR         AS invoice,
            stock_code::VARCHAR      AS stock_code,
            description::VARCHAR     AS description,
            quantity::BIGINT         AS quantity,
            invoice_date::TIMESTAMP  AS invoice_date,
            unit_price::DOUBLE       AS unit_price,
            customer_id::VARCHAR     AS customer_id,
            country::VARCHAR         AS country,
            line_revenue::DOUBLE     AS line_revenue,
            is_cancellation::BOOLEAN AS is_cancellation,
            is_product::BOOLEAN      AS is_product,
            source_file::VARCHAR     AS source_file,
            source_sheet::VARCHAR    AS source_sheet,
            loaded_at::TIMESTAMP     AS loaded_at
        FROM validated_frame
        """
    )
    con.unregister("validated_frame")
    logger.info("Wrote %s", SILVER_TABLE)


def export_silver_parquet(con: duckdb.DuckDBPyConnection, silver_dir: Path) -> Path:
    """Export ``silver.transactions`` to a single Parquet file."""
    silver_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = silver_dir / PARQUET_FILENAME
    con.execute(f"COPY {SILVER_TABLE} TO '{parquet_path}' (FORMAT PARQUET)")
    logger.info("Exported %s to %s", SILVER_TABLE, parquet_path)
    return parquet_path


def write_data_quality_report(
    con: duckdb.DuckDBPyConnection, accounting: RowAccounting, reports_dir: Path
) -> Path:
    """Generate the data quality report from the live silver table."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / DATA_QUALITY_FILENAME

    lines = [
        "# Data Quality Report",
        "",
        "Generated from the live warehouse on every silver build — do not edit by hand.",
        "",
        "## Row accounting (bronze → silver)",
        "",
        "Cleaning rules remove only *known* dirt; anything else fails the Pandera",
        "contract below and aborts the build without writing the table.",
        "",
        "| Stage | Rows | Dropped | Rule |",
        "|-------|------|---------|------|",
        f"| `bronze.transactions` | {accounting.bronze_rows:,} | — | raw load |",
        f"| after dedup | {accounting.bronze_rows - accounting.duplicate_rows_dropped:,} "
        f"| {accounting.duplicate_rows_dropped:,} | identical rows present in both workbook "
        "sheets (export overlap) keep only the earlier sheet's copies |",
        f"| after anonymous filter | {accounting.silver_rows:,} "
        f"| {accounting.anonymous_rows_dropped:,} | rows without `customer_id` dropped — "
        "churn is per-customer |",
        f"| `silver.transactions` | {accounting.silver_rows:,} | — | published |",
        *_silver_summary(con),
        *_non_product_codes(con),
        *_contract_section(),
    ]

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote data quality report to %s", report_path)
    return report_path


def _silver_summary(con: duckdb.DuckDBPyConnection) -> list[str]:
    row = con.execute(
        f"""
        SELECT
            COUNT(DISTINCT customer_id),
            COUNT(DISTINCT invoice),
            MIN(invoice_date)::VARCHAR,
            MAX(invoice_date)::VARCHAR,
            SUM(CASE WHEN is_cancellation THEN 1 ELSE 0 END),
            SUM(CASE WHEN NOT is_product THEN 1 ELSE 0 END),
            SUM(CASE WHEN unit_price = 0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN is_product THEN line_revenue ELSE 0 END)
        FROM {SILVER_TABLE}
        """
    ).fetchone()
    assert row is not None
    customers, invoices, first, last, cancellations, non_product, zero_price, revenue = row
    return [
        "",
        "## Silver summary",
        "",
        f"- **Customers:** {customers:,}",
        f"- **Invoices:** {invoices:,}",
        f"- **Date range:** {first} → {last}",
        f"- **Cancellation lines:** {cancellations:,} (kept as negative quantities; "
        "revenue is net)",
        f"- **Non-product lines:** {non_product:,} (kept for activity, excluded from revenue)",
        f"- **Zero-price lines:** {zero_price:,} (kept: real activity, zero revenue)",
        f"- **Net product revenue:** £{revenue:,.2f}",
    ]


def _non_product_codes(con: duckdb.DuckDBPyConnection) -> list[str]:
    codes = con.execute(
        f"""
        SELECT stock_code, COUNT(*), SUM(line_revenue)
        FROM {SILVER_TABLE}
        WHERE NOT is_product
        GROUP BY stock_code
        ORDER BY ABS(SUM(line_revenue)) DESC
        """
    ).fetchall()
    lines = [
        "",
        "## Non-product stock codes (excluded from revenue)",
        "",
        f"A stock code is a product iff it matches `{PRODUCT_STOCK_CODE_PATTERN}`",
        "(five digits plus optional letter suffix). Everything else is a",
        "service/adjustment code, flagged `is_product = false`:",
        "",
        "| Stock code | Lines | Net line revenue |",
        "|------------|-------|------------------|",
    ]
    for code, count, revenue in codes:
        lines.append(f"| `{code}` | {count:,} | £{revenue:,.2f} |")
    return lines


def _contract_section() -> list[str]:
    schema = SilverTransactions.to_schema()
    lines = [
        "",
        "## Silver contract (Pandera, enforced on every build)",
        "",
        "| Column | Type | Nullable | Checks |",
        "|--------|------|----------|--------|",
    ]
    for name, column in schema.columns.items():
        # str(Check) renders as "<Check name: name(args)>"; keep "name(args)".
        checks = "; ".join(f"`{str(check).strip('<>').split(': ')[-1]}`" for check in column.checks)
        nullable = "yes" if column.nullable else "no"
        lines.append(f"| `{name}` | {column.dtype} | {nullable} | {checks or '—'} |")
    lines.extend(["", "Frame-level business rules:", ""])
    for check in schema.checks:
        lines.append(f"- {check.error}")
    return lines


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])
