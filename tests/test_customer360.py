import re
from datetime import date, datetime

import duckdb
import pandas as pd
import pytest

from churnlens.config.settings import Settings
from churnlens.io.customer360 import GOLD_TABLE, build_customer_360
from churnlens.io.warehouse import warehouse_connection

AS_OF = "2011-06-01"
PRODUCT_RE = re.compile(r"\d{5}[A-Za-z]*")

# (invoice, stock_code, quantity, unit_price, invoice_date, customer_id, country)
# Hand-computable fixture, evaluated as of 2011-06-01:
#   11111  two product purchases + a later POST (non-product) service line
#   22222  one-time buyer, thin history (run-rate tenure floor applies)
#   33333  cancellation-only customer (no purchase yet)
SILVER_ROWS = [
    ("100001", "85123", 10, 2.0, datetime(2010, 1, 15, 9), "11111", "United Kingdom"),
    ("100002", "85124", 5, 4.0, datetime(2011, 5, 1, 9), "11111", "United Kingdom"),
    ("100005", "POST", 1, 18.0, datetime(2011, 5, 15, 9), "11111", "United Kingdom"),
    ("100003", "85125", 2, 50.0, datetime(2011, 5, 20, 9), "22222", "France"),
    ("C100004", "85126", -3, 5.0, datetime(2011, 4, 1, 9), "33333", "United Kingdom"),
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


def customer_row(settings, customer_id, as_of=AS_OF):
    rows = query(
        settings,
        f"""
        SELECT first_purchase_date, last_activity_date, last_purchase_date,
               recency_days, tenure_days, order_count, cancelled_order_count,
               total_net_revenue, trailing_12m_net_revenue, cancelled_revenue,
               run_rate_90d, country
        FROM {GOLD_TABLE} WHERE customer_id = ? AND as_of_date = ?
        """,
        [customer_id, as_of],
    )
    return rows[0] if rows else None


def test_population_is_all_customers_with_prior_history(settings):
    result = build_customer_360(settings, AS_OF)
    assert result.customer_rows == 3
    ids = {cid for (cid,) in query(settings, f"SELECT customer_id FROM {GOLD_TABLE}")}
    assert ids == {"11111", "22222", "33333"}


def test_metrics_for_multi_purchase_customer(settings):
    build_customer_360(settings, AS_OF)
    (
        first,
        last_act,
        last_pur,
        recency,
        tenure,
        orders,
        cancels,
        net,
        trailing,
        cancelled,
        run_rate,
        country,
    ) = customer_row(settings, "11111")
    assert first == date(2010, 1, 15)
    assert last_act == date(2011, 5, 15)  # the POST line is the latest activity
    assert last_pur == date(2011, 5, 1)  # ... but last purchase ignores non-product
    assert recency == 17
    assert tenure == 502
    assert orders == 3  # three distinct non-cancellation invoices (POST counts as an order)
    assert cancels == 0
    assert net == pytest.approx(40.0)  # POST revenue excluded
    assert trailing == pytest.approx(20.0)  # only the 2011-05-01 purchase is within 12mo
    assert cancelled == pytest.approx(0.0)
    # tenure >= 365 -> trailing-12m branch
    assert run_rate == pytest.approx(20.0 * 90 / 365)
    assert country == "United Kingdom"


def test_thin_history_run_rate_uses_tenure_floor(settings):
    build_customer_360(settings, AS_OF)
    row = customer_row(settings, "22222")
    recency, tenure, orders, net, run_rate = row[3], row[4], row[5], row[7], row[10]
    assert recency == 12
    assert tenure == 12
    assert orders == 1
    assert net == pytest.approx(100.0)
    # tenure (12) < 365 and < the 90d floor -> denominator floored to 90, so rate == net
    assert run_rate == pytest.approx(100.0)


def test_cancellation_only_customer(settings):
    build_customer_360(settings, AS_OF)
    (
        _first,
        _last_act,
        last_pur,
        recency,
        _tenure,
        orders,
        cancels,
        net,
        _trailing,
        cancelled,
        run_rate,
        _,
    ) = customer_row(settings, "33333")
    assert last_pur is None  # no purchase yet
    assert orders == 0
    assert cancels == 1
    assert net == pytest.approx(-15.0)
    assert cancelled == pytest.approx(-15.0)
    assert recency == 61
    assert run_rate == pytest.approx(-15.0)  # -15 / max(61, 90) * 90


def test_point_in_time_metrics_change_with_as_of(settings):
    build_customer_360(settings, "2011-05-10")  # before 22222's only purchase
    assert customer_row(settings, "22222", "2011-05-10") is None
    # 11111 as of 2011-05-10: POST and the trailing window have not happened yet
    early = customer_row(settings, "11111", "2011-05-10")
    assert early[1] == date(2011, 5, 1)  # last activity is the purchase, not the POST
    assert early[5] == 2  # only two invoices so far


def test_anti_leakage_future_transactions_are_ignored(settings):
    build_customer_360(settings, AS_OF)
    before = customer_row(settings, "11111")

    # A purchase exactly at the cutoff midnight (must be excluded: strict <) and one
    # after it. Rebuilding the same as_of_date must not change a single metric.
    leak_rows = [
        *SILVER_ROWS,
        ("100099", "85999", 100, 9.0, datetime(2011, 6, 1, 0, 0, 0), "11111", "United Kingdom"),
        ("100100", "85999", 100, 9.0, datetime(2011, 7, 1, 9), "11111", "United Kingdom"),
    ]
    seed_silver(settings, leak_rows)
    build_customer_360(settings, AS_OF)
    assert customer_row(settings, "11111") == before

    # Advancing the clock past the future rows surfaces them.
    build_customer_360(settings, "2011-08-01")
    later = customer_row(settings, "11111", "2011-08-01")
    assert later[5] == 5  # the two new invoices now count


def test_idempotent_upsert_no_duplicate_rows(settings):
    build_customer_360(settings, AS_OF)
    build_customer_360(settings, AS_OF)
    count = query(settings, f"SELECT COUNT(*) FROM {GOLD_TABLE} WHERE customer_id = '11111'")
    assert count == [(1,)]


def test_multiple_snapshots_accumulate_a_panel(settings):
    build_customer_360(settings, "2011-05-01")
    build_customer_360(settings, AS_OF)
    dates = query(settings, f"SELECT DISTINCT as_of_date FROM {GOLD_TABLE} ORDER BY as_of_date")
    assert dates == [(date(2011, 5, 1),), (date(2011, 6, 1),)]


def test_artifacts_written(settings):
    result = build_customer_360(settings, AS_OF)
    exported = duckdb.sql(f"SELECT COUNT(*) FROM '{result.parquet_path}'").fetchone()
    assert exported == (3,)

    report = result.report_path.read_text()
    assert f"as_of_date = {AS_OF}" in report
    assert "**Customers:** 3" in report

    dictionary = result.dictionary_path.read_text()
    assert "## `gold.customer_360`" in dictionary
    assert "`run_rate_90d`" in dictionary
