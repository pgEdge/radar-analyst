r"""Parse radar-style TSV files (inverse of radar.go::rowsToTSV).

Radar's TSV format (radar.go:682-684):

- Tab-separated fields, LF-terminated rows.
- If a value contains any of ``\\t``, ``\\n``, ``\\r``, or ``"``, it is
  wrapped in double-quotes, and inner ``"`` is doubled to ``""``.
- NULL values are written as an empty field (no quoting).
- Single quotes are NOT escaped.

This maps cleanly onto :mod:`csv` with ``delimiter='\\t'``, ``quotechar='"'``
and ``doublequote=True``: which also handles the multi-line quoted-field
case transparently.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO


@dataclass(frozen=True)
class TsvTable:
    """A parsed TSV: column order plus row dicts."""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)


def parse_tsv(text: str) -> TsvTable:
    """Parse *text* as a radar-style TSV table."""
    if not text:
        return TsvTable()
    reader = csv.reader(
        StringIO(text),
        delimiter="\t",
        quotechar='"',
        doublequote=True,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    try:
        header = next(reader)
    except StopIteration:
        return TsvTable()
    rows: list[dict[str, str]] = []
    for idx, raw in enumerate(reader, start=2):
        if len(raw) > len(header):
            raise ValueError(
                f"row {idx}: expected at most {len(header)} "
                f"fields, got {len(raw)}"
            )
        # Pad short rows with empty strings: matches radar's
        # "NULL → empty field" convention.
        padded = raw + [""] * (len(header) - len(raw))
        rows.append(dict(zip(header, padded, strict=True)))
    return TsvTable(columns=header, rows=rows)


def parse_tsv_bytes(data: bytes) -> TsvTable:
    """Convenience wrapper: decode UTF-8, then parse.

    Invalid bytes become U+FFFD instead of raising, so one bad
    byte cannot discard an entire file's data.
    """
    return parse_tsv(data.decode("utf-8", errors="replace"))
