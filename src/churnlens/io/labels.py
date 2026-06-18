"""Label build: silver + customer_360 → point-in-time ``gold.labels`` (Phase 5).

The supervised learning target. For a given ``snapshot_date`` the population is
the D3 active set (``recency_days <= churn_window_days``) read straight off the
``gold.customer_360`` slice for that date (D23); the churn target is read from
``silver.transactions`` in the *forward* window ``[snapshot, snapshot + 90d)``
(D2/D18). This forward read is the one deliberate look-ahead in the platform and
is used for the target only — never for features, which live strictly before the
snapshot (clean partition at snapshot midnight).

A purchase is a positive product line (``is_product AND quantity > 0``), mirroring
customer_360's ``last_purchase_date`` — churn means "stopped buying", so returns
in the window do not save a customer (D24). Censoring is event-aware: a snapshot
whose window extends past the observed-data horizon (``MAX(invoice_date)`` in
silver, never ``today()``) and shows no purchase is censored (``churned`` NULL,
outcome unknowable); if a purchase was observed the outcome is known regardless of
the unobserved tail (``churned = 0``).

The write is an idempotent per-slice upsert: the rows for ``snapshot_date`` are
replaced, so backfilled snapshots (D10) accumulate a ``(customer, snapshot_date)``
panel and any single date re-runs cleanly — the same mechanism serves replay
maturation (D8) and retraining.
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
from churnlens.validation.schemas import Labels

logger = logging.getLogger(__name__)

SILVER_TABLE = "silver.transactions"
C360_TABLE = "gold.customer_360"
GOLD_TABLE = "gold.labels"
PARQUET_FILENAME = "labels.parquet"
REPORT_FILENAME = "labels.md"

_CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS {GOLD_TABLE} (
        customer_id        VARCHAR,
        snapshot_date      DATE,
        churned            INTEGER,
        censored           BOOLEAN,
        next_purchase_date DATE
    )
"""


def _label_sql(churn_window_days: int) -> str:
    """Forward-window churn target over the D3 active population (D24).

    Population = active customers from the ``customer_360`` slice at ``$snapshot``;
    the target reads ``silver`` purchases in ``[$snapshot, $snapshot + window)``.
    The censoring horizon is the observed-data end, derived from silver, never
    ``today()`` — so the table cannot assume data it does not have.
    """
    return f"""
        WITH horizon AS (
            SELECT MAX(invoice_date) AS observed_through FROM {SILVER_TABLE}
        ),
        population AS (
            SELECT customer_id
            FROM {C360_TABLE}
            WHERE as_of_date = CAST($snapshot AS DATE)
              AND recency_days <= {churn_window_days}
        ),
        window_purchases AS (
            SELECT customer_id, MIN(invoice_date) AS next_purchase_ts
            FROM {SILVER_TABLE}
            WHERE is_product AND quantity > 0
              AND invoice_date >= CAST($snapshot AS TIMESTAMP)
              AND invoice_date <  CAST($snapshot AS TIMESTAMP)
                                  + INTERVAL '{churn_window_days} days'
            GROUP BY customer_id
        )
        SELECT
            p.customer_id,
            CAST($snapshot AS DATE) AS snapshot_date,
            CASE
                WHEN w.next_purchase_ts IS NOT NULL THEN 0
                WHEN CAST($snapshot AS TIMESTAMP) + INTERVAL '{churn_window_days} days'
                     > (SELECT observed_through FROM horizon) THEN NULL
                ELSE 1
            END AS churned,
            (
                w.next_purchase_ts IS NULL
                AND CAST($snapshot AS TIMESTAMP) + INTERVAL '{churn_window_days} days'
                    > (SELECT observed_through FROM horizon)
            ) AS censored,
            CAST(w.next_purchase_ts AS DATE) AS next_purchase_date
        FROM population p
        LEFT JOIN window_purchases w USING (customer_id)
        ORDER BY p.customer_id
    """


@dataclass(frozen=True)
class LabelsResult:
    snapshot_date: date
    label_rows: int
    churned_count: int
    censored_count: int
    duckdb_path: Path
    parquet_path: Path
    report_path: Path
    dictionary_path: Path


def build_labels(settings: Settings, snapshot_date: str | date) -> LabelsResult:
    """Build the ``gold.labels`` slice for ``snapshot_date`` (validate → upsert → report)."""
    snapshot = parse_as_of_date(snapshot_date)
    sql = _label_sql(settings.churn_window_days)

    with warehouse_connection(settings.duckdb_path) as con:
        _require_customer_360_slice(con, snapshot)
        candidate = con.execute(sql, {"snapshot": snapshot.isoformat()}).df()
        validated = validate(candidate, Labels, f"{GOLD_TABLE} (candidate)")

        _upsert_slice(con, validated, snapshot)
        parquet_path = export_labels_parquet(con, settings.gold_dir)
        report_path = write_labels_report(con, snapshot, settings)
        dictionary_path = write_data_dictionary(con, settings.reports_dir)

    churned_count = int(validated["churned"].eq(1).sum())
    censored_count = int(validated["censored"].sum())
    return LabelsResult(
        snapshot_date=snapshot,
        label_rows=len(validated),
        churned_count=churned_count,
        censored_count=censored_count,
        duckdb_path=settings.duckdb_path,
        parquet_path=parquet_path,
        report_path=report_path,
        dictionary_path=dictionary_path,
    )


def _require_customer_360_slice(con: duckdb.DuckDBPyConnection, snapshot: date) -> None:
    """Fail clearly if the customer_360 population for ``snapshot`` has not been built."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'gold' AND table_name = 'customer_360'"
    ).fetchone()
    rows = (
        con.execute(
            f"SELECT COUNT(*) FROM {C360_TABLE} WHERE as_of_date = ?", [snapshot]
        ).fetchone()
        if exists
        else None
    )
    if not rows or rows[0] == 0:
        raise ValueError(
            f"no {C360_TABLE} slice for snapshot_date={snapshot}; "
            f"build customer_360 for that date first"
        )


def _upsert_slice(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, snapshot: date) -> None:
    """Idempotently replace the ``snapshot_date`` slice with the validated frame (D10)."""
    con.execute(_CREATE_TABLE_SQL)
    con.register("labels_frame", frame)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM {GOLD_TABLE} WHERE snapshot_date = ?", [snapshot])
        con.execute(
            f"""
            INSERT INTO {GOLD_TABLE} SELECT
                customer_id::VARCHAR,
                snapshot_date::DATE,
                churned::INTEGER,
                censored::BOOLEAN,
                next_purchase_date::DATE
            FROM labels_frame
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("labels_frame")
    logger.info(
        "Upserted %s slice for snapshot_date=%s (%d rows)", GOLD_TABLE, snapshot, len(frame)
    )


def export_labels_parquet(con: duckdb.DuckDBPyConnection, gold_dir: Path) -> Path:
    """Export the whole ``gold.labels`` panel to a single Parquet file."""
    gold_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = gold_dir / PARQUET_FILENAME
    con.execute(f"COPY {GOLD_TABLE} TO '{parquet_path}' (FORMAT PARQUET)")
    logger.info("Exported %s to %s", GOLD_TABLE, parquet_path)
    return parquet_path


def write_labels_report(con: duckdb.DuckDBPyConnection, snapshot: date, settings: Settings) -> Path:
    """Profile the whole ``gold.labels`` panel, one row per built snapshot."""
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.reports_dir / REPORT_FILENAME

    per_snapshot = con.execute(
        f"""
        SELECT
            snapshot_date,
            COUNT(*) AS n,
            SUM(CASE WHEN churned = 1 THEN 1 ELSE 0 END) AS churned,
            SUM(CASE WHEN churned = 0 THEN 1 ELSE 0 END) AS retained,
            SUM(CASE WHEN censored THEN 1 ELSE 0 END) AS censored
        FROM {GOLD_TABLE}
        GROUP BY snapshot_date
        ORDER BY snapshot_date
        """
    ).fetchall()

    lines = [
        "# Labels Profile",
        "",
        "Generated from the live warehouse on every label build — do not edit by hand.",
        "",
        f"Most recently built slice: **`snapshot_date = {snapshot.isoformat()}`**. The target "
        "is *no product purchase* in `[snapshot, snapshot + "
        f"{settings.churn_window_days}d)`, over the D3 active population (`recency_days ≤ "
        f"{settings.churn_window_days}`, read from `gold.customer_360`).",
        "",
        "## Snapshots in `gold.labels`",
        "",
        "Active churn rate excludes censored rows (immature window, outcome unknowable).",
        "",
        "| snapshot_date | customers | churned | retained | censored | active churn rate |",
        "|---------------|-----------|---------|----------|----------|-------------------|",
    ]
    for snap, n, churned, retained, censored in per_snapshot:
        mature = churned + retained
        rate = f"{churned / mature * 100:.1f}%" if mature else "—"
        lines.append(
            f"| {snap.isoformat()} | {n:,} | {churned:,} | {retained:,} | {censored:,} | {rate} |"
        )
    lines.extend(_contract_section())
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote labels profile to %s", report_path)
    return report_path


def _contract_section() -> list[str]:
    schema = Labels.to_schema()
    lines = [
        "",
        "## Labels contract (Pandera, enforced on every build)",
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
