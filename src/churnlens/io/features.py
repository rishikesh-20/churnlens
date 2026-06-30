"""Feature build: ``gold.customer_360`` → model-ready ``gold.features`` (Phase 6).

The feature engineering layer. For a given ``as_of_date`` it transforms the
``gold.customer_360`` slice for that date into one model-input row per customer.
Every feature is a *closed-form, per-row* function of that customer's own
durable facts (D25) — no cross-customer statistics, no forward read, no silver
access. Because the builder reads only ``customer_360`` (already strictly before
the cutoff, D18) and computes per row, the same ``build_features`` serves both
training backfills and production scoring with identical values: there is one
feature code path and no training-serving skew (D26).

Undefined values (one-time buyers, zero/negative denominators, customers whose
only activity is a cancellation) are emitted as NaN and never imputed — the
tree model handles them natively (D3); every division guards its denominator so
the result is NaN, never ±inf.

Population is the full ``customer_360`` set (every customer with prior history);
the D3 active-only filter stays in labeling/scoring, and training inner-joins
features to labels on ``(customer_id, as_of_date)``.

The write is an idempotent per-slice upsert: the rows for ``as_of_date`` are
replaced, so backfilled snapshots (D10) accumulate a ``(customer, as_of_date)``
panel and any single date re-runs cleanly — the same mechanism serves replay
and retraining.
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
from churnlens.validation.schemas import Features

logger = logging.getLogger(__name__)

C360_TABLE = "gold.customer_360"
GOLD_TABLE = "gold.features"
PARQUET_FILENAME = "features.parquet"
REPORT_FILENAME = "features.md"

# Feature columns in table order; the report and inserts iterate this list.
FEATURE_COLUMNS = [
    "customer_lifetime_orders",
    "order_frequency",
    "purchase_velocity",
    "purchase_intensity",
    "average_days_between_orders",
    "recency_score",
    "average_order_value",
    "revenue_per_active_day",
    "trailing_12m_average_monthly_revenue",
    "revenue_growth_ratio",
    "revenue_concentration",
    "active_months",
    "product_diversity",
    "average_products_per_order",
    "cancellation_rate",
    "repeat_purchase_ratio",
    "customer_age_days",
    "days_since_last_purchase",
]

_CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS {GOLD_TABLE} (
        customer_id                          VARCHAR,
        as_of_date                           DATE,
        customer_lifetime_orders             INTEGER,
        order_frequency                      DOUBLE,
        purchase_velocity                    DOUBLE,
        purchase_intensity                   DOUBLE,
        average_days_between_orders          DOUBLE,
        recency_score                        DOUBLE,
        average_order_value                  DOUBLE,
        revenue_per_active_day               DOUBLE,
        trailing_12m_average_monthly_revenue DOUBLE,
        revenue_growth_ratio                 DOUBLE,
        revenue_concentration                DOUBLE,
        active_months                        INTEGER,
        product_diversity                    INTEGER,
        average_products_per_order           DOUBLE,
        cancellation_rate                    DOUBLE,
        repeat_purchase_ratio                DOUBLE,
        customer_age_days                    INTEGER,
        days_since_last_purchase             DOUBLE
    )
"""


def _feature_sql(churn_window_days: int) -> str:
    """Per-row feature transform of the ``customer_360`` slice at ``$as_of`` (D26).

    ``churn_window_days`` (90) is the time constant of the recency-decay score, so
    a customer one churn-window stale scores ``exp(-1) ≈ 0.37``. Every ratio guards
    a zero/negative denominator with a ``CASE`` so undefined values are NULL → NaN.
    """
    return f"""
        WITH base AS (
            SELECT * FROM {C360_TABLE} WHERE as_of_date = CAST($as_of AS DATE)
        )
        SELECT
            customer_id,
            as_of_date,
            order_count AS customer_lifetime_orders,
            CASE WHEN tenure_days > 0
                 THEN order_count / (tenure_days / 30.0) END AS order_frequency,
            CASE WHEN distinct_active_months > 0
                 THEN order_count::DOUBLE / distinct_active_months END AS purchase_velocity,
            CASE WHEN tenure_days > 0
                 THEN distinct_active_days::DOUBLE / tenure_days END AS purchase_intensity,
            CASE WHEN order_count >= 2 AND last_purchase_date IS NOT NULL
                 THEN DATE_DIFF('day', first_purchase_date, last_purchase_date)::DOUBLE
                      / (order_count - 1) END AS average_days_between_orders,
            CASE WHEN last_purchase_date IS NOT NULL
                 THEN EXP(-DATE_DIFF('day', last_purchase_date, as_of_date)::DOUBLE
                          / {churn_window_days}) END AS recency_score,
            CASE WHEN order_count > 0
                 THEN total_net_revenue / order_count END AS average_order_value,
            total_net_revenue / distinct_active_days AS revenue_per_active_day,
            trailing_12m_net_revenue / 12.0 AS trailing_12m_average_monthly_revenue,
            CASE WHEN prior_12m_net_revenue > 0
                 THEN trailing_12m_net_revenue / prior_12m_net_revenue END AS revenue_growth_ratio,
            CASE WHEN gross_product_revenue > 0
                 THEN max_invoice_net_revenue / gross_product_revenue END AS revenue_concentration,
            distinct_active_months AS active_months,
            distinct_products AS product_diversity,
            CASE WHEN order_count > 0
                 THEN product_line_count::DOUBLE / order_count END AS average_products_per_order,
            CASE WHEN (order_count + cancelled_order_count) > 0
                 THEN cancelled_order_count::DOUBLE / (order_count + cancelled_order_count)
                 END AS cancellation_rate,
            CASE WHEN order_count > 0
                 THEN (order_count - 1)::DOUBLE / order_count END AS repeat_purchase_ratio,
            tenure_days AS customer_age_days,
            CASE WHEN last_purchase_date IS NOT NULL
                 THEN DATE_DIFF('day', last_purchase_date, as_of_date)
                 END AS days_since_last_purchase
        FROM base
        ORDER BY customer_id
    """


@dataclass(frozen=True)
class FeaturesResult:
    as_of_date: date
    feature_rows: int
    duckdb_path: Path
    parquet_path: Path
    report_path: Path
    dictionary_path: Path


def build_features(settings: Settings, as_of_date: str | date) -> FeaturesResult:
    """Build the ``gold.features`` slice for ``as_of_date`` (validate → upsert → report)."""
    as_of = parse_as_of_date(as_of_date)
    sql = _feature_sql(settings.churn_window_days)

    with warehouse_connection(settings.duckdb_path) as con:
        _require_customer_360_slice(con, as_of)
        candidate = con.execute(sql, {"as_of": as_of.isoformat()}).df()
        validated = validate(candidate, Features, f"{GOLD_TABLE} (candidate)")

        _upsert_slice(con, validated, as_of)
        parquet_path = export_features_parquet(con, settings.gold_dir)
        report_path = write_features_report(con, as_of, settings)
        dictionary_path = write_data_dictionary(con, settings.reports_dir)

    return FeaturesResult(
        as_of_date=as_of,
        feature_rows=len(validated),
        duckdb_path=settings.duckdb_path,
        parquet_path=parquet_path,
        report_path=report_path,
        dictionary_path=dictionary_path,
    )


def _require_customer_360_slice(con: duckdb.DuckDBPyConnection, as_of: date) -> None:
    """Fail clearly if the customer_360 population for ``as_of`` has not been built."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'gold' AND table_name = 'customer_360'"
    ).fetchone()
    rows = (
        con.execute(f"SELECT COUNT(*) FROM {C360_TABLE} WHERE as_of_date = ?", [as_of]).fetchone()
        if exists
        else None
    )
    if not rows or rows[0] == 0:
        raise ValueError(
            f"no {C360_TABLE} slice for as_of_date={as_of}; build customer_360 for that date first"
        )


def _upsert_slice(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, as_of: date) -> None:
    """Idempotently replace the ``as_of_date`` slice with the validated frame (D10)."""
    con.execute(_CREATE_TABLE_SQL)
    con.register("features_frame", frame)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM {GOLD_TABLE} WHERE as_of_date = ?", [as_of])
        con.execute(f"INSERT INTO {GOLD_TABLE} SELECT * FROM features_frame")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("features_frame")
    logger.info("Upserted %s slice for as_of_date=%s (%d rows)", GOLD_TABLE, as_of, len(frame))


def export_features_parquet(con: duckdb.DuckDBPyConnection, gold_dir: Path) -> Path:
    """Export the whole ``gold.features`` panel to a single Parquet file."""
    gold_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = gold_dir / PARQUET_FILENAME
    con.execute(f"COPY {GOLD_TABLE} TO '{parquet_path}' (FORMAT PARQUET)")
    logger.info("Exported %s to %s", GOLD_TABLE, parquet_path)
    return parquet_path


def write_features_report(con: duckdb.DuckDBPyConnection, as_of: date, settings: Settings) -> Path:
    """Profile the freshly built ``as_of_date`` slice: per-feature coverage and median."""
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.reports_dir / REPORT_FILENAME

    slice_df = con.execute(
        f"SELECT * FROM {GOLD_TABLE} WHERE as_of_date = ? ORDER BY customer_id", [as_of]
    ).df()
    rows = len(slice_df)

    lines = [
        "# Features Profile",
        "",
        "Generated from the live warehouse on every feature build — do not edit by hand.",
        "",
        f"Slice profiled: **`as_of_date = {as_of.isoformat()}`** (one model-input row per "
        "customer with history strictly before this date, D18/D26).",
        "",
        "## Slice summary",
        "",
        f"- **Customers (rows):** {rows:,}",
        f"- **Features:** {len(FEATURE_COLUMNS)}",
        "",
        "Undefined values are NaN, never imputed (D3); coverage below is the non-null share.",
        "",
        "| Feature | Non-null | Coverage | Median |",
        "|---------|----------|----------|--------|",
    ]
    for col in FEATURE_COLUMNS:
        series = slice_df[col]
        non_null = int(series.notna().sum())
        coverage = f"{non_null / rows * 100:.1f}%" if rows else "—"
        median = series.median()
        median_str = f"{median:,.3f}" if pd.notna(median) else "—"
        lines.append(f"| `{col}` | {non_null:,} | {coverage} | {median_str} |")
    lines.extend(_contract_section())
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote features profile to %s", report_path)
    return report_path


def _contract_section() -> list[str]:
    schema = Features.to_schema()
    lines = [
        "",
        "## Features contract (Pandera, enforced on every build)",
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
