"""psycopg async pool creation and migration runner.

Migrations live as plain .sql files under ``migrations/`` and are applied
in lexical order at startup. A bootstrap step creates the ``radar`` schema
and the ``radar.schema_migrations`` bookkeeping table before any migration
file runs, so migrations themselves assume ``CREATE SCHEMA`` is done.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from psycopg.rows import AsyncRowFactory
from psycopg_pool import AsyncConnectionPool

R = TypeVar("R")

_BOOTSTRAP_SQL = """
CREATE SCHEMA IF NOT EXISTS radar;
CREATE TABLE IF NOT EXISTS radar.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def create_pool(
    dsn: str, *, min_size: int = 1, max_size: int = 5
) -> AsyncConnectionPool:
    """Create and open an async connection pool against *dsn*."""
    pool: AsyncConnectionPool = AsyncConnectionPool(
        dsn, min_size=min_size, max_size=max_size, open=False
    )
    await pool.open()
    await pool.wait()
    return pool


async def execute(
    pool: AsyncConnectionPool,
    sql: str,
    params: Sequence[Any] = (),
) -> int:
    """Run one statement in its own transaction.

    Returns the affected row count.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            affected = cur.rowcount
        await conn.commit()
    return affected


async def fetch_all(
    pool: AsyncConnectionPool,
    sql: str,
    params: Sequence[Any] = (),
    *,
    row_factory: AsyncRowFactory[R],
) -> list[R]:
    """Run a query and return every row via *row_factory*."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=row_factory) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def fetch_one(
    pool: AsyncConnectionPool,
    sql: str,
    params: Sequence[Any] = (),
    *,
    row_factory: AsyncRowFactory[R],
) -> R | None:
    """Run a query and return the first row, or None."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=row_factory) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def fetch_scalar(
    pool: AsyncConnectionPool,
    sql: str,
    params: Sequence[Any] = (),
) -> Any | None:
    """Return the first column of the first row, or None.

    A missing row and a NULL value both read as None; callers
    needing the distinction should fetch the row instead.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
    if row is None:
        return None
    return row[0]


def _migration_files() -> list[Path]:
    migrations_dir = Path(__file__).parent / "migrations"
    return sorted(migrations_dir.glob("*.sql"))


async def apply_migrations(pool: AsyncConnectionPool) -> list[str]:
    """Apply any not-yet-applied migrations.

    Returns the list of versions that were applied during this call, in
    the order they ran. An empty list means everything was already up
    to date.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_BOOTSTRAP_SQL)
            await cur.execute(
                "SELECT version FROM radar.schema_migrations"
            )
            applied = {r[0] for r in await cur.fetchall()}
        await conn.commit()

    newly_applied: list[str] = []
    for path in _migration_files():
        version = path.name
        if version in applied:
            continue
        sql = path.read_text()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                await cur.execute(
                    "INSERT INTO radar.schema_migrations (version) "
                    "VALUES (%s)",
                    (version,),
                )
            await conn.commit()
        newly_applied.append(version)
    return newly_applied
