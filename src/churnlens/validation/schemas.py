"""Pandera contracts for warehouse tables (D14, D22).

Each validated layer boundary gets a ``DataFrameModel`` here; pipelines
enforce them through ``churnlens.validation.runner.validate``.

Bronze's contract is loose — it admits the known dirt that the silver
filter rules remove (anonymous rows, adjustment codes with negative
prices). Silver's contract is strict: after the D11 filters, any
violation is a surprise and aborts the build (D22).
"""

from datetime import datetime
from typing import cast

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

# Invoice numbers are six digits, prefixed 'C' for cancellations (D11).
INVOICE_PATTERN = r"^C?\d{6}$"
# Customer ids are five-digit codes stored as text (DATA_MODEL conventions).
CUSTOMER_ID_PATTERN = r"^\d{5}$"
# A product stock code is five digits plus an optional letter suffix; anything
# else (POST, M, DOT, BANK CHARGES, ...) is a service/adjustment code excluded
# from revenue (D11, D22). Anchored, so SQL regexp_matches == str.fullmatch.
PRODUCT_STOCK_CODE_PATTERN = r"^\d{5}[A-Za-z]*$"
# The frozen dataset's invoice_date window (D1), with headroom at the end.
DATASET_START = datetime(2009, 12, 1)
DATASET_END = datetime(2012, 1, 1)


class BronzeTransactions(pa.DataFrameModel):
    """Input contract for ``bronze.transactions``: raw rows, known dirt admitted."""

    invoice: Series[str]
    stock_code: Series[str]
    description: Series[str] = pa.Field(nullable=True)
    quantity: Series[int]
    invoice_date: Series[pa.DateTime] = pa.Field(ge=DATASET_START, lt=DATASET_END)
    unit_price: Series[float]
    customer_id: Series[str] = pa.Field(nullable=True)
    country: Series[str]
    source_file: Series[str]
    source_sheet: Series[str]
    loaded_at: Series[pa.DateTime]

    class Config:
        strict = True
        coerce = True


class SilverTransactions(pa.DataFrameModel):
    """Output contract for ``silver.transactions``: strict, violations abort the build."""

    invoice: Series[str] = pa.Field(str_matches=INVOICE_PATTERN)
    stock_code: Series[str]
    description: Series[str]
    quantity: Series[int] = pa.Field(ne=0)
    invoice_date: Series[pa.DateTime] = pa.Field(ge=DATASET_START, lt=DATASET_END)
    unit_price: Series[float] = pa.Field(ge=0)
    customer_id: Series[str] = pa.Field(str_matches=CUSTOMER_ID_PATTERN)
    country: Series[str]
    line_revenue: Series[float]
    is_cancellation: Series[bool]
    is_product: Series[bool]
    source_file: Series[str]
    source_sheet: Series[str]
    loaded_at: Series[pa.DateTime]

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check(error="line_revenue must equal quantity * unit_price")
    def revenue_is_quantity_times_price(cls, df: pd.DataFrame) -> Series[bool]:
        residual = (df["line_revenue"] - df["quantity"] * df["unit_price"]).abs()
        return cast("Series[bool]", residual <= 1e-9)

    @pa.dataframe_check(error="cancellations must be exactly the negative-quantity rows")
    def cancellation_iff_negative_quantity(cls, df: pd.DataFrame) -> Series[bool]:
        return cast("Series[bool]", df["is_cancellation"] == (df["quantity"] < 0))

    @pa.dataframe_check(error="is_cancellation must mirror the 'C' invoice prefix")
    def cancellation_iff_c_invoice(cls, df: pd.DataFrame) -> Series[bool]:
        return cast("Series[bool]", df["is_cancellation"] == df["invoice"].str.startswith("C"))

    @pa.dataframe_check(error="is_product must mirror the structural stock-code rule")
    def product_iff_structural_code(cls, df: pd.DataFrame) -> Series[bool]:
        structural = df["stock_code"].str.fullmatch(PRODUCT_STOCK_CODE_PATTERN)
        return cast("Series[bool]", df["is_product"] == structural)


class Customer360(pa.DataFrameModel):
    """Output contract for ``gold.customer_360``: one row per customer, point-in-time (D18).

    Validated on the candidate slice for a single ``as_of_date`` before it is
    written, so ``customer_id`` is unique here. Anti-leakage is enforced by the
    aggregation SQL (history strictly before the cutoff) and proven by tests;
    this contract guards the resulting facts' internal consistency.
    """

    customer_id: Series[str] = pa.Field(str_matches=CUSTOMER_ID_PATTERN, unique=True)
    as_of_date: Series[pa.DateTime]
    first_purchase_date: Series[pa.DateTime]
    last_activity_date: Series[pa.DateTime]
    # Null for customers whose only pre-cutoff activity is a cancellation.
    last_purchase_date: Series[pa.DateTime] = pa.Field(nullable=True)
    recency_days: Series[int] = pa.Field(ge=0)
    tenure_days: Series[int] = pa.Field(ge=0)
    order_count: Series[int] = pa.Field(ge=0)
    cancelled_order_count: Series[int] = pa.Field(ge=0)
    # Revenue is net of product cancellations and may be negative (pure returns).
    total_net_revenue: Series[float]
    trailing_12m_net_revenue: Series[float]
    cancelled_revenue: Series[float] = pa.Field(le=0)
    run_rate_90d: Series[float]
    country: Series[str]

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check(error="recency_days must not exceed tenure_days")
    def recency_within_tenure(cls, df: pd.DataFrame) -> Series[bool]:
        return cast("Series[bool]", df["recency_days"] <= df["tenure_days"])

    @pa.dataframe_check(error="first_purchase_date must not exceed last_activity_date")
    def first_before_last_activity(cls, df: pd.DataFrame) -> Series[bool]:
        return cast("Series[bool]", df["first_purchase_date"] <= df["last_activity_date"])


class Labels(pa.DataFrameModel):
    """Output contract for ``gold.labels``: one row per active customer, point-in-time (D24).

    Validated on the candidate slice for a single ``snapshot_date`` before it is
    written, so ``customer_id`` is unique here. The forward-looking target is read
    from silver in ``[snapshot, snapshot + 90d)`` (the only deliberate look-ahead,
    target-only); this contract guards the resulting label's internal consistency.
    """

    customer_id: Series[str] = pa.Field(str_matches=CUSTOMER_ID_PATTERN, unique=True)
    snapshot_date: Series[pa.DateTime]
    # Null exactly for censored rows (window not fully observed, outcome unknowable).
    churned: Series[pd.Int64Dtype] = pa.Field(nullable=True, isin=[0, 1])
    censored: Series[bool]
    # First product purchase in the window; null unless churned == 0.
    next_purchase_date: Series[pa.DateTime] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check(error="churned is null exactly when censored")
    def churned_null_iff_censored(cls, df: pd.DataFrame) -> Series[bool]:
        return cast("Series[bool]", df["churned"].isna() == df["censored"])

    @pa.dataframe_check(error="next_purchase_date is set exactly when churned == 0")
    def next_purchase_iff_retained(cls, df: pd.DataFrame) -> Series[bool]:
        retained = df["churned"].eq(0).fillna(False).astype(bool)
        return cast("Series[bool]", df["next_purchase_date"].notna() == retained)

    @pa.dataframe_check(error="next_purchase_date must not precede snapshot_date")
    def next_purchase_within_window(cls, df: pd.DataFrame) -> Series[bool]:
        within = df["next_purchase_date"] >= df["snapshot_date"]
        return cast("Series[bool]", within | df["next_purchase_date"].isna())
