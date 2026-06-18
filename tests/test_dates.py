from datetime import date, datetime

import pytest

from churnlens.utils.dates import monthly_snapshots, parse_as_of_date


def test_iso_string():
    assert parse_as_of_date("2011-04-01") == date(2011, 4, 1)


def test_date_passthrough():
    d = date(2011, 4, 1)
    assert parse_as_of_date(d) == d


def test_datetime_discards_time():
    # Airflow logical dates arrive as midnight datetimes.
    assert parse_as_of_date(datetime(2011, 4, 1, 23, 59)) == date(2011, 4, 1)


def test_malformed_string_raises():
    with pytest.raises(ValueError):
        parse_as_of_date("01/04/2011")


def test_unsupported_type_raises():
    with pytest.raises(TypeError):
        parse_as_of_date(20110401)


def test_monthly_snapshots_inclusive_first_of_month():
    assert monthly_snapshots("2010-12-01", "2011-03-01") == [
        date(2010, 12, 1),
        date(2011, 1, 1),
        date(2011, 2, 1),
        date(2011, 3, 1),
    ]


def test_monthly_snapshots_snaps_to_first_of_month():
    # Any day in the month normalizes to the first; a single month yields one date.
    assert monthly_snapshots("2011-03-15", "2011-03-28") == [date(2011, 3, 1)]


def test_monthly_snapshots_rejects_reversed_range():
    with pytest.raises(ValueError):
        monthly_snapshots("2011-03-01", "2010-03-01")
