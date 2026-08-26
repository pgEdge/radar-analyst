"""Where the analyst writes, and the token that guards deletes.

One data directory holds everything the analyst produces, so these
tests pin what lands there and that a delete stays authenticated
without anyone configuring a secret first.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from radar_analyst import layout


# ---------------------------------------------------------------
# Data layout
# ---------------------------------------------------------------


def test_archives_live_under_the_data_dir() -> None:
    root = Path("/data")
    assert layout.archive_dir(root) == root / "archives"
    assert layout.admin_token_path(root) == root / "admin-token"


def test_data_dir_defaults_beside_the_source_tree() -> None:
    """A developer checkout must not reach for a system path.

    The container image sets ``RADAR_ANALYST_DATA_DIR=/data``, which
    is where its volume is mounted.
    """
    assert layout.data_dir_from_env({}) == Path("data")
    assert Path("data") == layout.DEFAULT_DATA_DIR


def test_data_dir_is_overridable() -> None:
    assert layout.data_dir_from_env(
        {"RADAR_ANALYST_DATA_DIR": "/srv/analyst"}
    ) == Path("/srv/analyst")


def test_archive_dir_follows_the_data_dir() -> None:
    assert layout.resolve_archive_dir(
        {"RADAR_ANALYST_DATA_DIR": "/srv/analyst"}
    ) == Path("/srv/analyst/archives")


def test_explicit_blob_dir_wins_over_the_data_dir() -> None:
    """An operator can put archives on separate storage."""
    assert layout.resolve_archive_dir(
        {
            "RADAR_ANALYST_DATA_DIR": "/srv/analyst",
            "RADAR_ANALYST_BLOB_DIR": "/mnt/big/archives",
        }
    ) == Path("/mnt/big/archives")


# ---------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------


def test_admin_token_is_generated_on_first_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / "admin-token"
    token = layout.ensure_admin_token(path)
    assert len(token) >= 32
    assert path.read_text().strip() == token


def test_admin_token_is_stable_across_restarts(
    tmp_path: Path,
) -> None:
    """A token that changed each start would be useless in the UI."""
    path = tmp_path / "admin-token"
    first = layout.ensure_admin_token(path)
    assert layout.ensure_admin_token(path) == first


def test_admin_token_file_is_not_world_readable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "admin-token"
    layout.ensure_admin_token(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_admin_token_tolerates_trailing_whitespace(
    tmp_path: Path,
) -> None:
    """A token edited by hand still authenticates."""
    path = tmp_path / "admin-token"
    path.write_text("  chosen-by-hand \n")
    assert layout.ensure_admin_token(path) == "chosen-by-hand"


def test_admin_tokens_differ_between_installs(
    tmp_path: Path,
) -> None:
    """No fixed default: two installs never share a token."""
    first = layout.ensure_admin_token(tmp_path / "a")
    second = layout.ensure_admin_token(tmp_path / "b")
    assert first != second


def test_admin_token_reports_an_unwritable_data_dir(
    tmp_path: Path,
) -> None:
    """The caller decides what to do, rather than getting a crash."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(OSError):
            layout.ensure_admin_token(locked / "admin-token")
    finally:
        locked.chmod(0o700)
