import logging

from churnlens.utils.logging import configure_logging


def test_sets_level_case_insensitive():
    configure_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_idempotent_no_duplicate_handlers():
    configure_logging("INFO")
    configure_logging("INFO")
    assert len(logging.getLogger().handlers) == 1
