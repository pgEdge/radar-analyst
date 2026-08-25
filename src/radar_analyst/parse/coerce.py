"""Shared string-to-scalar coercion for parsed TSV values.

Radar serializes query results through Go's ``%v`` formatting, so
booleans arrive as ``true``/``false`` and NULL as an empty string.
Every helper treats an empty or unparseable value as its zero/None
so a single odd cell never discards a row.
"""

from __future__ import annotations

from collections.abc import Mapping

_TRUE_WORDS = frozenset({"t", "true", "yes", "1"})


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
