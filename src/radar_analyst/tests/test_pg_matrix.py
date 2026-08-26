"""The suite runs on the PostgreSQL the deployment actually uses.

Upstream `postgres` and the pgEdge image differ in ways that reach
this code. Upstream defaults to UTF8; the pgEdge image defaults to
SQL_ASCII, under which psycopg hands back every text column as raw
bytes. Running the fast suite against the wrong one is how a bug
that only appears in production clears nine hundred tests: it
happened, and the encoding check exists because of it.
"""

from __future__ import annotations

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import check_server_encoding, fetch_scalar
from radar_analyst.tests.conftest import (
    DEFAULT_PG_MAJOR,
    pg_image,
    pg_major,
)


def test_the_image_is_pgedge_not_upstream() -> None:
    """Upstream postgres is not what any deployment runs."""
    image = pg_image(pg_major())
    assert image.startswith("ghcr.io/pgedge/pgedge-postgres:")
    assert "alpine" not in image


@pytest.mark.parametrize("major", ["16", "17", "18"])
def test_every_matrix_version_names_a_real_tag(major: str) -> None:
    """The tags CI iterates over must be the ones that exist."""
    assert pg_image(major) == (
        f"ghcr.io/pgedge/pgedge-postgres:{major}-spock5-minimal"
    )


def test_the_default_major_is_in_the_matrix() -> None:
    assert DEFAULT_PG_MAJOR in {"16", "17", "18"}


async def test_the_server_is_the_requested_major(
    fresh_pool: AsyncConnectionPool,
) -> None:
    """Otherwise a matrix run could silently test one version thrice."""
    version = await fetch_scalar(
        fresh_pool, "SHOW server_version"
    )
    assert isinstance(version, str)
    assert version.split(".")[0] == pg_major(), version


async def test_the_test_database_is_utf8(
    fresh_pool: AsyncConnectionPool,
) -> None:
    """The same check startup makes, made against the test database.

    If this fails, every text column in the suite is bytes and the
    failures downstream will look like anything but an encoding
    problem.
    """
    encoding = await fetch_scalar(
        fresh_pool, "SELECT current_setting('server_encoding')"
    )
    assert isinstance(encoding, str), "text came back as bytes"
    check_server_encoding(encoding)
    assert encoding == "UTF8"
