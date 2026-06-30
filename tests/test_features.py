import math
import re
from datetime import datetime

import duckdb
import pandas as pd
import pytest

from churnlens.config.settings import Settings
from churnlens.io.customer360 import build_customer_360
from churnlens.io.features import FEATURE_COLUMNS, GOLD_TABLE, build_features
from churnlens.io.warehouse import warehouse_connection

AS_OF = "2011-06-01"
PRODUCT_RE = re.compile(r"\d{5}[A-Za-z]*")

# (invoice, stock_code, quantity, unit_price, invoice_date, customer_id, country)
# Hand-computable fixture as of 2011-06-01:
#   11111  two purchases (2010-01-15, 2011-05-01) + a POST service line (2011-05-15)
#   22222  one-time buyer (2011-05-20), thin history
#   33333  cancellation-only (2011-04-01) — no purchase, net-negative
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


def feature_slice(settings, as_of=AS_OF):
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        return con.execute(
            f"SELECT * FROM {GOLD_TABLE} WHERE as_of_date = ? ORDER BY customer_id", [as_of]
        ).df()
    finally:
        con.close()


def feature_row(settings, customer_id, as_of=AS_OF):
    df = feature_slice(settings, as_of)
    df = df[df["customer_id"] == customer_id]
    return df.iloc[0].to_dict() if len(df) else None


def build(settings, as_of=AS_OF):
    """Build the customer_360 population then the features for an as_of_date."""
    build_customer_360(settings, as_of)
    return build_features(settings, as_of)


def test_population_is_full_customer_360(settings):
    result = build(settings)
    assert result.feature_rows == 3  # every customer with history, not just the active ones
    assert set(feature_slice(settings)["customer_id"]) == {"11111", "22222", "33333"}


def test_feature_correctness_multi_purchase_customer(settings):
    build(settings)
    f = feature_row(settings, "11111")
    assert f["customer_lifetime_orders"] == 3
    assert f["order_frequency"] == pytest.approx(3 * 30 / 502)
    assert f["purchase_velocity"] == pytest.approx(1.5)  # 3 orders / 2 active months
    assert f["purchase_intensity"] == pytest.approx(3 / 502)  # 3 active days / 502 tenure days
    assert f["average_days_between_orders"] == pytest.approx(471 / 2)  # 2010-01-15 -> 2011-05-01
    assert f["recency_score"] == pytest.approx(math.exp(-31 / 90))  # 31 days since last purchase
    assert f["average_order_value"] == pytest.approx(40 / 3)
    assert f["revenue_per_active_day"] == pytest.approx(40 / 3)
    assert f["trailing_12m_average_monthly_revenue"] == pytest.approx(20 / 12)
    assert f["revenue_growth_ratio"] == pytest.approx(1.0)  # trailing 20 / prior 20
    assert f["revenue_concentration"] == pytest.approx(0.5)  # biggest order 20 / gross 40
    assert f["active_months"] == 2
    assert f["product_diversity"] == 2
    assert f["average_products_per_order"] == pytest.approx(2 / 3)
    assert f["cancellation_rate"] == pytest.approx(0.0)
    assert f["repeat_purchase_ratio"] == pytest.approx(2 / 3)
    assert f["customer_age_days"] == 502
    assert f["days_since_last_purchase"] == pytest.approx(31)


def test_one_time_buyer_undefined_features_are_nan(settings):
    build(settings)
    f = feature_row(settings, "22222")
    assert math.isnan(f["average_days_between_orders"])  # fewer than two orders
    assert math.isnan(f["revenue_growth_ratio"])  # no prior-12m revenue
    assert f["repeat_purchase_ratio"] == pytest.approx(0.0)  # one order, not NaN
    assert f["recency_score"] == pytest.approx(math.exp(-12 / 90))


def test_cancellation_only_customer_features(settings):
    build(settings)
    f = feature_row(settings, "33333")
    assert f["customer_lifetime_orders"] == 0
    assert math.isnan(f["recency_score"])  # never purchased
    assert math.isnan(f["average_order_value"])  # no orders
    assert math.isnan(f["repeat_purchase_ratio"])
    assert math.isnan(f["average_products_per_order"])
    assert math.isnan(f["days_since_last_purchase"])
    assert math.isnan(f["revenue_concentration"])  # non-positive total revenue
    assert f["cancellation_rate"] == pytest.approx(1.0)
    assert f["revenue_per_active_day"] == pytest.approx(-15.0)  # net-negative, unconstrained


def test_anti_leakage_future_transactions_never_touch_features(settings):
    build(settings)
    before = feature_row(settings, "11111")

    # A purchase exactly at the cutoff midnight (excluded, strict <) and one after it.
    # Rebuilding customer_360 + features for the same as_of_date must change nothing.
    leak_rows = [
        *SILVER_ROWS,
        ("100099", "85999", 100, 9.0, datetime(2011, 6, 1, 0, 0, 0), "11111", "United Kingdom"),
        ("100100", "85999", 100, 9.0, datetime(2011, 7, 1, 9), "11111", "United Kingdom"),
    ]
    seed_silver(settings, leak_rows)
    build(settings)
    after = feature_row(settings, "11111")

    assert pd.Series(after).equals(pd.Series(before))  # no feature moved


def test_shared_builder_is_point_in_time(settings):
    # The same build_features serves "training" (an earlier cutoff) and "scoring" (a later one).
    # 11111's age advances exactly with the cutoff; the code path is identical.
    build(settings, "2011-05-10")
    build(settings, "2011-06-01")
    early = feature_row(settings, "11111", "2011-05-10")
    late = feature_row(settings, "11111", "2011-06-01")
    assert late["customer_age_days"] - early["customer_age_days"] == 22  # 2011-05-10 -> 2011-06-01


def test_idempotent_rebuild_is_logically_equal(settings):
    build(settings)
    first = feature_slice(settings)
    build_features(settings, AS_OF)  # rebuild the same slice
    second = feature_slice(settings)
    assert len(second) == 3
    pd.testing.assert_frame_equal(first, second)  # value-wise equal, NaN-aware


def test_missing_customer_360_slice_fails_clearly(settings):
    with pytest.raises(ValueError, match="build customer_360"):
        build_features(settings, AS_OF)


def test_artifacts_and_report(settings):
    result = build(settings)
    exported = duckdb.sql(f"SELECT COUNT(*) FROM '{result.parquet_path}'").fetchone()
    assert exported == (3,)

    report = result.report_path.read_text()
    assert f"as_of_date = {AS_OF}" in report
    assert f"**Features:** {len(FEATURE_COLUMNS)}" in report
    assert "`recency_score`" in report

    dictionary = result.dictionary_path.read_text()
    assert "## `gold.features`" in dictionary
    assert "`revenue_concentration`" in dictionary
