"""Tests for the migration runner and the query helpers."""

from pathlib import Path

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import apply_migrations, execute


async def test_apply_migrations_creates_the_radar_schema(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    async with fresh_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = 'radar'"
        )
        assert await cur.fetchone() is not None


async def test_apply_migrations_creates_expected_tables(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    expected = {
        "schema_migrations",
        "uploads",
        "jobs",
        "snapshots",
        "findings",
        "briefs",
    }
    async with fresh_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'radar'"
        )
        rows = await cur.fetchall()
    got = {r[0] for r in rows}
    assert expected <= got, f"missing: {expected - got}"


async def test_apply_migrations_is_idempotent(
    fresh_pool: AsyncConnectionPool,
) -> None:
    first = await apply_migrations(fresh_pool)
    second = await apply_migrations(fresh_pool)
    assert first, "first run should apply at least one migration"
    assert second == [], "second run must be a no-op"


async def test_apply_migrations_records_version(
    fresh_pool: AsyncConnectionPool,
) -> None:
    applied = await apply_migrations(fresh_pool)
    async with fresh_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT version FROM radar.schema_migrations "
            "ORDER BY version"
        )
        rows = await cur.fetchall()
    versions = [r[0] for r in rows]
    assert versions == applied


async def test_a_new_migration_upgrades_an_existing_database(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the runner exists.

    A build that has moved on has to open a data directory written by
    an older one, apply what is missing, and leave the rows already
    there untouched. Squashing the shipped migrations while
    pre-release does not change that: the next schema change after
    something is deployed goes into a new file, and this is what has
    to happen when it does.
    """
    from radar_analyst.store import db

    first = tmp_path / "0001_thing.sql"
    first.write_text(
        "CREATE TABLE radar.thing (id INT PRIMARY KEY);"
    )
    monkeypatch.setattr(db, "_migration_files", lambda: [first])

    assert await apply_migrations(fresh_pool) == ["0001_thing.sql"]
    await execute(
        fresh_pool, "INSERT INTO radar.thing (id) VALUES (1)"
    )

    second = tmp_path / "0002_more.sql"
    second.write_text(
        "ALTER TABLE radar.thing ADD COLUMN label TEXT;"
    )
    monkeypatch.setattr(
        db, "_migration_files", lambda: [first, second]
    )

    applied = await apply_migrations(fresh_pool)

    assert applied == ["0002_more.sql"], "only the new one runs"
    async with fresh_pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, label FROM radar.thing")
        rows = await cur.fetchall()
    assert rows == [(1, None)], "the existing row did not survive"


async def test_apply_migrations_preserves_existing_rows(
    fresh_pool: AsyncConnectionPool,
) -> None:
    """A restart must not drop what is already stored."""
    from uuid import uuid4

    from radar_analyst.store.uploads import (
        insert_upload,
        list_uploads,
    )

    await apply_migrations(fresh_pool)
    await insert_upload(
        fresh_pool,
        upload_id=uuid4(),
        filename="radar-host.zip",
        storage_url="file:///tmp/x.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )

    await apply_migrations(fresh_pool)

    assert len(await list_uploads(fresh_pool)) == 1


async def test_execute_returns_rowcount(
    fresh_pool: AsyncConnectionPool,
) -> None:
    from radar_analyst.store.db import execute

    await execute(
        fresh_pool,
        "CREATE TABLE radar_t_exec (n INT)",
    )
    affected = await execute(
        fresh_pool,
        "INSERT INTO radar_t_exec VALUES (%s), (%s)",
        (1, 2),
    )
    assert affected == 2


async def test_fetch_helpers_roundtrip(
    fresh_pool: AsyncConnectionPool,
) -> None:
    from dataclasses import dataclass

    from psycopg.rows import class_row

    from radar_analyst.store.db import (
        execute,
        fetch_all,
        fetch_one,
        fetch_scalar,
    )

    @dataclass
    class Pair:
        a: int
        b: str

    await execute(
        fresh_pool,
        "CREATE TABLE radar_t_fetch (a INT, b TEXT)",
    )
    await execute(
        fresh_pool,
        "INSERT INTO radar_t_fetch VALUES (1, 'x'), (2, 'y')",
    )
    rows = await fetch_all(
        fresh_pool,
        "SELECT a, b FROM radar_t_fetch ORDER BY a",
        row_factory=class_row(Pair),
    )
    assert rows == [Pair(a=1, b="x"), Pair(a=2, b="y")]
    one = await fetch_one(
        fresh_pool,
        "SELECT a, b FROM radar_t_fetch WHERE a = %s",
        (2,),
        row_factory=class_row(Pair),
    )
    assert one == Pair(a=2, b="y")
    none = await fetch_one(
        fresh_pool,
        "SELECT a, b FROM radar_t_fetch WHERE a = %s",
        (99,),
        row_factory=class_row(Pair),
    )
    assert none is None
    val = await fetch_scalar(
        fresh_pool,
        "SELECT b FROM radar_t_fetch WHERE a = %s",
        (1,),
    )
    assert val == "x"
    missing = await fetch_scalar(
        fresh_pool,
        "SELECT b FROM radar_t_fetch WHERE a = %s",
        (99,),
    )
    assert missing is None
