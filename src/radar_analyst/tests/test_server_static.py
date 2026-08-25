"""Tests for static-GUI serving."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_analyst.server.app import create_app
from radar_analyst.server.static import find_static_dir, mount_static


def test_find_static_dir_returns_path_when_build_exists() -> None:
    # This test runs only when Astro has been built; the dev
    # workflow always builds before running CI.
    path = find_static_dir()
    if path is None:
        pytest.skip("no Astro build present")
    assert (path / "index.html").is_file()


def test_mount_returns_false_when_no_build(
    tmp_path: Path, monkeypatch: "object"
) -> None:
    # Point the candidates at a non-existent directory.
    from radar_analyst.server import static as static_mod

    monkeypatch.setattr(  # type: ignore[attr-defined]
        static_mod,
        "_CANDIDATES",
        (tmp_path / "does-not-exist",),
    )
    app = create_app(serve_static=False)
    assert mount_static(app) is False


def test_healthz_still_works_with_static_mount() -> None:
    # When the GUI is present, /healthz must still return 200
    # rather than getting swallowed by the catch-all mount.
    app = create_app()  # default: serve_static=True
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200


def test_api_routes_not_shadowed_by_static(
    tmp_path: Path,
) -> None:
    # /api/config must always be reachable even with GUI mounted.
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body


def test_static_root_returns_html_if_built() -> None:
    if find_static_dir() is None:
        pytest.skip("no Astro build present")
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_unknown_api_path_returns_json_not_html() -> None:
    """The console mount is a catch-all, so it would otherwise
    answer a mistyped API path with an HTML 404."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/no-such-endpoint")
    assert resp.status_code == 404
    assert "application/json" in resp.headers.get(
        "content-type", ""
    )
    assert resp.json()["detail"] == "not found"


def test_unknown_api_path_is_json_for_every_method() -> None:
    app = create_app()
    with TestClient(app) as client:
        for call in (
            client.post,
            client.put,
            client.delete,
            client.patch,
        ):
            resp = call("/api/no-such-endpoint")
            assert resp.status_code == 404, call
            assert "application/json" in resp.headers.get(
                "content-type", ""
            ), call


def test_real_api_route_still_wins() -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 200
