"""Whole-warehouse data dictionary generation (D21, D22).

The dictionary is regenerated from the live warehouse by every pipeline
run that changes a table, so ``reports/data_dictionary.md`` (tracked in
git) is always provably in sync with the schemas it documents. Every
table found in the medallion layer schemas gets a section; descriptions
are registered here as tables gain phases.
"""

import logging
from pathlib import Path

import duckdb

from churnlens.io.warehouse import LAYER_SCHEMAS

logger = logging.getLogger(__name__)

SOURCE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
DATA_DICTIONARY_FILENAME = "data_dictionary.md"

_TABLE_DESCRIPTIONS = {
    "bronze.transactions": (
        "Raw Online Retail II invoice lines, exactly as in the source workbook "
        f"([UCI 502]({SOURCE_URL})). One row per invoice line; no cleaning or filtering."
    ),
    "silver.transactions": (
        "Cleaned invoice lines: inter-sheet duplicate copies and anonymous rows removed, "
        "derived revenue and flags added. A strict Pandera contract validates every build "
        "before the table is written; row losses are accounted in "
        "[data_quality.md](data_quality.md)."
    ),
    "gold.customer_360": (
        "Point-in-time customer analytics mart: one row per customer per `as_of_date`, "
        "aggregated from silver history strictly before the cutoff (D18). Durable facts "
        "only (recency/tenure, order and return counts, net-product revenue, the D6 run "
        "rate, most-recent country); a single-date slice is profiled in "
        "[customer_360.md](customer_360.md)."
    ),
}

_SHARED_COLUMNS = {
    "invoice": "Invoice number (text); prefixed 'C' for cancellations.",
    "stock_code": "Product (item) code.",
    "quantity": "Units on the invoice line; negative for cancellations.",
    "invoice_date": "Invoice timestamp.",
    "unit_price": "Price per unit in GBP.",
    "country": "Customer's country of residence.",
    "source_file": "Lineage: source workbook file name.",
    "source_sheet": "Lineage: workbook sheet the row was read from.",
    "loaded_at": "Lineage: UTC timestamp of the bronze load run.",
}

_COLUMN_DESCRIPTIONS = {
    "bronze.transactions": {
        **_SHARED_COLUMNS,
        "description": "Product name; null on some non-product rows.",
        "customer_id": "Customer identifier; null for unregistered (anonymous) sales.",
    },
    "silver.transactions": {
        **_SHARED_COLUMNS,
        "description": "Product name.",
        "customer_id": "Customer identifier; never null in silver.",
        "line_revenue": "quantity * unit_price in GBP; negative for cancellations.",
        "is_cancellation": "True when the invoice is a cancellation ('C' prefix).",
        "is_product": "True for merchandise stock codes; False for service/adjustment "
        "codes (postage, fees, manual adjustments) excluded from revenue.",
    },
    "gold.customer_360": {
        "customer_id": "Customer identifier.",
        "as_of_date": "Point-in-time cutoff; metrics use only history strictly before it (D18).",
        "first_purchase_date": "Date of the customer's first line (tenure anchor).",
        "last_activity_date": "Date of the most recent line of any kind; cancellations count "
        "as activity (D11). Drives recency.",
        "last_purchase_date": "Date of the most recent product purchase (positive quantity); "
        "null if the customer has only cancellations so far.",
        "recency_days": "as_of_date minus last_activity_date, in days.",
        "tenure_days": "as_of_date minus first_purchase_date, in days.",
        "order_count": "Distinct non-cancellation invoices.",
        "cancelled_order_count": "Distinct cancellation ('C') invoices.",
        "total_net_revenue": "Net product revenue to date in GBP (cancellations net out; "
        "non-product codes excluded, D11). May be negative.",
        "trailing_12m_net_revenue": "Net product revenue in the trailing 12 months before the "
        "cutoff, feeding the D6 run rate.",
        "cancelled_revenue": "Net revenue of cancellation lines in GBP (≤ 0).",
        "run_rate_90d": "Expected 90-day net revenue (D6): trailing-12m scaled by 90/365, or "
        "a full-history rate floored at the churn window for <12mo customers.",
        "country": "Country on the customer's most recent invoice before the cutoff.",
    },
}


def write_data_dictionary(con: duckdb.DuckDBPyConnection, reports_dir: Path) -> Path:
    """Generate the data dictionary for every table in the layer schemas."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    dictionary_path = reports_dir / DATA_DICTIONARY_FILENAME

    lines = [
        "# Data Dictionary",
        "",
        "Generated from the live warehouse on every pipeline run — do not edit by hand.",
    ]
    for schema, table in _list_tables(con):
        lines.extend(_table_section(con, schema, table))

    dictionary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote data dictionary to %s", dictionary_path)
    return dictionary_path


def _list_tables(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    rows = con.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN (SELECT UNNEST(?))
        ORDER BY list_position(?, table_schema), table_name
        """,
        [list(LAYER_SCHEMAS), list(LAYER_SCHEMAS)],
    ).fetchall()
    return [(str(schema), str(table)) for schema, table in rows]


def _table_section(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> list[str]:
    qualified = f"{schema}.{table}"
    row = con.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()
    assert row is not None
    total_rows = int(row[0])
    columns = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
        """,
        [schema, table],
    ).fetchall()
    descriptions = _COLUMN_DESCRIPTIONS.get(qualified, {})

    lines = [
        "",
        f"## `{qualified}`",
        "",
        _TABLE_DESCRIPTIONS.get(qualified, ""),
        "",
        f"**Rows:** {total_rows:,}",
        "",
        "| Column | Type | Nulls | Distinct | Min | Max | Description |",
        "|--------|------|-------|----------|-----|-----|-------------|",
    ]
    for name, data_type in columns:
        stats = con.execute(
            f"""
            SELECT
                COUNT(*) - COUNT({name}),
                COUNT(DISTINCT {name}),
                MIN({name})::VARCHAR,
                MAX({name})::VARCHAR
            FROM {qualified}
            """
        ).fetchone()
        assert stats is not None
        nulls, distinct, min_val, max_val = stats
        lines.append(
            f"| `{name}` | {data_type} | {nulls:,} | {distinct:,} "
            f"| {min_val} | {max_val} | {descriptions.get(name, '')} |"
        )
    return lines
