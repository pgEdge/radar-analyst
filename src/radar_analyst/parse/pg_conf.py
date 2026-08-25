"""Parsers for PostgreSQL configuration file data.

Covers:
- ``postgresql/file_settings.tsv`` : pg_file_settings view
- ``postgresql/pg_hba_file_rules.tsv``: pg_hba_file_rules view
- ``postgresql/db_role_setting.tsv``: pg_db_role_setting view
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class FileSetting:
    """One row from pg_file_settings (parsed postgresql.conf)."""

    name: str
    setting: str
    applied: bool
    error: str      # empty string when no error
    sourcefile: str
    sourceline: int


def parse_file_settings(
    data: bytes,
) -> list[FileSetting] | None:
    """Parse ``postgresql/file_settings.tsv``.

    Returns ``None`` for completely empty input; ``[]`` when the
    table has no data rows.
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    out: list[FileSetting] = []
    for r in t.rows:
        name = r.get("name") or ""
        if not name:
            continue
        applied_raw = (r.get("applied") or "").lower()
        try:
            sourceline = int(r.get("sourceline") or "0")
        except ValueError:
            sourceline = 0
        out.append(
            FileSetting(
                name=name,
                setting=r.get("setting") or "",
                applied=applied_raw in ("t", "true", "1"),
                error=r.get("error") or "",
                sourcefile=r.get("sourcefile") or "",
                sourceline=sourceline,
            )
        )
    return out


@dataclass(frozen=True)
class HbaRule:
    """One row from pg_hba_file_rules."""

    rule_number: int
    type: str           # local | host | hostssl | hostnossl | ...
    database: str       # raw PostgreSQL array string, e.g. "{all}"
    user_name: str      # raw PostgreSQL array string
    address: str        # empty for local rules
    auth_method: str    # trust | md5 | scram-sha-256 | peer | ...
    options: str        # empty when none
    error: str          # empty when rule is valid


def parse_hba_file_rules(
    data: bytes,
) -> list[HbaRule] | None:
    """Parse ``postgresql/pg_hba_file_rules.tsv``.

    Returns ``None`` for completely empty input; ``[]`` when the
    table has no data rows.
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    out: list[HbaRule] = []
    for r in t.rows:
        type_val = r.get("type") or ""
        if not type_val:
            continue
        try:
            rule_number = int(r.get("rule_number") or "0")
        except ValueError:
            rule_number = 0
        out.append(
            HbaRule(
                rule_number=rule_number,
                type=type_val,
                database=r.get("database") or "",
                user_name=r.get("user_name") or "",
                address=r.get("address") or "",
                auth_method=r.get("auth_method") or "",
                options=r.get("options") or "",
                error=r.get("error") or "",
            )
        )
    return out


@dataclass(frozen=True)
class DbRoleSetting:
    """One row from pg_db_role_setting."""

    setdatabase: str  # OID or "0" for cluster-wide
    setrole: str      # OID or "0" for all roles
    setconfig: str    # raw PostgreSQL array string, e.g. "{work_mem=64MB}"


def parse_db_role_setting(
    data: bytes,
) -> list[DbRoleSetting] | None:
    """Parse ``postgresql/db_role_setting.tsv``.

    Returns ``None`` for completely empty input; ``[]`` when the
    table has no data rows.
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    out: list[DbRoleSetting] = []
    for r in t.rows:
        setdatabase = r.get("setdatabase") or ""
        if not setdatabase:
            continue
        out.append(
            DbRoleSetting(
                setdatabase=setdatabase,
                setrole=r.get("setrole") or "",
                setconfig=r.get("setconfig") or "",
            )
        )
    return out
