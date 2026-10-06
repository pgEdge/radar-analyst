"""Every object in the `radar` schema carries a comment.

The schema is the contract between the analyst and anyone reading
its state with psql. A column called `verdict` or `storage_url`
means something specific, and the place that survives is the
database itself rather than a document beside it.
"""

from __future__ import annotations

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import apply_migrations, fetch_all


_EXPECTED_TABLES = frozenset(
    {
        "uploads",
        "jobs",
        "snapshots",
        "findings",
        "briefs",
        "schema_migrations",
    }
)


async def _rows(
    pool: AsyncConnectionPool, sql: str
) -> list[tuple[str, str, str | None]]:
    from psycopg.rows import tuple_row

    return await fetch_all(pool, sql, row_factory=tuple_row)


@pytest.mark.asyncio
async def test_every_table_is_commented(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)

    rows = await _rows(
        fresh_pool,
        """
        SELECT c.relname, 'table', obj_description(c.oid, 'pg_class')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'radar' AND c.relkind = 'r'
        """,
    )

    found = {name for name, _, _ in rows}
    assert found == _EXPECTED_TABLES, found
    missing = [name for name, _, comment in rows if not comment]
    assert not missing, f"tables without a comment: {missing}"


@pytest.mark.asyncio
async def test_every_column_is_commented(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)

    rows = await _rows(
        fresh_pool,
        """
        SELECT c.relname, a.attname,
               col_description(c.oid, a.attnum)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = 'radar'
          AND c.relkind = 'r'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """,
    )

    assert rows, "no columns found in the radar schema"
    missing = [
        f"{table}.{column}"
        for table, column, comment in rows
        if not comment
    ]
    assert not missing, f"columns without a comment: {missing}"


@pytest.mark.asyncio
async def test_every_index_is_commented(
    fresh_pool: AsyncConnectionPool,
) -> None:
    """Excluding the primary keys, which the table comment covers."""
    await apply_migrations(fresh_pool)

    rows = await _rows(
        fresh_pool,
        """
        SELECT c.relname, 'index',
               obj_description(c.oid, 'pg_class')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_index i ON i.indexrelid = c.oid
        WHERE n.nspname = 'radar'
          AND c.relkind = 'i'
          AND NOT i.indisprimary
        """,
    )

    assert rows, "no secondary indexes found in the radar schema"
    missing = [name for name, _, comment in rows if not comment]
    assert not missing, f"indexes without a comment: {missing}"


@pytest.mark.asyncio
async def test_comments_survive_a_second_run(
    fresh_pool: AsyncConnectionPool,
) -> None:
    """The runner is called on every start, not only the first."""
    await apply_migrations(fresh_pool)
    await apply_migrations(fresh_pool)

    rows = await _rows(
        fresh_pool,
        """
        SELECT c.relname, 'table', obj_description(c.oid, 'pg_class')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'radar' AND c.relkind = 'r'
        """,
    )
    assert {name for name, _, _ in rows} == _EXPECTED_TABLES
