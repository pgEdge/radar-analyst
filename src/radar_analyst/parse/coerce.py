"""Shared string-to-scalar coercion for parsed TSV values.

Radar serializes query results through Go's ``%v`` formatting, so
booleans arrive as ``true``/``false`` and NULL as an empty string.
Every helper treats an empty or unparseable value as its zero/None
so a single odd cell never discards a row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime


_TRUE_WORDS = frozenset({"t", "true", "yes", "1"})

# Go's time.Time layout, ``2006-01-02 15:04:05.999999999 -0700 MST``:
# the fraction drops trailing zeros and a zone name follows the
# offset, and datetime.fromisoformat accepts neither.
_GO_TIME_RE = re.compile(
    r"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d{1,9}))?"
    r" (?P<tz>[+-]\d{4})(?: \S+)?$"
)


def as_int(value: str | None) -> int:
    """Parse *value* as int; empty or unparseable becomes 0."""
    v = (value or "").strip()
    if not v:
        return 0
    try:
        return int(v)
    except ValueError:
        return 0


def as_int_or_none(value: str | None) -> int | None:
    """Parse *value* as int; empty or unparseable becomes None."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def as_float(value: str | None) -> float:
    """Parse *value* as float; empty or unparseable becomes 0.0."""
    v = (value or "").strip()
    if not v:
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def as_float_or_none(value: str | None) -> float | None:
    """Parse *value* as float; empty or unparseable becomes None."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def as_bool(value: str | None) -> bool:
    """Parse a boolean cell (``true``/``t``/``yes``/``1``)."""
    return (value or "").strip().lower() in _TRUE_WORDS


def row_int(row: Mapping[str, str], key: str) -> int:
    """``as_int`` of ``row[key]``; a missing key becomes 0."""
    return as_int(row.get(key))


def row_float(row: Mapping[str, str], key: str) -> float:
    """``as_float`` of ``row[key]``; a missing key becomes 0.0."""
    return as_float(row.get(key))


def as_datetime_or_none(value: str | None) -> datetime | None:
    """Parse a radar timestamp; None when empty or unparseable.

    Radar writes ``timestamptz`` values in Go's time.Time layout,
    which is rewritten to ISO 8601 with the fraction cut to the
    microseconds ``datetime`` holds. Any other value goes to
    ``datetime.fromisoformat`` as it is.
    """
    s = (value or "").strip()
    m = _GO_TIME_RE.match(s)
    if m is not None:
        frac = (m["frac"] or "").ljust(6, "0")[:6]
        s = f"{m['dt']}.{frac}{m['tz']}"
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
