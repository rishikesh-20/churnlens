import logging
from datetime import datetime

import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from churnlens.validation.runner import validate
from churnlens.validation.schemas import BronzeTransactions, SilverTransactions


def silver_frame(**overrides):
    """A minimal valid silver frame: one sale, one cancellation."""
    columns = {
        "invoice": ["489434", "C579889"],
        "stock_code": ["85048", "23245"],
        "description": ["GLASS BALL", "CAKE TINS"],
        "quantity": [12, -8],
        "invoice_date": [datetime(2009, 12, 1, 7, 45), datetime(2011, 12, 5, 9, 15)],
        "unit_price": [6.95, 4.15],
        "customer_id": ["13085", "17315"],
        "country": ["United Kingdom", "United Kingdom"],
        "line_revenue": [83.4, -33.2],
        "is_cancellation": [False, True],
        "is_product": [True, True],
        "source_file": ["online_retail_II.xlsx"] * 2,
        "source_sheet": ["Year 2009-2010"] * 2,
        "loaded_at": [datetime(2026, 6, 12)] * 2,
    }
    columns.update(overrides)
    return pd.DataFrame(columns)


def bronze_frame(**overrides):
    frame = silver_frame(**overrides)
    return frame.drop(columns=["line_revenue", "is_cancellation", "is_product"])


def test_valid_silver_frame_passes():
    validated = validate(silver_frame(), SilverTransactions, "test")
    assert len(validated) == 2


@pytest.mark.parametrize(
    ("overrides", "expected_check"),
    [
        # Column contracts.
        ({"unit_price": [-6.95, 4.15], "line_revenue": [-83.4, -33.2]}, "greater_than"),
        ({"quantity": [0, -8], "line_revenue": [0.0, -33.2]}, "not_equal_to"),
        ({"invoice": ["X89434", "C579889"]}, "str_matches"),
        ({"customer_id": ["ANON", "17315"]}, "str_matches"),
        ({"invoice_date": [datetime(2008, 1, 1), datetime(2011, 12, 5)]}, "greater_than"),
        # Business rules.
        ({"line_revenue": [99.9, -33.2]}, "line_revenue must equal"),
        ({"is_cancellation": [False, False]}, "negative-quantity"),
        ({"is_product": [False, True]}, "structural stock-code"),
    ],
)
def test_silver_contract_rejects(overrides, expected_check):
    with pytest.raises(SchemaErrors) as excinfo:
        validate(silver_frame(**overrides), SilverTransactions, "test")
    assert expected_check in excinfo.value.failure_cases["check"].str.cat()


def test_silver_contract_rejects_null_customer():
    frame = silver_frame(customer_id=["13085", None])
    with pytest.raises(SchemaErrors):
        validate(frame, SilverTransactions, "test")


def test_silver_contract_rejects_extra_and_missing_columns():
    with pytest.raises(SchemaErrors):
        validate(silver_frame().assign(surprise=1), SilverTransactions, "test")
    with pytest.raises(SchemaErrors):
        validate(silver_frame().drop(columns=["is_product"]), SilverTransactions, "test")


def test_lazy_validation_collects_all_violations():
    frame = silver_frame(
        unit_price=[-6.95, 4.15],  # violates ge(0) and the revenue rule
        quantity=[0, -8],  # violates ne(0) and the cancellation rule
    )
    with pytest.raises(SchemaErrors) as excinfo:
        validate(frame, SilverTransactions, "test")
    checks = set(excinfo.value.failure_cases["check"])
    assert len(checks) >= 2


def test_runner_logs_one_summary_line_per_check(caplog):
    frame = silver_frame(line_revenue=[99.9, -33.2])
    with caplog.at_level(logging.ERROR), pytest.raises(SchemaErrors):
        validate(frame, SilverTransactions, "test")
    revenue_lines = [r for r in caplog.messages if "line_revenue must equal" in r]
    assert len(revenue_lines) == 1
    assert "'<frame>'" in revenue_lines[0]


def test_bronze_contract_admits_known_dirt():
    frame = bronze_frame(
        customer_id=["13085", None],  # anonymous rows
        description=["GLASS BALL", None],  # null descriptions
        invoice=["489434", "A579889"],  # adjustment invoices
        unit_price=[6.95, -53594.36],  # negative adjustment prices
    )
    validated = validate(frame, BronzeTransactions, "test")
    assert len(validated) == 2


def test_bronze_contract_still_rejects_missing_columns():
    with pytest.raises(SchemaErrors):
        validate(bronze_frame().drop(columns=["invoice_date"]), BronzeTransactions, "test")
