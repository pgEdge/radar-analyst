"""The entrypoint's bundled-deployment behaviour.

One ``docker run`` has to be enough: the analyst starts its own
PostgreSQL, keeps archives beside it, and can authenticate a delete
without the operator inventing a shared secret first. Pointing
``RADAR_ANALYST_STATE_DB_URL`` at an existing database has to switch
all of that off, because that is how the service deployment runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import radar_analyst.main as main_mod
from radar_analyst import embedded

_FAKE_DSN = "postgresql://fake@/fake?host=%2Ftmp"


class _FakeEmbedded:
    """Stand-in for the bundled server, recording its lifecycle."""

    instances: list[_FakeEmbedded] = []

    def __init__(
        self, data_dir: Path, bin_dir: Path | None = None
    ) -> None:
        self.data_dir = Path(data_dir)
        self.started = False
        self.stopped = False
        type(self).instances.append(self)

    @property
    def dsn(self) -> str:
        return _FAKE_DSN

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an unconfigured environment."""
    for name in (
        "RADAR_ANALYST_STATE_DB_URL",
        "RADAR_ANALYST_EMBEDDED_DB",
        "RADAR_ANALYST_DATA_DIR",
        "RADAR_ANALYST_BLOB_DIR",
        "RADAR_ANALYST_ADMIN_TOKEN",
        "RADAR_ANALYST_LISTEN",
    ):
        monkeypatch.delenv(name, raising=False)
    _FakeEmbedded.instances.clear()


@pytest.fixture
def fake_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> type[_FakeEmbedded]:
    monkeypatch.setattr(
        main_mod, "EmbeddedPostgres", _FakeEmbedded
    )
    return _FakeEmbedded


def _capture_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Replace uvicorn.run with a recorder and return what it saw."""
    seen: dict[str, Any] = {}

    def fake_run(app: str, **kw: Any) -> None:
        seen.update(kw)
        seen["state_db_url"] = os.environ.get(
            "RADAR_ANALYST_STATE_DB_URL"
        )

    monkeypatch.setattr("uvicorn.run", fake_run)
    return seen


# ---------------------------------------------------------------
# Starting and stopping the bundled server
# ---------------------------------------------------------------


def test_bundled_server_starts_and_hands_over_its_dsn(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedded: type[_FakeEmbedded],
    tmp_path: Path,
) -> None:
    """The service connects to the server the entrypoint started."""
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    seen = _capture_uvicorn(monkeypatch)

    main_mod.main()

    assert len(fake_embedded.instances) == 1
    server = fake_embedded.instances[0]
    assert server.started
    assert server.data_dir == tmp_path
    assert seen["state_db_url"] == _FAKE_DSN


def test_bundled_server_is_stopped_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedded: type[_FakeEmbedded],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    _capture_uvicorn(monkeypatch)

    main_mod.main()

    assert fake_embedded.instances[0].stopped


def test_bundled_server_is_stopped_when_serving_fails(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedded: type[_FakeEmbedded],
    tmp_path: Path,
) -> None:
    """A crash must not leave PostgreSQL running without its client."""
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))

    def boom(app: str, **kw: Any) -> None:
        raise RuntimeError("port already bound")

    monkeypatch.setattr("uvicorn.run", boom)

    with pytest.raises(RuntimeError):
        main_mod.main()

    assert fake_embedded.instances[0].stopped


def test_external_database_starts_no_server(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedded: type[_FakeEmbedded],
) -> None:
    """The service deployment keeps using the database it was given."""
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv(
        "RADAR_ANALYST_STATE_DB_URL", "postgresql://elsewhere/db"
    )
    seen = _capture_uvicorn(monkeypatch)

    main_mod.main()

    assert fake_embedded.instances == []
    assert seen["state_db_url"] == "postgresql://elsewhere/db"


def test_no_server_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
    fake_embedded: type[_FakeEmbedded],
) -> None:
    """A developer checkout keeps the old, explicit behaviour."""
    _capture_uvicorn(monkeypatch)

    main_mod.main()

    assert fake_embedded.instances == []


# ---------------------------------------------------------------
# Where the archives land
# ---------------------------------------------------------------


def test_archives_land_beside_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One volume holds both, so a copy of it is a whole backup."""
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "RADAR_ANALYST_STATE_DB_URL", "postgresql://elsewhere/db"
    )

    main_mod.build_production_app()

    assert (tmp_path / "archives").is_dir()


def test_explicit_blob_dir_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "RADAR_ANALYST_BLOB_DIR", str(tmp_path / "elsewhere")
    )
    monkeypatch.setenv(
        "RADAR_ANALYST_STATE_DB_URL", "postgresql://elsewhere/db"
    )

    main_mod.build_production_app()

    assert (tmp_path / "elsewhere").is_dir()
    assert not (tmp_path / "archives").exists()


# ---------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------


def test_bundled_deployment_generates_an_admin_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deleting an upload works out of the box, still authenticated.

    By the time the factory runs, the entrypoint has started the
    bundled server and published its DSN, so both variables are set.
    """
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _FAKE_DSN)

    app = main_mod.build_production_app()

    token_file = embedded.admin_token_path(tmp_path)
    assert token_file.is_file()
    assert app.state.admin_token == token_file.read_text().strip()


def test_configured_admin_token_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_EMBEDDED_DB", "1")
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _FAKE_DSN)
    monkeypatch.setenv("RADAR_ANALYST_ADMIN_TOKEN", "chosen")

    app = main_mod.build_production_app()

    assert app.state.admin_token == "chosen"
    assert not embedded.admin_token_path(tmp_path).exists()


def test_external_deployment_keeps_failing_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No token is invented for a deployment nobody configured.

    Outside the bundled image the analyst has no single owner of its
    data directory, so an unset token keeps meaning "deletes are
    refused" rather than "a token appeared in a file somewhere".
    """
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "RADAR_ANALYST_STATE_DB_URL", "postgresql://elsewhere/db"
    )

    app = main_mod.build_production_app()

    assert app.state.admin_token is None
    assert not embedded.admin_token_path(tmp_path).exists()
