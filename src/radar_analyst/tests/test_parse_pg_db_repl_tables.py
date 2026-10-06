"""Tests for parse/pg_db_repl_tables.py."""

from radar_analyst.parse.pg_db_repl_tables import (
    PublishedTable,
    SubscriptionRel,
    parse_publication_tables,
    parse_subscription_tables,
)


def test_publications_empty_returns_empty() -> None:
    assert parse_publication_tables(b"") == []


def test_publications_missing_columns() -> None:
    tsv = "schemaname\ttablename\npublic\tt\n"
    assert parse_publication_tables(tsv.encode()) == []


def test_publications_parses_rows() -> None:
    tsv = (
        "pubname\tschemaname\ttablename\n"
        "pub_orders\tpublic\torders\n"
        "pub_orders\tpublic\torder_items\n"
        "pub_users\tpublic\tusers\n"
    )
    out = parse_publication_tables(tsv.encode())
    assert len(out) == 3
    assert isinstance(out[0], PublishedTable)
    assert out[0].fqname == "public.orders"


def test_subscription_tables_empty() -> None:
    assert parse_subscription_tables(b"") == []


def test_subscription_tables_state_labels() -> None:
    tsv = (
        "srsubid\tsrrelid\tsrsubstate\tsrsublsn\n"
        "10\t100\tr\t0/16B6098\n"
        "10\t101\td\t\n"
    )
    out = parse_subscription_tables(tsv.encode())
    assert isinstance(out[0], SubscriptionRel)
    assert out[0].state_label == "ready"
    assert out[1].state_label == "copying data"
