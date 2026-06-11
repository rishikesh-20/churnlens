"""Logging setup shared by every ChurnLens entrypoint (D17).

Entrypoints (scripts, DAG tasks, API startup) call ``configure_logging()``
once with the level from Settings. Library code only calls
``logging.getLogger(__name__)`` and never configures handlers.
"""

import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger. Idempotent: safe to call from any entrypoint."""
    logging.basicConfig(
        level=level.upper(),
        format=_FORMAT,
        datefmt=_DATEFMT,
        stream=sys.stderr,
        force=True,
    )
