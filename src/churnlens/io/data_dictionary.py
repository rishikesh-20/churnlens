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
    "gold.labels": (
        "Supervised churn target: one row per active customer (D3, `recency_days ≤ 90` "
        "from customer_360) per `snapshot_date`. `churned = 1` when no product purchase "
        "falls in `[snapshot, snapshot + 90d)` (D2/D24); rows whose window extends past the "
        "observed-data horizon with no purchase are censored (`churned` NULL). The forward "
        "window is the only deliberate look-ahead — target only, never features. Profiled "
        "in [labels.md](labels.md)."
    ),
    "gold.features": (
        "Model-ready feature vector: one row per customer per `as_of_date`, each feature a "
        "closed-form per-row transform of the `gold.customer_360` slice (D26). No "
        "cross-customer statistics and no forward read, so the same builder serves training "
        "and scoring with no skew. Undefined values are NaN, never imputed (D3). Profiled in "
        "[features.md](features.md)."
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
        "distinct_active_months": "Count of distinct calendar months with any activity before "
        "the cutoff (D25).",
        "distinct_active_days": "Count of distinct calendar days with any activity before the "
        "cutoff (D25).",
        "distinct_products": "Count of distinct product stock codes actually purchased "
        "(positive product lines) before the cutoff (D25).",
        "product_line_count": "Count of positive product invoice lines before the cutoff (D25).",
        "gross_product_revenue": "Total revenue of positive product lines before the cutoff "
        "(returns not netted); the denominator for revenue concentration (D25).",
        "prior_12m_net_revenue": "Net product revenue in the window 24-12 months before the "
        "cutoff, i.e. the year before trailing_12m_net_revenue; feeds revenue growth (D25).",
        "max_invoice_net_revenue": "Largest single non-cancellation invoice's net product "
        "revenue before the cutoff; 0 if the customer has no order. Feeds revenue "
        "concentration (D25).",
        "country": "Country on the customer's most recent invoice before the cutoff.",
    },
    "gold.labels": {
        "customer_id": "Customer identifier; the D3 active population at the snapshot.",
        "snapshot_date": "Point-in-time labeling cutoff; the forward window starts here (D18).",
        "churned": "1 if no product purchase in [snapshot, snapshot+90d); 0 if a purchase "
        "occurred; NULL when censored (window unobserved).",
        "censored": "True when the 90-day window extends past the observed-data horizon and "
        "no purchase was seen, so the outcome is unknowable (D4).",
        "next_purchase_date": "Date of the first product purchase in the window; null unless "
        "churned = 0.",
    },
    "gold.features": {
        "customer_id": "Customer identifier.",
        "as_of_date": "Point-in-time cutoff; features use only customer_360 facts as of this "
        "date (D18).",
        "customer_lifetime_orders": "Total distinct non-cancellation invoices to date.",
        "order_frequency": "Orders per 30 calendar days of tenure; NaN if tenure is 0 days.",
        "purchase_velocity": "Orders per distinct active month — order cadence while engaged.",
        "purchase_intensity": "Share of tenure days on which the customer was active, in (0,1].",
        "average_days_between_orders": "Mean gap between first and last purchase across orders; "
        "NaN for customers with fewer than two orders.",
        "recency_score": "exp(-days_since_last_purchase / 90): 1 just after a purchase, decaying "
        "to ~0.37 at one churn window; NaN if the customer has never purchased.",
        "average_order_value": "Net revenue per order; NaN if no orders. May be negative (net of "
        "returns).",
        "revenue_per_active_day": "Net revenue per distinct active day.",
        "trailing_12m_average_monthly_revenue": "Trailing-12-month net revenue divided by 12.",
        "revenue_growth_ratio": "Trailing-12m net revenue over prior-12m net revenue; NaN when "
        "the prior year's revenue is not positive.",
        "revenue_concentration": "Largest order's share of gross product revenue, in (0,1]; NaN "
        "when the customer has no positive product revenue.",
        "active_months": "Count of distinct calendar months with activity.",
        "product_diversity": "Count of distinct product codes purchased.",
        "average_products_per_order": "Product lines per order; NaN if no orders.",
        "cancellation_rate": "Cancellation invoices over all invoices, in [0,1].",
        "repeat_purchase_ratio": "Share of orders beyond the first, (order_count-1)/order_count; "
        "NaN if no orders.",
        "customer_age_days": "Days from first activity to the cutoff (= tenure).",
        "days_since_last_purchase": "Days from the last product purchase to the cutoff; NaN if "
        "the customer has never purchased.",
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
