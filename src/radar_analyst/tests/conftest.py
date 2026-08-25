"""Shared pytest fixtures (Postgres container + fresh pool)."""

from collections.abc import AsyncIterator, Iterator

import pytest
from psycopg_pool import AsyncConnectionPool
from testcontainers.postgres import PostgresContainer

from radar_analyst.store.db import create_pool


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:17-alpine") as pg:
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
