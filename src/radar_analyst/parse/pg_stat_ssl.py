"""Parse ``postgresql/stat_ssl.tsv``.

Radar joins ``pg_stat_ssl`` with ``pg_stat_activity``, returning
one row per backend with ``pid, ssl, version, cipher, bits,
client_dn, client_serial, issuer_dn, usename, application_name,
client_addr``.

Privilege caveat: only superusers (or members of
``pg_read_all_stats``) see every backend, so a non-privileged
collection produces a partial table. The parser reports the rows
as collected and does not compensate.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.coerce import (
    as_bool,
)
from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class SslConnection:
    """One backend's SSL state."""
    pid: str
    ssl: bool
    version: str = ""
    cipher: str = ""
    bits: str = ""
    client_dn: str = ""
    usename: str = ""
    application_name: str = ""
    client_addr: str = ""


@dataclass(frozen=True)
class StatSsl:
    """All backends' SSL rows."""
    rows: list[SslConnection]

    def __len__(self) -> int:
        """Return how many rows were parsed."""
        return len(self.rows)

    def insecure(self) -> list[SslConnection]:
        """Return the backends not using SSL.

        Excludes the special ``pid = NULL`` row that some
        PostgreSQL versions emit.
        """
        return [
            r for r in self.rows
            if r.pid and not r.ssl
        ]


_REQUIRED_COLUMNS: frozenset[str] = frozenset({"pid", "ssl"})


def parse_stat_ssl(data: bytes) -> StatSsl:
    """Parse ``stat_ssl.tsv`` into a ``StatSsl`` snapshot."""
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return StatSsl(rows=[])

    out: list[SslConnection] = []
    for r in table.rows:
        pid = r.get("pid", "").strip()
        if not pid:
            continue
        out.append(
            SslConnection(
                pid=pid,
                ssl=as_bool(r.get("ssl", "")),
                version=r.get("version", "") or "",
                cipher=r.get("cipher", "") or "",
                bits=r.get("bits", "") or "",
                client_dn=r.get("client_dn", "") or "",
                usename=r.get("usename", "") or "",
                application_name=(
                    r.get("application_name", "") or ""
                ),
                client_addr=r.get("client_addr", "") or "",
            )
        )
    return StatSsl(rows=out)
