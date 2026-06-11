from datetime import date, datetime

import pytest

from churnlens.utils.dates import parse_as_of_date


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
