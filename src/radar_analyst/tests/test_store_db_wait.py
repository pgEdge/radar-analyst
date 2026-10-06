"""Waiting for a database that is still starting.

Under docker-compose, systemd, or a package install the PostgreSQL
the analyst uses often starts at the same moment the analyst does.
Refusing to serve because the first connection attempt was refused
would make a correct deployment look broken, so startup waits.
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from radar_analyst.store.db import wait_for_server


_DSN = "postgresql://radar_analyst@db:5432/radar_analyst"


class _FakeConnection:
    """Records that the probe connection was closed."""

    def __init__(self, closed: list[bool]) -> None:
        self._closed = closed

    async def close(self) -> None:
        self._closed.append(True)


def _connect_failing_times(
    failures: int, closed: list[bool]
) -> Any:
    """Build a connect() that refuses *failures* times, then works."""
    attempts = {"n": 0}

    async def fake_connect(*args: Any, **kwargs: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] <= failures:
            raise psycopg.OperationalError("connection refused")
        return _FakeConnection(closed)

    fake_connect.attempts = attempts  # type: ignore[attr-defined]
    return fake_connect


async def test_returns_as_soon_as_the_server_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []
    connect = _connect_failing_times(0, closed)
    monkeypatch.setattr(
        psycopg.AsyncConnection, "connect", connect
    )

    await wait_for_server(_DSN, timeout=5.0, interval=0.01)

    assert connect.attempts["n"] == 1
    assert closed == [True], "the probe connection was not closed"


async def test_retries_while_connections_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database still running initdb is not a failed deployment."""
    closed: list[bool] = []
    connect = _connect_failing_times(4, closed)
    monkeypatch.setattr(
        psycopg.AsyncConnection, "connect", connect
    )

    await wait_for_server(_DSN, timeout=5.0, interval=0.01)

    assert connect.attempts["n"] == 5


async def test_keeps_a_steady_interval_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No growing backoff: a long gap is what broke this before.

    psycopg-pool doubles its own delay after each failure, so a
    refusal in the first second could leave sixteen seconds with no
    attempt at all while the server sat there ready.
    """
    closed: list[bool] = []
    connect = _connect_failing_times(6, closed)
    monkeypatch.setattr(
        psycopg.AsyncConnection, "connect", connect
    )
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        slept.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    await wait_for_server(_DSN, timeout=5.0, interval=0.25)

    assert slept == [0.25] * 6, slept


async def test_gives_up_with_a_message_naming_the_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database that never appears must say so, not hang."""
    closed: list[bool] = []
    connect = _connect_failing_times(10_000, closed)
    monkeypatch.setattr(
        psycopg.AsyncConnection, "connect", connect
    )

    with pytest.raises(TimeoutError) as excinfo:
        await wait_for_server(_DSN, timeout=0.05, interval=0.01)

    message = str(excinfo.value)
    assert "connection refused" in message
    assert "db:5432" in message


async def test_the_password_is_not_repeated_in_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup errors reach logs; the DSN carries a password."""
    closed: list[bool] = []
    connect = _connect_failing_times(10_000, closed)
    monkeypatch.setattr(
        psycopg.AsyncConnection, "connect", connect
    )
    dsn = "postgresql://radar_analyst:hunter2@db:5432/radar_analyst"

    with pytest.raises(TimeoutError) as excinfo:
        await wait_for_server(dsn, timeout=0.05, interval=0.01)

    assert "hunter2" not in str(excinfo.value)
