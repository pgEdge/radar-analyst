"""Parse ``postgresql/postmaster_start_time.tsv``.

Single-row TSV with a ``start_time`` column carrying a Postgres
``timestamp with time zone`` value, e.g.
``2026-04-30 10:26:54.03875 +0100 BST``.

Kept as the raw string for display: Python's ``%z`` parser
doesn't accept the trailing ``BST``-style abbreviation, so
attempting to round-trip through ``datetime`` adds fragility
without buying anything: snapshot consumers want to read it,
not arithmetic against it.
"""

from __future__ import annotations

from radar_analyst.parse.tsv import parse_tsv_bytes


def parse_postmaster_start_time(data: bytes) -> str | None:
    """The postmaster start timestamp, or None."""
    table = parse_tsv_bytes(data)
    if not table.rows:
        return None
    row = table.rows[0]
    value = (row.get("start_time") or "").strip()
    return value or None
