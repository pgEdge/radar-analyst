"""Parse ``postgresql/configuration.tsv`` (output of ``pg_settings``).

Radar's query (postgres_tasks.go) selects ``name, setting, unit,
category, short_desc``. It does NOT include ``boot_val`` or
``source``, so rows cannot be filtered to non-default ones at parse
time; the parser is a faithful representation of radar's output and
consumers pick the settings they care about by name.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.tsv import parse_tsv_bytes


_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"name", "setting", "unit", "category", "short_desc"}
)


@dataclass(frozen=True)
class PgSetting:
    """One pg_settings row."""
    name: str
    setting: str
    unit: str
    category: str
    short_desc: str


@dataclass(frozen=True)
class PgSettings:
    """All settings, addressable by name."""
    all: dict[str, PgSetting]

    def get(self, name: str) -> PgSetting | None:
        """The named setting's row, or None."""
        return self.all.get(name)


def parse_pg_settings(data: bytes) -> PgSettings:
    """Parse configuration.tsv into a ``PgSettings`` value.

    Empty / missing files yield an empty ``PgSettings``. Rows missing
    any required column are skipped (defensive: radar's query could
    change upstream without breaking us).
    """
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return PgSettings(all={})
    all_: dict[str, PgSetting] = {}
    for row in table.rows:
        name = row.get("name", "")
        if not name:
            continue
        all_[name] = PgSetting(
            name=name,
            setting=row.get("setting", ""),
            unit=row.get("unit", ""),
            category=row.get("category", ""),
            short_desc=row.get("short_desc", ""),
        )
    return PgSettings(all=all_)
