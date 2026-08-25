"""Compiled-in end-of-life schedules for Postgres and OS releases.

Both schedules need annual maintenance: keep this file as the
single source of truth so the audit is one diff.

Sources:
- PostgreSQL: https://www.postgresql.org/support/versioning/
  Each major receives 5 years of support after first GA.
- Linux distros: vendor-published lifecycle pages. Only the
  distros pgEdge customers actually run are covered. Add
  entries on demand.

EOL dates here use ISO ``YYYY-MM-DD``. The rule layer only
needs day granularity.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------
# PostgreSQL community majors
# ---------------------------------------------------------------------
# Source: https://www.postgresql.org/support/versioning/
PG_MAJOR_EOL: dict[int, date] = {
    11: date(2023, 11, 9),
    12: date(2024, 11, 14),
    13: date(2025, 11, 13),
    14: date(2026, 11, 12),
    15: date(2027, 11, 11),
    16: date(2028, 11, 9),
    17: date(2029, 11, 8),
    18: date(2030, 11, 13),
}


# ---------------------------------------------------------------------
# Operating systems: kept narrow on purpose.
# ---------------------------------------------------------------------
# Maps a (id, version_id) tuple from /etc/os-release to its
# vendor-supported EOL date. The matcher in the rule layer
# normalises the version_id (strips ".x" minor, etc.) before
# lookup.
OS_EOL: dict[tuple[str, str], date] = {
    # Red Hat family
    ("rhel", "7"): date(2024, 6, 30),
    ("rhel", "8"): date(2029, 5, 31),
    ("rhel", "9"): date(2032, 5, 31),
    ("rhel", "10"): date(2035, 5, 31),
    ("rocky", "8"): date(2029, 5, 31),
    ("rocky", "9"): date(2032, 5, 31),
    ("rocky", "10"): date(2035, 5, 31),
    ("almalinux", "8"): date(2029, 5, 31),
    ("almalinux", "9"): date(2032, 5, 31),
    ("almalinux", "10"): date(2035, 5, 31),
    ("centos", "7"): date(2024, 6, 30),
    ("centos", "8"): date(2021, 12, 31),
    # Debian family
    ("debian", "10"): date(2024, 6, 30),
    ("debian", "11"): date(2026, 8, 31),
    ("debian", "12"): date(2028, 6, 30),
    ("debian", "13"): date(2030, 6, 30),
    ("ubuntu", "18.04"): date(2023, 5, 31),
    ("ubuntu", "20.04"): date(2025, 5, 29),
    ("ubuntu", "22.04"): date(2027, 5, 31),
    ("ubuntu", "24.04"): date(2029, 5, 31),
    # Amazon Linux
    ("amzn", "2"): date(2026, 6, 30),
    ("amzn", "2023"): date(2028, 3, 15),
    # SUSE
    ("sles", "12"): date(2027, 10, 31),
    ("sles", "15"): date(2031, 7, 31),
    ("opensuse-leap", "15.5"): date(2024, 12, 31),
    ("opensuse-leap", "15.6"): date(2025, 12, 31),
}
