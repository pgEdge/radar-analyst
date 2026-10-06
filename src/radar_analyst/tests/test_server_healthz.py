"""Smoke tests for the FastAPI app skeleton and its probes."""

import socket

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from radar_analyst.server.app import create_app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert app is not None
    assert app.title


def test_healthz_returns_200_ok() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_503_until_pool_attached() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503


async def test_readyz_is_ready_while_the_database_answers(
    fresh_pool: AsyncConnectionPool,
) -> None:
    app = create_app(pool=fresh_pool)
    async with _client(app) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


async def test_readyz_503_when_the_database_does_not_answer() -> None:
    # Nothing listens on the port, so the pool never gets a
    # connection to hand out.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    pool = AsyncConnectionPool(
        f"host=127.0.0.1 port={port} dbname=radar user=radar",
        open=False,
    )
    await pool.open(wait=False)
    try:
        async with _client(create_app(pool=pool)) as client:
            resp = await client.get("/readyz")
    finally:
        await pool.close()
    assert resp.status_code == 503
