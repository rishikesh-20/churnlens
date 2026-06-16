"""Generic Pandera contract runner (D14, D22).

Every layer boundary validates through ``validate()`` so failure handling
is uniform: the whole frame is checked lazily (all violations collected,
not just the first), a per-check summary is logged, and the original
``SchemaErrors`` is re-raised so callers abort before writing anything.
"""

import logging

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

logger = logging.getLogger(__name__)


def validate(frame: pd.DataFrame, schema: type[pa.DataFrameModel], name: str) -> pd.DataFrame:
    """Validate ``frame`` against ``schema``, logging all violations before raising."""
    try:
        validated = schema.validate(frame, lazy=True)
    except SchemaErrors as exc:
        # Frame-level check failures are reported once per column; collapse
        # them so the summary counts each failing row once per check.
        cases = exc.failure_cases.copy()
        cases.loc[cases["schema_context"] == "DataFrameSchema", "column"] = "<frame>"
        summary = cases.groupby(["column", "check"], dropna=False)["index"].nunique()
        logger.error("Contract %r failed: %d check(s) violated", name, len(summary))
        for (column, check), count in summary.items():
            logger.error("  column %r, check %r: %d failing row(s)", column, check, count)
        raise
    logger.info("Contract %r passed: %d rows", name, len(validated))
    return pd.DataFrame(validated)
