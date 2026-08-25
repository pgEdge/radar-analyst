"""Parse per-database publication / subscription table TSVs.

Both files map a relation to either a publication or a
subscription. radar collects:

- ``publication_tables.tsv``: ``pg_publication_tables``,
  columns: ``pubname, schemaname, tablename`` (and a few more
  in newer PG versions for column / row filters).
- ``subscription_tables.tsv``: ``pg_subscription_rel``,
  columns: ``srsubid, srrelid, srsubstate, srsublsn``.

We don't try to resolve OIDs: the `srrelid::regclass` cast
isn't always in the dump. The downstream prompt-builder
surfaces names where they're available and counts otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class PublishedTable:
    """One pg_publication_tables row."""
    pubname: str
    schemaname: str
    tablename: str

    @property
    def fqname(self) -> str:
        """Schema-qualified table name."""
        return f"{self.schemaname}.{self.tablename}"


def parse_publication_tables(
    data: bytes,
) -> list[PublishedTable]:
    """Parse publication_tables.tsv."""
    table = parse_tsv_bytes(data)
    required = {"pubname", "schemaname", "tablename"}
    if not required.issubset(table.columns):
        return []
    out: list[PublishedTable] = []
    for r in table.rows:
        pub = r.get("pubname", "")
        schema = r.get("schemaname", "")
        name = r.get("tablename", "")
        if not pub or not schema or not name:
            continue
        out.append(
            PublishedTable(
                pubname=pub,
                schemaname=schema,
                tablename=name,
            )
        )
    return out


@dataclass(frozen=True)
class SubscriptionRel:
    """One pg_subscription_rel row."""
    srsubid: str
    srrelid: str
    srsubstate: str = ""

    @property
    def state_label(self) -> str:
        # Postgres state codes documented in pg_subscription_rel:
        # 'i' = initialize, 'd' = data is being copied,
        # 'f' = finished table copy, 's' = synchronized,
        # 'r' = ready.
        """Human-readable subscription-relation state."""
        return {
            "i": "initializing",
            "d": "copying data",
            "f": "finished copy",
            "s": "synchronized",
            "r": "ready",
        }.get(self.srsubstate, self.srsubstate or "unknown")


def parse_subscription_tables(
    data: bytes,
) -> list[SubscriptionRel]:
    """Parse subscription_tables.tsv."""
    table = parse_tsv_bytes(data)
    required = {"srsubid", "srrelid"}
    if not required.issubset(table.columns):
        return []
    out: list[SubscriptionRel] = []
    for r in table.rows:
        sub = r.get("srsubid", "")
        rel = r.get("srrelid", "")
        if not sub or not rel:
            continue
        out.append(
            SubscriptionRel(
                srsubid=sub,
                srrelid=rel,
                srsubstate=r.get("srsubstate", "") or "",
            )
        )
    return out
