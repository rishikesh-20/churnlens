import re
from datetime import date, datetime

import duckdb
import pandas as pd
import pytest

from churnlens.config.settings import Settings
from churnlens.io.customer360 import GOLD_TABLE as C360_TABLE
from churnlens.io.customer360 import build_customer_360
from churnlens.io.labels import GOLD_TABLE, build_labels
from churnlens.io.warehouse import warehouse_connection

AS_OF = "2011-06-01"  # window [2011-06-01, 2011-08-30); horizon below is 2011-09-15
PRODUCT_RE = re.compile(r"\d{5}[A-Za-z]*")

# (invoice, stock_code, quantity, unit_price, invoice_date, customer_id, country)
# Hand-computable fixture. As of 2011-06-01 the active population (recency <= 90) is
#   11111  multi-purchase, last purchase 2011-05-01, no purchase in window -> churned
#   22222  active, re-purchases 2011-07-01 in the window               -> retained
#   33333  cancellation-only (active by recency); only a return in window -> churned
# while 44444 (last pre-snapshot activity 2010-12-01) is inactive -> excluded.
# The 2011-09-15 line sets the observed horizon; 2011-09-01 feeds the censoring test.
SILVER_ROWS = [
    ("100001", "85123", 10, 2.0, datetime(2010, 1, 15, 9), "11111", "United Kingdom"),
    ("100002", "85124", 5, 4.0, datetime(2011, 5, 1, 9), "11111", "United Kingdom"),
    ("100003", "85125", 2, 50.0, datetime(2011, 5, 20, 9), "22222", "France"),
    ("C100004", "85126", -3, 5.0, datetime(2011, 4, 1, 9), "33333", "United Kingdom"),
    ("100005", "85127", 1, 10.0, datetime(2010, 12, 1, 9), "44444", "United Kingdom"),
    ("100010", "85125", 1, 50.0, datetime(2011, 7, 1, 9), "22222", "France"),
    ("C100011", "85126", -1, 5.0, datetime(2011, 7, 10, 9), "33333", "United Kingdom"),
    ("100020", "85125", 1, 50.0, datetime(2011, 9, 1, 9), "22222", "France"),
    ("100099", "85127", 1, 10.0, datetime(2011, 9, 15, 9), "44444", "United Kingdom"),
]


def seed_silver(settings, rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "invoice",
            "stock_code",
            "quantity",
            "unit_price",
            "invoice_date",
            "customer_id",
            "country",
        ],
    )
    frame["description"] = frame["stock_code"]
    frame["line_revenue"] = frame["quantity"] * frame["unit_price"]
    frame["is_cancellation"] = frame["invoice"].str.startswith("C")
    frame["is_product"] = frame["stock_code"].map(lambda c: bool(PRODUCT_RE.fullmatch(c)))
    frame["source_file"] = "online_retail_II.xlsx"
    frame["source_sheet"] = "Year 2010-2011"
    frame["loaded_at"] = datetime(2026, 6, 16)
    with warehouse_connection(settings.duckdb_path) as con:
        con.register("frame", frame)
        con.execute("CREATE OR REPLACE TABLE silver.transactions AS SELECT * FROM frame")
        con.unregister("frame")


@pytest.fixture
def settings(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")
    seed_silver(s, SILVER_ROWS)
    return s


def query(settings, sql, params=None):
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def label_row(settings, customer_id, snapshot=AS_OF):
    rows = query(
        settings,
        f"""
        SELECT churned, censored, next_purchase_date
        FROM {GOLD_TABLE} WHERE customer_id = ? AND snapshot_date = ?
        """,
        [customer_id, snapshot],
    )
    return rows[0] if rows else None


def build(settings, snapshot=AS_OF):
    """Build the customer_360 population then the labels for a snapshot."""
    build_customer_360(settings, snapshot)
    return build_labels(settings, snapshot)


def test_population_is_active_customers_only(settings):
    result = build(settings)
    assert result.label_rows == 3
    ids = {cid for (cid,) in query(settings, f"SELECT customer_id FROM {GOLD_TABLE}")}
    assert ids == {"11111", "22222", "33333"}  # 44444 inactive (recency > 90) -> excluded


def test_no_purchase_in_window_is_churned(settings):
    build(settings)
    churned, censored, next_purchase = label_row(settings, "11111")
    assert churned == 1
    assert censored is False
    assert next_purchase is None


def test_repurchase_in_window_is_retained(settings):
    build(settings)
    churned, censored, next_purchase = label_row(settings, "22222")
    assert churned == 0
    assert censored is False
    assert next_purchase == date(2011, 7, 1)


def test_return_in_window_does_not_save_from_churn(settings):
    # 33333 is active by recency (a cancellation counts as activity, D11) but its only
    # window event is a return, not a product purchase -> still churned (D24).
    build(settings)
    churned, _censored, next_purchase = label_row(settings, "33333")
    assert churned == 1
    assert next_purchase is None


def test_window_boundaries_are_half_open(settings):
    # A purchase at exactly the snapshot midnight counts (inclusive start); one at exactly
    # snapshot + 90d does not (exclusive end). 11111 otherwise churns.
    rows = [
        *SILVER_ROWS,
        ("100200", "85999", 1, 9.0, datetime(2011, 6, 1, 0, 0, 0), "11111", "United Kingdom"),
    ]
    seed_silver(settings, rows)
    build(settings)
    churned, _censored, next_purchase = label_row(settings, "11111")
    assert churned == 0  # the midnight purchase is in-window
    assert next_purchase == date(2011, 6, 1)

    rows = [
        *SILVER_ROWS,
        ("100201", "85999", 1, 9.0, datetime(2011, 8, 30, 0, 0, 0), "11111", "United Kingdom"),
    ]
    seed_silver(settings, rows)
    build(settings)
    churned, _censored, _next = label_row(settings, "11111")
    assert churned == 1  # 2011-08-30 == snapshot + 90d is excluded


def test_event_aware_censoring(settings):
    # Snapshot 2011-08-01: window [2011-08-01, 2011-10-30) extends past the 2011-09-15
    # horizon. 22222 has an observed purchase (2011-09-01) -> outcome known, not censored;
    # 33333 has no purchase in window -> censored, churned unknown.
    snapshot = "2011-08-01"
    build(settings, snapshot)

    churned, censored, next_purchase = label_row(settings, "22222", snapshot)
    assert censored is False
    assert churned == 0
    assert next_purchase == date(2011, 9, 1)

    churned, censored, next_purchase = label_row(settings, "33333", snapshot)
    assert censored is True
    assert churned is None
    assert next_purchase is None


def test_anti_leakage_forward_window_never_touches_features(settings):
    build(settings)
    c360_before = query(
        settings,
        f"SELECT * FROM {C360_TABLE} WHERE customer_id = '11111' AND as_of_date = ?",
        [AS_OF],
    )
    assert label_row(settings, "11111")[0] == 1  # churned with no window purchase

    # Inject a purchase in 11111's forward window, then rebuild both tables for the
    # same snapshot: the label flips, but no customer_360 feature changes.
    rows = [
        *SILVER_ROWS,
        ("100300", "85999", 4, 9.0, datetime(2011, 7, 15, 9), "11111", "United Kingdom"),
    ]
    seed_silver(settings, rows)
    build(settings)

    c360_after = query(
        settings,
        f"SELECT * FROM {C360_TABLE} WHERE customer_id = '11111' AND as_of_date = ?",
        [AS_OF],
    )
    assert c360_after == c360_before  # features unchanged by the post-snapshot purchase
    assert label_row(settings, "11111") == (0, False, date(2011, 7, 15))  # target changed


def test_idempotent_upsert_no_duplicate_rows(settings):
    build_customer_360(settings, AS_OF)
    build_labels(settings, AS_OF)
    build_labels(settings, AS_OF)
    count = query(settings, f"SELECT COUNT(*) FROM {GOLD_TABLE} WHERE customer_id = '11111'")
    assert count == [(1,)]


def test_multiple_snapshots_accumulate_a_panel(settings):
    build(settings, "2011-06-01")
    build(settings, "2011-08-01")
    dates = query(
        settings, f"SELECT DISTINCT snapshot_date FROM {GOLD_TABLE} ORDER BY snapshot_date"
    )
    assert dates == [(date(2011, 6, 1),), (date(2011, 8, 1),)]


def test_missing_customer_360_slice_fails_clearly(settings):
    # No customer_360 built for this date -> labeling must refuse, not write empty.
    with pytest.raises(ValueError, match="build customer_360"):
        build_labels(settings, AS_OF)


def test_artifacts_written(settings):
    result = build(settings)
    exported = duckdb.sql(f"SELECT COUNT(*) FROM '{result.parquet_path}'").fetchone()
    assert exported == (3,)

    report = result.report_path.read_text()
    assert f"snapshot_date = {AS_OF}" in report
    assert "active churn rate" in report

    dictionary = result.dictionary_path.read_text()
    assert "## `gold.labels`" in dictionary
    assert "`churned`" in dictionary
