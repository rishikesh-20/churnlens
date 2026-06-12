"""DuckDB warehouse access (D20).

The analytical warehouse is a single DuckDB file (``Settings.duckdb_path``)
holding one SQL schema per medallion layer: ``bronze``, ``silver``, ``gold``.
All warehouse readers and writers obtain connections through
``warehouse_connection()`` so the layer schemas always exist.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

LAYER_SCHEMAS = ("bronze", "silver", "gold")


@contextmanager
def warehouse_connection(duckdb_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the warehouse file, ensuring the medallion layer schemas exist."""
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(duckdb_path))
    try:
        for schema in LAYER_SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        yield con
    finally:
        con.close()
