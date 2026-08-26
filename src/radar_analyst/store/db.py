"""psycopg async pool creation and migration runner.

Migrations live as plain .sql files under ``migrations/`` and are applied
in lexical order at startup. A bootstrap step creates the ``radar`` schema
and the ``radar.schema_migrations`` bookkeeping table before any migration
file runs, so migrations themselves assume ``CREATE SCHEMA`` is done.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import AsyncRowFactory
from psycopg_pool import AsyncConnectionPool


_logger = logging.getLogger(__name__)

R = TypeVar("R")

# Long enough to cover a PostgreSQL container running initdb on a
# fresh volume, short enough that a genuinely absent database is
# reported rather than waited on forever.
DEFAULT_WAIT_SECONDS = 60.0
_PROBE_INTERVAL = 0.5
_PROBE_CONNECT_TIMEOUT = 5

_BOOTSTRAP_SQL = """
CREATE SCHEMA IF NOT EXISTS radar;
CREATE TABLE IF NOT EXISTS radar.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _describe(dsn: str) -> str:
    """Return host:port for *dsn*, without its password."""
    try:
        info = conninfo_to_dict(dsn)
    except psycopg.Error:
        return "the configured database"
    host = info.get("host") or "localhost"
    port = info.get("port") or 5432
    return f"{host}:{port}"


async def wait_for_server(
    dsn: str,
    *,
    timeout: float = DEFAULT_WAIT_SECONDS,
    interval: float = _PROBE_INTERVAL,
) -> None:
    """Block until *dsn* accepts a connection, or raise TimeoutError.

    The database usually starts alongside the analyst, so the first
    attempt being refused says nothing about whether the deployment
    is sound. Probing directly at a steady interval, rather than
    leaving it to the pool, matters: psycopg-pool doubles its own
    delay after each failure, so one refusal early on can leave the
    pool idle for sixteen seconds while the server is already up.

    The error names the address but never the password, because a
    failed startup is written to logs.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            conn = await psycopg.AsyncConnection.connect(
                dsn, connect_timeout=_PROBE_CONNECT_TIMEOUT
            )
        except psycopg.OperationalError as error:
            last_error = error
        else:
            await conn.close()
            return
        if time.monotonic() >= deadline:
            break
        _logger.info(
            "waiting for the database at %s", _describe(dsn)
        )
        await asyncio.sleep(interval)
    raise TimeoutError(
        f"the database at {_describe(dsn)} did not accept a "
        f"connection within {timeout:.0f}s: {last_error}"
    )


def check_server_encoding(value: object) -> None:
    """Refuse a database that hands text back as bytes.

    Under SQL_ASCII psycopg returns ``bytes`` for every text column,
    and nothing complains at connection time. What breaks is later
    and quieter: a job whose ``state`` never equals ``"done"``, a
    progress stream that waits forever for a job that has already
    finished, and a 500 from the first rule to call a string method.
    One check at startup turns all of that into one message.
    """
    if isinstance(value, bytes) or value == "SQL_ASCII":
        raise RuntimeError(
            "the state database uses the SQL_ASCII encoding, so "
            "PostgreSQL returns text as raw bytes and the analyst "
            "cannot read its own rows. Recreate it with UTF8: the "
            'container image takes POSTGRES_INITDB_ARGS="--encoding'
            '=UTF8 --locale=C.UTF-8", and initdb takes the same '
            "arguments directly."
        )
    if value != "UTF8":
        _logger.warning(
            "the state database uses the %s encoding; UTF8 is "
            "expected and anything else may mangle text taken "
            "from a radar archive",
            value,
        )


async def check_encoding(pool: AsyncConnectionPool) -> None:
    """Read the server encoding and refuse an unusable one."""
    check_server_encoding(
        await fetch_scalar(
            pool, "SELECT current_setting('server_encoding')"
        )
    )


async def create_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 5,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> AsyncConnectionPool:
    """Create and open an async connection pool against *dsn*."""
    await wait_for_server(dsn, timeout=wait_seconds)
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
    async with pool.connection() as conn, conn.cursor() as cur:
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
