"""The as_of_date convention (D18).

Every time-dependent pipeline function takes ``as_of_date: datetime.date``
under exactly that name. Semantics: start-of-day cutoff — the function may
read only data timestamped strictly before midnight at the start of
``as_of_date``; label/forecast windows start at ``as_of_date`` inclusive.
In pipelines, ``as_of_date`` is Airflow's ``logical_date`` (D10) normalized
through ``parse_as_of_date``; code never calls ``today()``.
"""

from datetime import date, datetime


def parse_as_of_date(value: str | date | datetime) -> date:
    """Normalize script/DAG input to a ``date``.

    Accepts ISO-format strings (``"2011-04-01"``), datetimes (time part
    discarded — Airflow logical dates are midnight datetimes), and dates.
    Raises ValueError for malformed strings, TypeError for other types.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"as_of_date must be str | date | datetime, got {type(value).__name__}")
