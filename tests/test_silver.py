from datetime import datetime

import duckdb
import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from churnlens.config.settings import Settings
from churnlens.io.silver import build_silver
from churnlens.io.warehouse import warehouse_connection

SHEET_1 = "Year 2009-2010"
SHEET_2 = "Year 2010-2011"

# (invoice, stock_code, description, quantity, invoice_date, unit_price,
#  customer_id, country, source_sheet)
OVERLAP_ROW = ("491200", "21733", "HEART", 6, datetime(2010, 12, 1, 10, 0), 2.95, "14688", "UK")
WITHIN_SHEET_DUP = (
    "581587",
    "22138",
    "BAKING SET",
    3,
    datetime(2011, 12, 9, 12, 50),
    4.95,
    "12680",
    "France",
)

BRONZE_ROWS = [
    # Plain product sale: line_revenue = 12 * 6.95 = 83.4.
    ("489434", "85048", "GLASS BALL", 12, datetime(2009, 12, 1, 7), 6.95, "13085", "UK", SHEET_1),
    # The export overlap: identical row in both sheets — silver keeps sheet 1's copy.
    (*OVERLAP_ROW, SHEET_1),
    (*OVERLAP_ROW, SHEET_2),
    # A legitimate repeated line inside one sheet — silver keeps both.
    (*WITHIN_SHEET_DUP, SHEET_2),
    (*WITHIN_SHEET_DUP, SHEET_2),
    # Anonymous row — dropped, churn is per-customer.
    ("489435", "22350", "CAT BOWL", 8, datetime(2009, 12, 1, 8), 2.55, None, "UK", SHEET_1),
    # Cancellation: kept as a negative line, is_cancellation = true.
    ("C579889", "23245", "CAKE TINS", -8, datetime(2011, 12, 5, 9), 4.15, "17315", "UK", SHEET_2),
    # Zero-price giveaway: kept, zero revenue.
    ("489998", "48185", "DOOR MAT", 2, datetime(2009, 12, 2, 11), 0.0, "13085", "UK", SHEET_1),
    # Non-product service code: kept, is_product = false.
    ("489500", "POST", "POSTAGE", 1, datetime(2009, 12, 3, 9), 18.0, "12680", "France", SHEET_1),
]

EXPECTED_SILVER_ROWS = 7  # 9 bronze - 1 overlap copy - 1 anonymous


def seed_bronze(settings, rows):
    frame = pd.DataFrame(
        rows,
        columns=[
            "invoice",
            "stock_code",
            "description",
            "quantity",
            "invoice_date",
            "unit_price",
            "customer_id",
            "country",
            "source_sheet",
        ],
    )
    frame["source_file"] = "online_retail_II.xlsx"
    frame["loaded_at"] = datetime(2026, 6, 12)
    with warehouse_connection(settings.duckdb_path) as con:
        con.register("frame", frame)
        con.execute("CREATE OR REPLACE TABLE bronze.transactions AS SELECT * FROM frame")
        con.unregister("frame")


@pytest.fixture
def settings(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")
    seed_bronze(s, BRONZE_ROWS)
    return s


def query(settings, sql):
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_build_silver_row_accounting(settings):
    result = build_silver(settings)
    a = result.accounting
    assert a.bronze_rows == len(BRONZE_ROWS)
    assert a.duplicate_rows_dropped == 1
    assert a.anonymous_rows_dropped == 1
    assert a.silver_rows == EXPECTED_SILVER_ROWS


def test_dedup_drops_only_the_inter_sheet_copy(settings):
    build_silver(settings)
    overlap = query(
        settings,
        "SELECT source_sheet FROM silver.transactions WHERE invoice = '491200'",
    )
    assert overlap == [(SHEET_1,)]  # one copy, from the earlier sheet
    within = query(settings, "SELECT COUNT(*) FROM silver.transactions WHERE invoice = '581587'")
    assert within == [(2,)]  # legitimate repeated line survives


def test_derived_columns(settings):
    build_silver(settings)
    rows = {
        invoice: (revenue, cancellation, product)
        for invoice, revenue, cancellation, product in query(
            settings,
            """
            SELECT invoice, SUM(line_revenue), BOOL_OR(is_cancellation), BOOL_OR(is_product)
            FROM silver.transactions GROUP BY invoice
            """,
        )
    }
    assert rows["489434"] == (pytest.approx(83.4), False, True)
    assert rows["C579889"] == (pytest.approx(-33.2), True, True)  # negative net revenue
    assert rows["489998"] == (0.0, False, True)  # zero-price row kept
    assert rows["489500"] == (pytest.approx(18.0), False, False)  # POST is not a product


def test_silver_has_no_anonymous_rows_and_proper_types(settings):
    build_silver(settings)
    anonymous = "SELECT COUNT(*) FROM silver.transactions WHERE customer_id IS NULL"
    assert query(settings, anonymous) == [(0,)]
    types = dict(
        query(
            settings,
            """
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'silver' AND table_name = 'transactions'
            """,
        )
    )
    assert types["is_cancellation"] == "BOOLEAN"
    assert types["is_product"] == "BOOLEAN"
    assert types["line_revenue"] == "DOUBLE"
    assert types["invoice_date"] == "TIMESTAMP"


def test_build_silver_is_idempotent(settings):
    first = build_silver(settings)
    second = build_silver(settings)
    assert first.accounting == second.accounting


def test_artifacts_written(settings):
    result = build_silver(settings)
    exported = duckdb.sql(f"SELECT COUNT(*) FROM '{result.parquet_path}'").fetchone()
    assert exported == (EXPECTED_SILVER_ROWS,)

    quality = result.quality_report_path.read_text()
    assert f"| `silver.transactions` | {EXPECTED_SILVER_ROWS:,} |" in quality
    assert "`POST`" in quality  # excluded code list
    assert "line_revenue must equal quantity * unit_price" in quality

    dictionary = result.dictionary_path.read_text()
    assert "## `bronze.transactions`" in dictionary
    assert "## `silver.transactions`" in dictionary
    assert "`is_product`" in dictionary


def test_contract_violation_aborts_without_touching_silver(settings):
    build_silver(settings)

    # A surprise: negative price on a product row with a real customer — no
    # filter rule removes it, so the silver contract must abort the build.
    bad_row = (
        "490000",
        "85123",
        "BAD ROW",
        1,
        datetime(2010, 1, 1, 9, 0),
        -5.0,
        "13085",
        "UK",
        SHEET_1,
    )
    seed_bronze(settings, [*BRONZE_ROWS, bad_row])

    with pytest.raises(SchemaErrors):
        build_silver(settings)
    # The previously built silver table is untouched.
    assert query(settings, "SELECT COUNT(*) FROM silver.transactions") == [(EXPECTED_SILVER_ROWS,)]
