"""Bronze ingestion of Online Retail II (D21).

Loads the source workbook into ``bronze.transactions`` as an exact copy of
the source rows — no cleaning, validation, filtering, or feature logic
(those start at the bronze→silver boundary, Phase 3). The only changes are
snake_case column names, customer ids stored as text, and lineage columns
(``source_file``, ``source_sheet``, ``loaded_at``).

The load takes no ``as_of_date``: bronze is the one layer below the
simulated clock (D1/D18) — downstream readers filter on ``invoice_date``.
Re-running fully replaces the table, so ingestion is idempotent and bronze
is always reloadable from source.

The source file is downloaded manually (no network code here): grab
``online+retail+ii.zip`` from the UCI repository and place the extracted
``.xlsx`` at ``Settings.raw_dir / SOURCE_FILENAME``.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from churnlens.config.settings import Settings
from churnlens.io.data_dictionary import SOURCE_URL, write_data_dictionary
from churnlens.io.warehouse import warehouse_connection

logger = logging.getLogger(__name__)

SOURCE_FILENAME = "online_retail_II.xlsx"
SOURCE_SHEETS = ("Year 2009-2010", "Year 2010-2011")

BRONZE_TABLE = "bronze.transactions"
PARQUET_FILENAME = "transactions.parquet"

# Source column -> bronze column (DATA_MODEL.md: bronze.transactions).
_COLUMN_MAP = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "unit_price",
    "Customer ID": "customer_id",
    "Country": "country",
}

# Text columns are read as text so source values survive verbatim —
# notably the 'C' cancellation prefix on invoice numbers.
_SOURCE_TEXT_COLUMNS = ["Invoice", "StockCode", "Description", "Country"]


@dataclass(frozen=True)
class IngestionResult:
    rows_loaded: int
    duckdb_path: Path
    parquet_path: Path
    dictionary_path: Path


def read_source(source_path: Path) -> pd.DataFrame:
    """Read every sheet of the source workbook into one bronze-shaped frame.

    Rows from all sheets are concatenated as-is; the overlap between the two
    UCI sheets is kept (deduplication is a silver concern, Phase 3).
    """
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}\n"
            f"Download the dataset from {SOURCE_URL} and place the extracted "
            f"workbook at this path."
        )

    frames = []
    for sheet in SOURCE_SHEETS:
        frame = pd.read_excel(
            source_path,
            sheet_name=sheet,
            dtype=dict.fromkeys(_SOURCE_TEXT_COLUMNS, "string"),
        )
        _validate_source_columns(frame, sheet)
        frame = frame.rename(columns=_COLUMN_MAP)
        # The workbook stores customer ids as floats (13085.0); the key is
        # text everywhere in the warehouse (DATA_MODEL.md conventions).
        frame["customer_id"] = frame["customer_id"].astype("Int64").astype("string")
        frame["source_sheet"] = sheet
        logger.info("Read sheet %r: %d rows", sheet, len(frame))
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    combined["source_file"] = source_path.name
    logger.info("Read %d rows total from %s", len(combined), source_path.name)
    return combined


def _validate_source_columns(frame: pd.DataFrame, sheet: str) -> None:
    expected = set(_COLUMN_MAP)
    actual = set(frame.columns)
    if actual != expected:
        raise ValueError(
            f"Sheet {sheet!r} has unexpected columns: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def load_bronze(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> int:
    """Atomically replace ``bronze.transactions`` with the source frame."""
    frame = frame.assign(loaded_at=datetime.now(UTC).replace(tzinfo=None))
    con.register("source_frame", frame)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {BRONZE_TABLE} AS
        SELECT
            invoice::VARCHAR       AS invoice,
            stock_code::VARCHAR    AS stock_code,
            description::VARCHAR   AS description,
            quantity::BIGINT       AS quantity,
            invoice_date::TIMESTAMP AS invoice_date,
            unit_price::DOUBLE     AS unit_price,
            customer_id::VARCHAR   AS customer_id,
            country::VARCHAR       AS country,
            source_file::VARCHAR   AS source_file,
            source_sheet::VARCHAR  AS source_sheet,
            loaded_at::TIMESTAMP   AS loaded_at
        FROM source_frame
        """
    )
    con.unregister("source_frame")
    rows = _row_count(con)
    logger.info("Loaded %d rows into %s", rows, BRONZE_TABLE)
    return rows


def export_bronze_parquet(con: duckdb.DuckDBPyConnection, bronze_dir: Path) -> Path:
    """Export ``bronze.transactions`` to a single Parquet file."""
    bronze_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = bronze_dir / PARQUET_FILENAME
    con.execute(f"COPY {BRONZE_TABLE} TO '{parquet_path}' (FORMAT PARQUET)")
    logger.info("Exported %s to %s", BRONZE_TABLE, parquet_path)
    return parquet_path


def ingest_bronze(settings: Settings) -> IngestionResult:
    """Run the full bronze ingestion: read → load → export → document."""
    frame = read_source(settings.raw_dir / SOURCE_FILENAME)
    with warehouse_connection(settings.duckdb_path) as con:
        rows = load_bronze(con, frame)
        parquet_path = export_bronze_parquet(con, settings.bronze_dir)
        dictionary_path = write_data_dictionary(con, settings.reports_dir)
    return IngestionResult(
        rows_loaded=rows,
        duckdb_path=settings.duckdb_path,
        parquet_path=parquet_path,
        dictionary_path=dictionary_path,
    )


def _row_count(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute(f"SELECT COUNT(*) FROM {BRONZE_TABLE}").fetchone()
    assert row is not None
    return int(row[0])
