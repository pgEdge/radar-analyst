"""The bundled deployment: data layout and embedded PostgreSQL.

The distributed image carries its own PostgreSQL server so that one
``docker run`` and one volume are enough. These tests pin the parts
that decide where data lands, whether the bundled server is used at
all, and that it never listens on a network socket.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from radar_analyst import embedded


# ---------------------------------------------------------------
# Data layout: one directory holds everything the analyst keeps
# ---------------------------------------------------------------


def test_layout_places_db_and_archives_under_one_dir() -> None:
    """One volume covers both, so a backup cannot be half a copy."""
    root = Path("/data")
    assert embedded.db_dir(root) == root / "db"
    assert embedded.archive_dir(root) == root / "archives"
    assert embedded.socket_dir(root) == root / "run"
    assert embedded.admin_token_path(root) == root / "admin-token"


def test_data_dir_defaults_beside_the_source_tree() -> None:
    """A developer checkout must not reach for a system path.

    The image sets ``RADAR_ANALYST_DATA_DIR=/data``, which is where
    the volume is mounted.
    """
    assert embedded.data_dir_from_env({}) == Path("data")
    assert embedded.DEFAULT_DATA_DIR == Path("data")


def test_data_dir_is_overridable() -> None:
    assert embedded.data_dir_from_env(
        {"RADAR_ANALYST_DATA_DIR": "/srv/analyst"}
    ) == Path("/srv/analyst")


def test_archive_dir_follows_the_data_dir() -> None:
    """Archives live beside the database unless told otherwise."""
    assert embedded.resolve_archive_dir(
        {"RADAR_ANALYST_DATA_DIR": "/srv/analyst"}
    ) == Path("/srv/analyst/archives")


def test_explicit_blob_dir_wins_over_the_data_dir() -> None:
    """An operator pointing the store elsewhere keeps that path."""
    assert embedded.resolve_archive_dir(
        {
            "RADAR_ANALYST_DATA_DIR": "/srv/analyst",
            "RADAR_ANALYST_BLOB_DIR": "/mnt/big/blobs",
        }
    ) == Path("/mnt/big/blobs")


# ---------------------------------------------------------------
# Choosing between the bundled server and an external database
# ---------------------------------------------------------------


def test_state_db_url_wins_over_the_bundled_server() -> None:
    """Naming a database is how the service deployment opts out."""
    assert not embedded.use_embedded_db(
        {
            "RADAR_ANALYST_STATE_DB_URL": "postgresql://host/db",
            "RADAR_ANALYST_EMBEDDED_DB": "1",
        }
    )


def test_the_image_stays_bundled_with_an_external_database() -> None:
    """Pointing the image at a database does not disown its volume.

    The container still owns the data directory, which is what lets
    it keep its own admin token there.
    """
    env = {
        "RADAR_ANALYST_STATE_DB_URL": "postgresql://host/db",
        "RADAR_ANALYST_EMBEDDED_DB": "1",
    }
    assert embedded.is_bundled(env)
    assert not embedded.use_embedded_db(env)


def test_a_checkout_is_not_bundled() -> None:
    assert not embedded.is_bundled({})


def test_bundled_server_runs_when_enabled_with_no_url() -> None:
    assert embedded.use_embedded_db(
        {"RADAR_ANALYST_EMBEDDED_DB": "1"}
    )


def test_bundled_server_is_off_by_default() -> None:
    """A developer checkout must not try to run a server."""
    assert not embedded.use_embedded_db({})


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_flag_values_enable_the_bundled_server(
    value: str,
) -> None:
    assert embedded.use_embedded_db(
        {"RADAR_ANALYST_EMBEDDED_DB": value}
    )


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_falsy_flag_values_leave_it_off(value: str) -> None:
    assert not embedded.use_embedded_db(
        {"RADAR_ANALYST_EMBEDDED_DB": value}
    )


# ---------------------------------------------------------------
# Version compatibility: PGDATA is bound to one major
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,major",
    [
        ("postgres (PostgreSQL) 17.11 (Debian 17.11-0+deb13u1)", 17),
        ("initdb (PostgreSQL) 17.11 (Debian 17.11-0+deb13u1)", 17),
        ("postgres (PostgreSQL) 18.0\n", 18),
    ],
)
def test_parse_server_major(text: str, major: int) -> None:
    assert embedded.parse_server_major(text) == major


def test_parse_server_major_rejects_unrecognised_output() -> None:
    with pytest.raises(ValueError):
        embedded.parse_server_major("no version here")


def test_pgdata_major_reads_pg_version(tmp_path: Path) -> None:
    (tmp_path / "PG_VERSION").write_text("17\n")
    assert embedded.pgdata_major(tmp_path) == 17


def test_pgdata_major_is_none_for_an_uninitialised_dir(
    tmp_path: Path,
) -> None:
    assert embedded.pgdata_major(tmp_path) is None
    assert embedded.pgdata_major(tmp_path / "absent") is None


def test_major_mismatch_refuses_to_start(tmp_path: Path) -> None:
    """A volume from an older image needs pg_upgrade, not a crash.

    Starting the wrong major against an existing PGDATA fails deep
    inside PostgreSQL with a message about control files. Refusing
    up front names both versions and the directory instead.
    """
    with pytest.raises(embedded.EmbeddedPostgresError) as excinfo:
        embedded.check_major(pgdata=16, server=17)
    message = str(excinfo.value)
    assert "16" in message and "17" in message


def test_matching_major_is_accepted() -> None:
    embedded.check_major(pgdata=17, server=17)


def test_uninitialised_pgdata_accepts_any_server() -> None:
    """Nothing to be incompatible with before the first initdb."""
    embedded.check_major(pgdata=None, server=17)


# ---------------------------------------------------------------
# Locating the server binaries
# ---------------------------------------------------------------


def _fake_install(root: Path, major: str) -> Path:
    """Create a directory tree that looks like a PostgreSQL install."""
    bin_dir = root / major / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("initdb", "pg_ctl", "postgres", "pg_isready"):
        (bin_dir / name).touch()
    return bin_dir


def test_find_bin_dir_locates_an_install(tmp_path: Path) -> None:
    expected = _fake_install(tmp_path, "17")
    assert embedded.find_bin_dir([tmp_path]) == expected


def test_find_bin_dir_prefers_the_newest_major(
    tmp_path: Path,
) -> None:
    _fake_install(tmp_path, "16")
    newest = _fake_install(tmp_path, "17")
    _fake_install(tmp_path, "9")
    assert embedded.find_bin_dir([tmp_path]) == newest


def test_find_bin_dir_ignores_an_incomplete_install(
    tmp_path: Path,
) -> None:
    """A directory without initdb is not an install."""
    (tmp_path / "17" / "bin").mkdir(parents=True)
    complete = _fake_install(tmp_path, "16")
    assert embedded.find_bin_dir([tmp_path]) == complete


def test_find_bin_dir_raises_when_nothing_is_installed(
    tmp_path: Path,
) -> None:
    with pytest.raises(embedded.EmbeddedPostgresError):
        embedded.find_bin_dir([tmp_path])


# ---------------------------------------------------------------
# The server must never be reachable over the network
# ---------------------------------------------------------------


def test_server_argv_disables_tcp(tmp_path: Path) -> None:
    """The bundled server is reachable only from its own container.

    Publishing the analyst's port is the deliberate act; the
    database behind it must never gain one.
    """
    argv = embedded.server_argv(
        bin_dir=tmp_path / "bin",
        pgdata=tmp_path / "db",
        socket_dir=tmp_path / "run",
    )
    assert "listen_addresses=" in argv
    assert not [
        a
        for a in argv
        if a.startswith("listen_addresses=") and a != "listen_addresses="
    ]


def test_server_argv_disables_the_jit(tmp_path: Path) -> None:
    """The analyst's own queries are small; JIT only adds latency.

    The image drops the LLVM libraries the JIT would need, so this
    setting is also what keeps that removal safe. Passing it on the
    command line means ALTER SYSTEM cannot turn it back on.
    """
    argv = embedded.server_argv(
        bin_dir=tmp_path / "bin",
        pgdata=tmp_path / "db",
        socket_dir=tmp_path / "run",
    )
    assert "jit=off" in argv


def test_server_argv_restricts_the_socket(tmp_path: Path) -> None:
    """0700 keeps any other uid in the container off the socket."""
    argv = embedded.server_argv(
        bin_dir=tmp_path / "bin",
        pgdata=tmp_path / "db",
        socket_dir=tmp_path / "run",
    )
    assert "unix_socket_permissions=0700" in argv
    assert str(tmp_path / "run") in argv


def test_initdb_argv_rejects_host_connections(
    tmp_path: Path,
) -> None:
    """A second, independent check: no host auth is configured.

    Even if ``listen_addresses`` were ever set, there would be no
    rule in pg_hba.conf under which a TCP client could authenticate.
    """
    argv = embedded.initdb_argv(
        bin_dir=tmp_path / "bin", pgdata=tmp_path / "db"
    )
    assert "--auth-host=reject" in argv
    assert "--auth-local=trust" in argv
    assert f"--username={embedded.SUPERUSER}" in argv


# ---------------------------------------------------------------
# The connection string handed to the rest of the service
# ---------------------------------------------------------------


def test_socket_dsn_points_at_the_socket_directory(
    tmp_path: Path,
) -> None:
    from psycopg.conninfo import conninfo_to_dict

    dsn = embedded.socket_dsn(tmp_path / "run")
    parsed = conninfo_to_dict(dsn)
    assert parsed["host"] == str(tmp_path / "run")
    assert parsed["user"] == embedded.SUPERUSER
    assert parsed["dbname"] == embedded.DATABASE


def test_socket_dsn_has_no_tcp_host(tmp_path: Path) -> None:
    dsn = embedded.socket_dsn(tmp_path / "run")
    assert "localhost" not in dsn and "127.0.0.1" not in dsn


def test_already_exists_error_is_recognised() -> None:
    """A second start must not fail on the database it created."""
    stderr = (
        'createdb: error: database creation failed: ERROR:  '
        'database "radar_analyst" already exists'
    )
    assert embedded.is_already_exists(stderr)


def test_other_createdb_errors_are_not_swallowed() -> None:
    assert not embedded.is_already_exists(
        "createdb: error: connection to server failed"
    )


# ---------------------------------------------------------------
# Admin token: deletes work out of the box without a shared secret
# ---------------------------------------------------------------


def test_admin_token_is_generated_on_first_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / "admin-token"
    token = embedded.ensure_admin_token(path)
    assert len(token) >= 32
    assert path.read_text().strip() == token


def test_admin_token_is_stable_across_restarts(
    tmp_path: Path,
) -> None:
    """A token that changed each start would be useless in the UI."""
    path = tmp_path / "admin-token"
    first = embedded.ensure_admin_token(path)
    assert embedded.ensure_admin_token(path) == first


def test_admin_token_file_is_not_world_readable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "admin-token"
    embedded.ensure_admin_token(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_admin_token_tolerates_trailing_whitespace(
    tmp_path: Path,
) -> None:
    """A token edited by hand still authenticates."""
    path = tmp_path / "admin-token"
    path.write_text("  chosen-by-hand \n")
    assert embedded.ensure_admin_token(path) == "chosen-by-hand"


def test_admin_tokens_differ_between_installs(
    tmp_path: Path,
) -> None:
    """No fixed default: two installs never share a token."""
    a = embedded.ensure_admin_token(tmp_path / "a")
    b = embedded.ensure_admin_token(tmp_path / "b")
    assert a != b
