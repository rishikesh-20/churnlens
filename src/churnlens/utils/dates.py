"""The as_of_date convention (D18).

Every time-dependent pipeline function takes ``as_of_date: datetime.date``
under exactly that name. Semantics: start-of-day cutoff — the function may
read only data timestamped strictly before midnight at the start of
``as_of_date``; label/forecast windows start at ``as_of_date`` inclusive.
In pipelines, ``as_of_date`` is Airflow's ``logical_date`` (D10) normalized
through ``parse_as_of_date``; code never calls ``today()``.
"""

from datetime import date, datetime


def monthly_snapshots(start: str | date | datetime, end: str | date | datetime) -> list[date]:
    """First-of-month dates from ``start``'s month through ``end``'s month, inclusive.

    The rolling monthly snapshot schedule (D2/D4): each labeling snapshot is the
    first of a month. Inputs are normalized through ``parse_as_of_date`` and
    snapped back to the first of their month. Raises ValueError if ``end`` precedes
    ``start``.
    """
    first = parse_as_of_date(start).replace(day=1)
    last = parse_as_of_date(end).replace(day=1)
    if last < first:
        raise ValueError(f"end ({last}) must not precede start ({first})")
    snapshots = []
    current = first
    while current <= last:
        snapshots.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return snapshots


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
