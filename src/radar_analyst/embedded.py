"""Bundled deployment: data layout and an embedded PostgreSQL server.

The distributed image carries its own PostgreSQL server, so running
the analyst takes one ``docker run`` and one volume. Everything the
analyst keeps lives under a single data directory: the server's
PGDATA in ``db/``, uploaded radar archives in ``archives/``, the
socket directory in ``run/``, and the admin token beside them. One
volume is therefore the whole of the analyst's state, and a copy of
it is a complete backup.

Setting ``RADAR_ANALYST_STATE_DB_URL`` turns the bundled server off:
the analyst then uses the database that URL names and starts nothing
of its own, which is how the service deployment runs.

The bundled server accepts connections only over a unix socket
inside the container. Publishing the analyst's HTTP port is a
deliberate act; the database behind it never gains one.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import signal
import subprocess
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import quote

_logger = logging.getLogger(__name__)

# Relative by default so a developer checkout keeps its state beside
# the source tree. The image sets RADAR_ANALYST_DATA_DIR=/data, which
# is where the volume is mounted.
DEFAULT_DATA_DIR = Path("data")

SUPERUSER = "radar_analyst"
DATABASE = "radar_analyst"

# Where Debian and Red Hat packages put the server binaries.
BIN_SEARCH_ROOTS: tuple[Path, ...] = (
    Path("/usr/lib/postgresql"),
    Path("/usr/pgsql"),
)

_STARTUP_TIMEOUT = 30.0
_SHUTDOWN_TIMEOUT = 30.0
_READY_POLL_INTERVAL = 0.2
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_VERSION_RE = re.compile(r"\(PostgreSQL\)\s+(\d+)")


class EmbeddedPostgresError(RuntimeError):
    """The bundled server cannot be located, started, or reused."""


# ---------------------------------------------------------------
# Data layout
# ---------------------------------------------------------------


def db_dir(data_dir: Path) -> Path:
    """PGDATA of the bundled server."""
    return Path(data_dir) / "db"


def archive_dir(data_dir: Path) -> Path:
    """Where uploaded radar archives are kept."""
    return Path(data_dir) / "archives"


def socket_dir(data_dir: Path) -> Path:
    """Directory holding the server's unix socket."""
    return Path(data_dir) / "run"


def admin_token_path(data_dir: Path) -> Path:
    """File holding the token that authorises deletes."""
    return Path(data_dir) / "admin-token"


def data_dir_from_env(env: Mapping[str, str]) -> Path:
    """The single directory holding everything the analyst keeps."""
    raw = env.get("RADAR_ANALYST_DATA_DIR") or ""
    return Path(raw) if raw else DEFAULT_DATA_DIR


def resolve_archive_dir(env: Mapping[str, str]) -> Path:
    """Where the blob store writes, honouring an explicit override."""
    explicit = env.get("RADAR_ANALYST_BLOB_DIR") or ""
    if explicit:
        return Path(explicit)
    return archive_dir(data_dir_from_env(env))


def is_bundled(env: Mapping[str, str]) -> bool:
    """Whether this process is the image's bundled deployment.

    True means the container owns its data directory, which is what
    lets the analyst generate its own admin token there.
    """
    value = (env.get("RADAR_ANALYST_EMBEDDED_DB") or "").strip()
    return value.lower() in _TRUE_VALUES


def use_embedded_db(env: Mapping[str, str]) -> bool:
    """Whether to start the bundled server.

    An explicit ``RADAR_ANALYST_STATE_DB_URL`` always wins, so the
    same image serves both the bundled deployment and one pointed at
    an existing PostgreSQL instance.
    """
    if env.get("RADAR_ANALYST_STATE_DB_URL"):
        return False
    return is_bundled(env)


# ---------------------------------------------------------------
# Version compatibility
# ---------------------------------------------------------------


def parse_server_major(text: str) -> int:
    """Read the major version out of ``postgres --version`` output."""
    match = _VERSION_RE.search(text)
    if match is None:
        raise ValueError(
            f"unrecognised PostgreSQL version output: {text!r}"
        )
    return int(match.group(1))


def pgdata_major(pgdata: Path) -> int | None:
    """Major version that wrote *pgdata*, or None if uninitialised."""
    version_file = Path(pgdata) / "PG_VERSION"
    try:
        raw = version_file.read_text().strip()
    except OSError:
        return None
    try:
        return int(raw.split(".")[0])
    except ValueError:
        raise EmbeddedPostgresError(
            f"{version_file} does not name a PostgreSQL major "
            f"version: {raw!r}"
        ) from None


def check_major(pgdata: int | None, server: int) -> None:
    """Refuse a data directory written by a different major version.

    On-disk format is bound to the major version, so an existing
    volume cannot be opened by a newer server without ``pg_upgrade``.
    PostgreSQL would fail here with a message about control-file
    versions; naming both versions instead makes the fix obvious.
    """
    if pgdata is None or pgdata == server:
        return
    raise EmbeddedPostgresError(
        f"the data directory was created by PostgreSQL {pgdata} "
        f"but this image ships PostgreSQL {server}. Run pg_upgrade "
        f"against the volume, or keep using the {pgdata} image."
    )


# ---------------------------------------------------------------
# Locating and invoking the server
# ---------------------------------------------------------------


def _installs_under(root: Path) -> list[tuple[int, Path]]:
    """Every ``(major, bin directory)`` installed under *root*."""
    try:
        entries = sorted(Path(root).iterdir())
    except OSError:
        return []
    found: list[tuple[int, Path]] = []
    for entry in entries:
        if not (entry / "bin" / "initdb").is_file():
            continue
        try:
            major = int(entry.name)
        except ValueError:
            continue
        found.append((major, entry / "bin"))
    return found


def find_bin_dir(roots: Iterable[Path]) -> Path:
    """Return the newest installed server's ``bin`` directory."""
    found: list[tuple[int, Path]] = []
    searched: list[str] = []
    for root in roots:
        searched.append(str(root))
        found.extend(_installs_under(root))
    if not found:
        raise EmbeddedPostgresError(
            "no PostgreSQL installation found under "
            + ", ".join(searched)
        )
    return max(found)[1]


def initdb_argv(*, bin_dir: Path, pgdata: Path) -> list[str]:
    """Command that creates the bundled server's data directory.

    Local connections are trusted because only this container's own
    processes can reach the socket; host connections are rejected
    outright, so a misconfigured ``listen_addresses`` still cannot
    turn into an open database.
    """
    return [
        str(Path(bin_dir) / "initdb"),
        f"--pgdata={pgdata}",
        f"--username={SUPERUSER}",
        "--auth-local=trust",
        "--auth-host=reject",
        "--encoding=UTF8",
        "--locale=C.UTF-8",
    ]


def server_argv(
    *, bin_dir: Path, pgdata: Path, socket_dir: Path
) -> list[str]:
    """Command that runs the bundled server in the foreground.

    An empty ``listen_addresses`` means no TCP port at all, and
    ``unix_socket_permissions=0700`` keeps any other uid in the
    container off the socket.

    ``jit=off`` because this database holds upload metadata,
    findings, and briefs, which are read by small indexed queries
    that JIT compilation can only slow down. The image leaves out the
    LLVM libraries the JIT provider needs, and a setting given on the
    command line outranks ``postgresql.auto.conf``, so it cannot be
    turned back on against a server that could not honour it.
    """
    return [
        str(Path(bin_dir) / "postgres"),
        "-D",
        str(pgdata),
        "-k",
        str(socket_dir),
        "-c",
        "listen_addresses=",
        "-c",
        "unix_socket_permissions=0700",
        "-c",
        "jit=off",
    ]


def socket_dsn(sock_dir: Path) -> str:
    """Connection string for the bundled server's unix socket."""
    host = quote(str(Path(sock_dir).absolute()), safe="")
    return f"postgresql://{SUPERUSER}@/{DATABASE}?host={host}"


def is_already_exists(stderr: str) -> bool:
    """Whether a ``createdb`` failure just means "it is already there"."""
    return "already exists" in stderr


# ---------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------


def ensure_admin_token(path: Path) -> str:
    """Return the persisted admin token, generating one on first use.

    Deletes stay authenticated: without this the analyst would ship
    with either a fixed token, which is no protection at all, or no
    token, which leaves the delete button permanently broken. The
    token is per-install and survives restarts because it lives in
    the data directory.
    """
    path = Path(path)
    try:
        existing = path.read_text().strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    token = secrets.token_hex(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened 0600: a token that is briefly world-readable has leaked.
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(fd, "w") as handle:
        handle.write(token + "\n")
    path.chmod(0o600)
    return token


# ---------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------


class EmbeddedPostgres:
    """The PostgreSQL server bundled inside the image."""

    def __init__(
        self, data_dir: Path, bin_dir: Path | None = None
    ) -> None:
        self._data_dir = Path(data_dir)
        self._bin_dir = (
            Path(bin_dir)
            if bin_dir is not None
            else find_bin_dir(BIN_SEARCH_ROOTS)
        )
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def dsn(self) -> str:
        """Connection string the rest of the service should use."""
        return socket_dsn(socket_dir(self._data_dir))

    def start(self, timeout: float = _STARTUP_TIMEOUT) -> None:
        """Initialise on first run, then start and wait for readiness."""
        pgdata = db_dir(self._data_dir)
        sock = socket_dir(self._data_dir)
        sock.mkdir(parents=True, exist_ok=True)
        sock.chmod(0o700)
        server = self._server_major()
        check_major(pgdata_major(pgdata), server)
        if pgdata_major(pgdata) is None:
            self._initdb(pgdata)
        _logger.info(
            "starting bundled PostgreSQL %d on %s", server, sock
        )
        self._proc = subprocess.Popen(
            server_argv(
                bin_dir=self._bin_dir,
                pgdata=pgdata,
                socket_dir=sock,
            )
        )
        self._wait_ready(sock, timeout)
        self._ensure_database(sock)

    def stop(self, timeout: float = _SHUTDOWN_TIMEOUT) -> None:
        """Shut the server down cleanly, escalating if it will not go."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        # SIGINT is PostgreSQL's fast shutdown: roll back open
        # transactions, checkpoint, exit. SIGQUIT skips the
        # checkpoint and forces recovery on the next start, so it is
        # the fallback rather than the first move.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            _logger.warning(
                "bundled PostgreSQL did not stop in %.0fs; "
                "forcing shutdown",
                timeout,
            )
        proc.send_signal(signal.SIGQUIT)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _server_major(self) -> int:
        result = self._run(
            [str(self._bin_dir / "postgres"), "--version"]
        )
        return parse_server_major(result.stdout)

    def _initdb(self, pgdata: Path) -> None:
        _logger.info("creating data directory %s", pgdata)
        pgdata.parent.mkdir(parents=True, exist_ok=True)
        result = self._run(
            initdb_argv(bin_dir=self._bin_dir, pgdata=pgdata)
        )
        if result.returncode != 0:
            raise EmbeddedPostgresError(
                f"initdb failed: {result.stderr.strip()}"
            )

    def _wait_ready(self, sock: Path, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        probe = [
            str(self._bin_dir / "pg_isready"),
            "-q",
            "-h",
            str(sock),
            "-U",
            SUPERUSER,
        ]
        while time.monotonic() < deadline:
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                raise EmbeddedPostgresError(
                    "bundled PostgreSQL exited during startup "
                    f"with code {proc.returncode}"
                )
            if self._run(probe).returncode == 0:
                return
            time.sleep(_READY_POLL_INTERVAL)
        raise EmbeddedPostgresError(
            f"bundled PostgreSQL was not ready within {timeout:.0f}s"
        )

    def _ensure_database(self, sock: Path) -> None:
        result = self._run(
            [
                str(self._bin_dir / "createdb"),
                "-h",
                str(sock),
                "-U",
                SUPERUSER,
                DATABASE,
            ]
        )
        if result.returncode == 0 or is_already_exists(result.stderr):
            return
        raise EmbeddedPostgresError(
            f"could not create database {DATABASE}: "
            f"{result.stderr.strip()}"
        )

    @staticmethod
    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv, capture_output=True, text=True, check=False
        )
