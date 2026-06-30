"""Customer360 build: silver → point-in-time ``gold.customer_360`` (Phase 4).

The first layer above the simulated clock (D1/D18). For a given
``as_of_date`` it aggregates ``silver.transactions`` — reading only lines
timestamped strictly before midnight at the start of that date — into one
row per customer with history before the cutoff. Every metric is anchored
on the *passed* ``as_of_date``, never ``MAX(invoice_date)`` or ``today()``,
so the table can never read the future.

Population is all customers with prior history (the D3 active-only filter,
``recency_days <= churn_window_days``, is applied downstream by Labeling).
Metrics are durable facts only — net-product revenue totals (D11),
the D6 revenue run rate, recency/tenure, order and return counts, distinct
active months/days, distinct products and product-line counts, gross product
revenue, the prior-12m revenue window, the largest order's net revenue, and the
most-recent country (D25); ratios, scores, and windowed features are built on
top of these in Phase 6.

The write is an idempotent per-slice upsert: the rows for ``as_of_date`` are
replaced, so backfilled snapshots (D10) accumulate a ``(customer, as_of_date)``
panel and any single date re-runs cleanly.
"""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from churnlens.config.settings import Settings
from churnlens.io.data_dictionary import write_data_dictionary
from churnlens.io.warehouse import warehouse_connection
from churnlens.utils.dates import parse_as_of_date
from churnlens.validation.runner import validate
from churnlens.validation.schemas import Customer360

logger = logging.getLogger(__name__)

SILVER_TABLE = "silver.transactions"
GOLD_TABLE = "gold.customer_360"
PARQUET_FILENAME = "customer_360.parquet"
REPORT_FILENAME = "customer_360.md"

_CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS {GOLD_TABLE} (
        customer_id              VARCHAR,
        as_of_date               DATE,
        first_purchase_date      DATE,
        last_activity_date       DATE,
        last_purchase_date       DATE,
        recency_days             INTEGER,
        tenure_days              INTEGER,
        order_count              INTEGER,
        cancelled_order_count    INTEGER,
        total_net_revenue        DOUBLE,
        trailing_12m_net_revenue DOUBLE,
        cancelled_revenue        DOUBLE,
        run_rate_90d             DOUBLE,
        distinct_active_months   INTEGER,
        distinct_active_days     INTEGER,
        distinct_products        INTEGER,
        product_line_count       INTEGER,
        gross_product_revenue    DOUBLE,
        prior_12m_net_revenue    DOUBLE,
        max_invoice_net_revenue  DOUBLE,
        country                  VARCHAR
    )
"""


def _aggregate_sql(horizon_days: int, trailing_days: int) -> str:
    """Aggregation over silver history strictly before ``$as_of`` (D18).

    ``horizon_days`` (D6 = churn window) is the run-rate horizon and the
    tenure floor that stops thin-history customers from exploding the rate;
    ``trailing_days`` is the trailing-window length for the run rate.
    """
    return f"""
        WITH history AS (
            SELECT *
            FROM {SILVER_TABLE}
            WHERE invoice_date < CAST($as_of AS TIMESTAMP)
        ),
        latest_country AS (
            SELECT customer_id, country FROM (
                SELECT customer_id, country, ROW_NUMBER() OVER (
                    PARTITION BY customer_id ORDER BY invoice_date DESC, invoice DESC
                ) AS rn
                FROM history
            ) WHERE rn = 1
        ),
        agg AS (
            SELECT
                customer_id,
                MIN(invoice_date) AS first_ts,
                MAX(invoice_date) AS last_activity_ts,
                MAX(CASE WHEN is_product AND quantity > 0 THEN invoice_date END)
                    AS last_purchase_ts,
                COUNT(DISTINCT CASE WHEN NOT is_cancellation THEN invoice END) AS order_count,
                COUNT(DISTINCT CASE WHEN is_cancellation THEN invoice END) AS cancelled_order_count,
                SUM(CASE WHEN is_product THEN line_revenue ELSE 0 END) AS total_net_revenue,
                SUM(CASE
                        WHEN is_product
                         AND invoice_date >= CAST($as_of AS TIMESTAMP)
                                              - INTERVAL '{trailing_days} days'
                        THEN line_revenue ELSE 0
                    END) AS trailing_12m_net_revenue,
                SUM(CASE WHEN is_cancellation THEN line_revenue ELSE 0 END) AS cancelled_revenue,
                COUNT(DISTINCT DATE_TRUNC('month', invoice_date)) AS distinct_active_months,
                COUNT(DISTINCT CAST(invoice_date AS DATE)) AS distinct_active_days,
                COUNT(DISTINCT CASE WHEN is_product AND quantity > 0 THEN stock_code END)
                    AS distinct_products,
                COUNT(CASE WHEN is_product AND quantity > 0 THEN 1 END) AS product_line_count,
                SUM(CASE WHEN is_product AND quantity > 0 THEN line_revenue ELSE 0 END)
                    AS gross_product_revenue,
                SUM(CASE
                        WHEN is_product
                         AND invoice_date >= CAST($as_of AS TIMESTAMP)
                                              - INTERVAL '{2 * trailing_days} days'
                         AND invoice_date <  CAST($as_of AS TIMESTAMP)
                                              - INTERVAL '{trailing_days} days'
                        THEN line_revenue ELSE 0
                    END) AS prior_12m_net_revenue
            FROM history
            GROUP BY customer_id
        ),
        invoice_rev AS (
            SELECT customer_id, MAX(inv_net) AS max_invoice_net_revenue
            FROM (
                SELECT customer_id, invoice,
                       SUM(CASE WHEN is_product THEN line_revenue ELSE 0 END) AS inv_net
                FROM history
                WHERE NOT is_cancellation
                GROUP BY customer_id, invoice
            )
            GROUP BY customer_id
        )
        SELECT
            a.customer_id,
            CAST($as_of AS DATE)                                 AS as_of_date,
            CAST(a.first_ts AS DATE)                             AS first_purchase_date,
            CAST(a.last_activity_ts AS DATE)                     AS last_activity_date,
            CAST(a.last_purchase_ts AS DATE)                     AS last_purchase_date,
            DATE_DIFF('day', CAST(a.last_activity_ts AS DATE), CAST($as_of AS DATE))
                AS recency_days,
            DATE_DIFF('day', CAST(a.first_ts AS DATE), CAST($as_of AS DATE))
                AS tenure_days,
            a.order_count,
            a.cancelled_order_count,
            a.total_net_revenue,
            a.trailing_12m_net_revenue,
            a.cancelled_revenue,
            CASE
                WHEN DATE_DIFF('day', CAST(a.first_ts AS DATE), CAST($as_of AS DATE))
                     >= {trailing_days}
                THEN a.trailing_12m_net_revenue * {horizon_days} / {trailing_days}
                ELSE a.total_net_revenue
                     / GREATEST(
                           DATE_DIFF('day', CAST(a.first_ts AS DATE), CAST($as_of AS DATE)),
                           {horizon_days}
                       ) * {horizon_days}
            END AS run_rate_90d,
            a.distinct_active_months,
            a.distinct_active_days,
            a.distinct_products,
            a.product_line_count,
            a.gross_product_revenue,
            a.prior_12m_net_revenue,
            COALESCE(r.max_invoice_net_revenue, 0.0) AS max_invoice_net_revenue,
            c.country
        FROM agg a
        JOIN latest_country c USING (customer_id)
        LEFT JOIN invoice_rev r USING (customer_id)
        ORDER BY a.customer_id
    """


@dataclass(frozen=True)
class Customer360Result:
    as_of_date: date
    customer_rows: int
    duckdb_path: Path
    parquet_path: Path
    report_path: Path
    dictionary_path: Path


def build_customer_360(settings: Settings, as_of_date: str | date) -> Customer360Result:
    """Build the ``gold.customer_360`` slice for ``as_of_date`` (validate → upsert → report)."""
    as_of = parse_as_of_date(as_of_date)
    sql = _aggregate_sql(settings.churn_window_days, settings.revenue_run_rate_window_days)

    with warehouse_connection(settings.duckdb_path) as con:
        candidate = con.execute(sql, {"as_of": as_of.isoformat()}).df()
        validated = validate(candidate, Customer360, f"{GOLD_TABLE} (candidate)")

        _upsert_slice(con, validated, as_of)
        parquet_path = export_customer_360_parquet(con, settings.gold_dir)
        report_path = write_customer_360_report(con, as_of, settings)
        dictionary_path = write_data_dictionary(con, settings.reports_dir)

    return Customer360Result(
        as_of_date=as_of,
        customer_rows=len(validated),
        duckdb_path=settings.duckdb_path,
        parquet_path=parquet_path,
        report_path=report_path,
        dictionary_path=dictionary_path,
    )


def _upsert_slice(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, as_of: date) -> None:
    """Idempotently replace the ``as_of_date`` slice with the validated frame (D10)."""
    con.execute(_CREATE_TABLE_SQL)
    con.register("c360_frame", frame)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM {GOLD_TABLE} WHERE as_of_date = ?", [as_of])
        con.execute(
            f"""
            INSERT INTO {GOLD_TABLE} SELECT
                customer_id::VARCHAR,
                as_of_date::DATE,
                first_purchase_date::DATE,
                last_activity_date::DATE,
                last_purchase_date::DATE,
                recency_days::INTEGER,
                tenure_days::INTEGER,
                order_count::INTEGER,
                cancelled_order_count::INTEGER,
                total_net_revenue::DOUBLE,
                trailing_12m_net_revenue::DOUBLE,
                cancelled_revenue::DOUBLE,
                run_rate_90d::DOUBLE,
                distinct_active_months::INTEGER,
                distinct_active_days::INTEGER,
                distinct_products::INTEGER,
                product_line_count::INTEGER,
                gross_product_revenue::DOUBLE,
                prior_12m_net_revenue::DOUBLE,
                max_invoice_net_revenue::DOUBLE,
                country::VARCHAR
            FROM c360_frame
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("c360_frame")
    logger.info("Upserted %s slice for as_of_date=%s (%d rows)", GOLD_TABLE, as_of, len(frame))


def export_customer_360_parquet(con: duckdb.DuckDBPyConnection, gold_dir: Path) -> Path:
    """Export the whole ``gold.customer_360`` panel to a single Parquet file."""
    gold_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = gold_dir / PARQUET_FILENAME
    con.execute(f"COPY {GOLD_TABLE} TO '{parquet_path}' (FORMAT PARQUET)")
    logger.info("Exported %s to %s", GOLD_TABLE, parquet_path)
    return parquet_path


def write_customer_360_report(
    con: duckdb.DuckDBPyConnection, as_of: date, settings: Settings
) -> Path:
    """Profile the freshly built ``as_of_date`` slice from the live table."""
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.reports_dir / REPORT_FILENAME

    row = con.execute(
        f"""
        SELECT
            COUNT(*),
            SUM(CASE WHEN recency_days <= {settings.churn_window_days} THEN 1 ELSE 0 END),
            SUM(CASE WHEN last_purchase_date IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN total_net_revenue < 0 THEN 1 ELSE 0 END),
            MEDIAN(recency_days), MAX(recency_days),
            MEDIAN(tenure_days), MAX(tenure_days),
            SUM(total_net_revenue), SUM(run_rate_90d)
        FROM {GOLD_TABLE}
        WHERE as_of_date = ?
        """,
        [as_of],
    ).fetchone()
    assert row is not None
    (rows, active, no_purchase, negative_rev, med_rec, max_rec, med_ten, max_ten, rev, rar) = row
    active_pct = (active / rows * 100) if rows else 0.0

    lines = [
        "# Customer360 Profile",
        "",
        "Generated from the live warehouse on every Customer360 build — do not edit by hand.",
        "",
        f"Slice profiled: **`as_of_date = {as_of.isoformat()}`** "
        f"(one row per customer with history strictly before this date, D18).",
        "",
        "## Slice summary",
        "",
        f"- **Customers:** {rows:,}",
        f"- **Active (recency_days ≤ {settings.churn_window_days}, the D3 population):** "
        f"{active:,} ({active_pct:.1f}%)",
        f"- **Cancellation-only (no purchase yet, `last_purchase_date` null):** {no_purchase:,}",
        f"- **Net-negative customers (pure returns to date):** {negative_rev:,}",
        f"- **Recency days:** median {med_rec:.0f}, max {max_rec:,}",
        f"- **Tenure days:** median {med_ten:.0f}, max {max_ten:,}",
        f"- **Total net product revenue (to date):** £{rev:,.2f}",
        f"- **Total 90-day run rate (revenue-at-risk base, D6):** £{rar:,.2f}",
        *_contract_section(),
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote Customer360 profile to %s", report_path)
    return report_path


def _contract_section() -> list[str]:
    schema = Customer360.to_schema()
    lines = [
        "",
        "## Customer360 contract (Pandera, enforced on every build)",
        "",
        "| Column | Type | Nullable | Checks |",
        "|--------|------|----------|--------|",
    ]
    for name, column in schema.columns.items():
        checks = "; ".join(f"`{str(check).strip('<>').split(': ')[-1]}`" for check in column.checks)
        nullable = "yes" if column.nullable else "no"
        lines.append(f"| `{name}` | {column.dtype} | {nullable} | {checks or '—'} |")
    lines.extend(["", "Frame-level business rules:", ""])
    for check in schema.checks:
        lines.append(f"- {check.error}")
    return lines
