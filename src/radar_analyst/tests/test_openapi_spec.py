"""The committed OpenAPI spec matches the code that serves it.

A generated file checked into a repository drifts the moment someone
changes a route and forgets to regenerate it, and a stale API
description is worse than none: it is believed. This test is the
whole answer to that. It fails the moment the two disagree and says
what to run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar_analyst.server.app import create_app


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = _REPO_ROOT / "docs" / "api" / "openapi.json"

pytestmark = pytest.mark.skipif(
    not (_REPO_ROOT / "docs").is_dir(),
    reason="docs are only present in a source checkout",
)


def current_spec() -> dict[str, object]:
    """Return the OpenAPI document the service would serve."""
    app = create_app(serve_static=False)
    spec: dict[str, object] = app.openapi()
    return spec


def test_the_committed_spec_is_current() -> None:
    """Regenerate with `make openapi` when this fails."""
    assert _SPEC.is_file(), f"{_SPEC} is missing; run `make openapi`"

    committed = json.loads(_SPEC.read_text())
    assert committed == current_spec(), (
        "docs/api/openapi.json no longer matches the routes; run "
        "`make openapi` and commit the result"
    )


def test_the_spec_documents_every_api_route() -> None:
    """A route that never reaches the spec is undocumented in practice."""
    spec = current_spec()
    paths = spec["paths"]
    assert isinstance(paths, dict)

    documented = set(paths)
    expected = {
        "/api/uploads",
        "/api/uploads/{upload_id}",
        "/api/uploads/{upload_id}/snapshot",
        "/api/uploads/{upload_id}/assessment",
        "/api/uploads/{upload_id}/files",
        "/api/uploads/{upload_id}/files/{archive_path}",
        "/api/jobs/{job_id}",
        "/api/jobs/{job_id}/events",
        "/api/config",
        "/healthz",
        "/readyz",
    }
    missing = expected - documented
    assert not missing, f"routes absent from the spec: {missing}"


def test_the_spec_names_the_service_and_its_version() -> None:
    from radar_analyst import __version__

    info = current_spec()["info"]
    assert isinstance(info, dict)
    assert info["title"] == "radar-analyst"
    assert info["version"] == __version__
