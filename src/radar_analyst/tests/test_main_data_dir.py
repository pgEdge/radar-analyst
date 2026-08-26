"""What the entrypoint does with its data directory.

The analyst writes uploaded archives and its admin token under one
directory, whichever deployment it is running in. These tests pin
where that lands and that a delete stays authenticated without an
operator configuring a secret first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import radar_analyst.main as main_mod
from radar_analyst import layout


_DB_URL = "postgresql://elsewhere/radar_analyst"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an unconfigured environment."""
    for name in (
        "RADAR_ANALYST_STATE_DB_URL",
        "RADAR_ANALYST_DATA_DIR",
        "RADAR_ANALYST_BLOB_DIR",
        "RADAR_ANALYST_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------
# Where the archives land
# ---------------------------------------------------------------


def test_archives_land_under_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One directory is all a deployment has to keep."""
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _DB_URL)

    main_mod.build_production_app()

    assert (tmp_path / "archives").is_dir()


def test_explicit_blob_dir_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "RADAR_ANALYST_BLOB_DIR", str(tmp_path / "elsewhere")
    )
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _DB_URL)

    main_mod.build_production_app()

    assert (tmp_path / "elsewhere").is_dir()
    assert not (tmp_path / "archives").exists()


def test_a_database_url_is_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every deployment brings its own PostgreSQL."""
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="STATE_DB_URL"):
        main_mod.build_production_app()


# ---------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------


def test_an_admin_token_is_generated_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deleting an upload works out of the box, still authenticated."""
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _DB_URL)

    app = main_mod.build_production_app()

    token_file = layout.admin_token_path(tmp_path)
    assert token_file.is_file()
    assert app.state.admin_token == token_file.read_text().strip()


def test_configured_admin_token_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _DB_URL)
    monkeypatch.setenv("RADAR_ANALYST_ADMIN_TOKEN", "chosen")

    app = main_mod.build_production_app()

    assert app.state.admin_token == "chosen"
    assert not layout.admin_token_path(tmp_path).exists()


def test_deletes_fail_closed_when_the_token_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unwritable data directory must not leave deletes open."""
    data_dir = tmp_path / "locked"
    data_dir.mkdir()
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "RADAR_ANALYST_BLOB_DIR", str(tmp_path / "writable")
    )
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", _DB_URL)
    data_dir.chmod(0o500)
    try:
        app = main_mod.build_production_app()
    finally:
        data_dir.chmod(0o700)

    assert app.state.admin_token is None
