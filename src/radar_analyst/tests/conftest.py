"""Shared pytest fixtures (Postgres container + fresh pool).

The suite runs against the same PostgreSQL the deployment does: the
pgEdge minimal image, not upstream `postgres`. The two differ in
ways that matter, and testing against the wrong one hides bugs that
only appear in production. `RADAR_ANALYST_PG_MAJOR` selects the
major version, so CI can run the whole suite across 16, 17, and 18.
"""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from psycopg_pool import AsyncConnectionPool
from testcontainers.postgres import PostgresContainer

from radar_analyst.store.db import create_pool


DEFAULT_PG_MAJOR = "18"


def pg_major() -> str:
    """Return the PostgreSQL major version under test."""
    return os.environ.get("RADAR_ANALYST_PG_MAJOR") or DEFAULT_PG_MAJOR


def pg_image(major: str) -> str:
    """Return the pgEdge image for *major*."""
    return f"ghcr.io/pgedge/pgedge-postgres:{major}-spock5-minimal"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    container = (
        PostgresContainer(pg_image(pg_major()))
        # This image's initdb defaults to SQL_ASCII, under which
        # psycopg returns every text column as raw bytes.
        .with_env(
            "POSTGRES_INITDB_ARGS",
            "--encoding=UTF8 --locale=C.UTF-8",
        )
        # listen_addresses so the published port reaches the server,
        # and logging_collector off so the readiness line testcontainers
        # waits for reaches stdout instead of a file inside the
        # container.
        .with_command(
            "postgres -c listen_addresses=* -c logging_collector=off"
        )
    )
    with container as pg:
        yield pg


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container: PostgresContainer) -> str:
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    pw = postgres_container.password
    db = postgres_container.dbname
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


@pytest.fixture
async def fresh_pool(
    postgres_dsn: str,
) -> AsyncIterator[AsyncConnectionPool]:
    """Return an open pool with the radar schema dropped clean first."""
    pool = await create_pool(postgres_dsn)
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DROP SCHEMA IF EXISTS radar CASCADE")
            await conn.commit()
        yield pool
    finally:
        await pool.close()
