"""The connection pool is configured, not left on its defaults.

psycopg-pool defaults to a minimum of four connections and never
validates one before handing it out. The analyst is a single-user
tool whose database may be restarted underneath it, so it wants a
small pool and a liveness check on checkout rather than an error on
the first query after a restart.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import pool_settings


def test_the_pool_is_small() -> None:
    """One user at a time does not need psycopg-pool's default four."""
    settings = pool_settings()
    assert settings["min_size"] == 1
    assert settings["max_size"] == 5


def test_connections_are_checked_before_use() -> None:
    """A restarted database must not surface as a failed request.

    Without this the pool hands out a connection closed by the
    server's restart, and the caller sees the error instead of the
    pool quietly replacing it.
    """
    assert (
        pool_settings()["check"]
        is AsyncConnectionPool.check_connection
    )


def test_idle_and_lifetime_ceilings_are_explicit() -> None:
    settings = pool_settings()
    assert settings["max_idle"] > 0
    assert settings["max_lifetime"] > settings["max_idle"]


def test_the_sizes_are_overridable() -> None:
    settings = pool_settings(min_size=2, max_size=9)
    assert settings["min_size"] == 2
    assert settings["max_size"] == 9


def test_every_setting_is_a_real_pool_argument() -> None:
    """A typo here would otherwise be a TypeError at startup."""
    import inspect

    accepted = set(
        inspect.signature(AsyncConnectionPool.__init__).parameters
    )
    unknown = set(pool_settings()) - accepted
    assert not unknown, unknown
