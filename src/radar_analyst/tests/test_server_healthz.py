"""Smoke tests for the FastAPI app skeleton and /healthz."""

from fastapi.testclient import TestClient

from radar_analyst.server.app import create_app


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


def test_readyz_ready_with_pool() -> None:
    app = create_app()
    app.state.pool = object()
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
