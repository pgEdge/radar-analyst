"""Settings the analyst reads from its environment."""

from __future__ import annotations

import contextlib
import logging
import os


_logger = logging.getLogger(__name__)


def positive_int_env(name: str, default: int) -> int:
    """Return environment variable *name* as a positive integer.

    An unset or empty variable gives *default*. So does any other
    value that is not a positive integer, after a warning that names
    the variable.
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    with contextlib.suppress(ValueError):
        if (value := int(raw)) > 0:
            return value
    _logger.warning(
        "invalid %s=%r, using default %d", name, raw, default
    )
    return default
