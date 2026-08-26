"""Deterministic rules for PostgreSQL configuration files.

These rules are registered under the "PostgreSQL Configuration"
category and run against parsed HBA rules, file_settings, and
the postgresql.auto.conf text.
"""

from __future__ import annotations

from typing import Any

from radar_analyst.parse.pg_conf import HbaRule
from radar_analyst.rules.base import Finding, register


# Connection types that reach the network: trust here is dangerous.
_NETWORK_TYPES = frozenset(
    {"host", "hostssl", "hostnossl", "hostgssenc", "hostnogssenc"}
)


@register("PostgreSQL Configuration")
def trust_method_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Critical when any network HBA rule uses trust authentication.

    ``local`` trust (Unix-socket) is intentional and common for the
    ``postgres`` superuser on a well-managed host. Network trust
    (type=host/hostssl/...) is a serious misconfiguration: any
    client that can reach the port gains unrestricted access.
    """
    rules: list[HbaRule] | None = parsed.get("pg.hba_file_rules")
    if not rules:
        return []
    bad = [
        r for r in rules
        if r.type in _NETWORK_TYPES
        and r.auth_method == "trust"
    ]
    if not bad:
        return []
    desc = ", ".join(
        f"{r.type}/{r.database}/{r.user_name}" for r in bad
    )
    return [
        Finding(
            rule_id="pg.conf.hba_trust",
            severity="critical",
            title=(
                f"{len(bad)} network HBA rule(s) use "
                "trust authentication"
            ),
            detail=(
                f"Rules with auth_method=trust for network "
                f"connections: {desc}. Any client that can "
                "reach the PostgreSQL port is granted access "
                "without a password. Replace with "
                "scram-sha-256 (preferred) or peer/cert. "
                "Leaving local-type rules as trust is fine; "
                "only network rules are flagged here."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def md5_method_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any HBA rule uses MD5 password authentication.

    MD5 sends a static hash derived from the password + username.
    It is not salted per-connection and is vulnerable to
    precomputation attacks. scram-sha-256 (server support since
    PG10, the ``password_encryption`` default since PG14) uses a
    proper challenge/response; all installations should use it.
    """
    rules: list[HbaRule] | None = parsed.get("pg.hba_file_rules")
    if not rules:
        return []
    bad = [r for r in rules if r.auth_method == "md5"]
    if not bad:
        return []
    desc = ", ".join(
        f"rule {r.rule_number} ({r.type}/{r.user_name})"
        for r in bad
    )
    return [
        Finding(
            rule_id="pg.conf.hba_md5",
            severity="warning",
            title=(
                f"{len(bad)} HBA rule(s) use MD5 authentication"
            ),
            detail=(
                f"Rules using auth_method=md5: {desc}. MD5 "
                "is a weak hash: not salted per-connection, "
                "vulnerable to precomputation. Migrate to "
                "scram-sha-256 (requires password rehash): "
                "update pg_hba.conf to scram-sha-256, then "
                "run ALTER ROLE … PASSWORD '…' for each "
                "affected user, and reload."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def hba_config_error(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any HBA rule has a parse error.

    PostgreSQL silently skips rules that it cannot parse; a rule
    with a non-empty ``error`` column in ``pg_hba_file_rules``
    was not applied and the intended access control is absent.
    """
    rules: list[HbaRule] | None = parsed.get("pg.hba_file_rules")
    if not rules:
        return []
    bad = [r for r in rules if r.error]
    if not bad:
        return []
    desc = "; ".join(
        f"rule {r.rule_number}: {r.error}" for r in bad
    )
    return [
        Finding(
            rule_id="pg.conf.hba_error",
            severity="warning",
            title=(
                f"{len(bad)} HBA rule(s) have a parse error"
            ),
            detail=(
                f"Rules skipped due to errors: {desc}. "
                "PostgreSQL ignores malformed pg_hba.conf "
                "lines; the intended access control policy "
                "is not in effect for those entries. Fix "
                "the syntax and reload (SELECT pg_reload_conf())."
            ),
        )
    ]


@register("PostgreSQL Configuration")
def alter_system_drift(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when postgresql.auto.conf contains active settings.

    ALTER SYSTEM writes settings into ``postgresql.auto.conf``,
    which overrides ``postgresql.conf`` at runtime. This creates
    a second source of truth that is not version-controlled and
    is invisible to configuration management tools. If ALTER
    SYSTEM was used intentionally, the settings should be migrated
    back to ``postgresql.conf``.
    """
    auto_conf: str | None = parsed.get("pg.conf.postgresql_auto")
    if not auto_conf:
        return []
    # The file always starts with a 2-line comment header.
    # A non-empty setting is any non-blank, non-comment line.
    has_settings = any(
        line.strip() and not line.strip().startswith("#")
        for line in auto_conf.splitlines()
    )
    if not has_settings:
        return []
    return [
        Finding(
            rule_id="pg.conf.alter_system_drift",
            severity="warning",
            title=(
                "postgresql.auto.conf contains runtime-set "
                "parameters (ALTER SYSTEM drift)"
            ),
            detail=(
                "postgresql.auto.conf has one or more settings "
                "written by ALTER SYSTEM. These override "
                "postgresql.conf and are invisible to version "
                "control. Review the settings, migrate them "
                "to postgresql.conf if intentional, and reset "
                "with ALTER SYSTEM RESET ALL to clear the file."
            ),
        )
    ]
