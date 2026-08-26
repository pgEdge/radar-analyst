"""Where the analyst keeps what it is given.

Everything the analyst writes lives under one data directory: the
uploaded radar archives in ``archives/``, and the token that
authorises deletes beside them. Mount a volume there, or point a
package's unit file at it, and that directory is the whole of what
has to survive a restart.

The database is deliberately not part of it. Every deployment brings
its own PostgreSQL, named by ``RADAR_ANALYST_STATE_DB_URL``: a
service alongside the analyst under compose, the system server for a
package install. The analyst creates its ``radar`` schema in
whatever it is pointed at and holds nothing else there.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from pathlib import Path


# Relative by default so a developer checkout keeps its state beside
# the source tree. The container image sets
# RADAR_ANALYST_DATA_DIR=/data, which is where its volume is mounted.
DEFAULT_DATA_DIR = Path("data")

# 24 bytes of urandom, hex encoded. Long enough that guessing is not
# a threat, short enough to paste into the console's prompt.
_TOKEN_BYTES = 24


def archive_dir(data_dir: Path) -> Path:
    """Return where uploaded radar archives are kept."""
    return Path(data_dir) / "archives"


def admin_token_path(data_dir: Path) -> Path:
    """Return the file holding the token that authorises deletes."""
    return Path(data_dir) / "admin-token"


def data_dir_from_env(env: Mapping[str, str]) -> Path:
    """Return the directory holding everything the analyst writes."""
    raw = env.get("RADAR_ANALYST_DATA_DIR") or ""
    return Path(raw) if raw else DEFAULT_DATA_DIR


def resolve_archive_dir(env: Mapping[str, str]) -> Path:
    """Return where the blob store writes.

    An explicit ``RADAR_ANALYST_BLOB_DIR`` wins, so an operator can
    put archives on separate storage without moving anything else.
    """
    explicit = env.get("RADAR_ANALYST_BLOB_DIR") or ""
    if explicit:
        return Path(explicit)
    return archive_dir(data_dir_from_env(env))


def ensure_admin_token(path: Path) -> str:
    """Return the persisted admin token, generating one on first use.

    Deletes stay authenticated without anyone configuring a shared
    secret first. The alternative is shipping a fixed token, which is
    no protection at all, or shipping none, which leaves the delete
    button permanently answering 503. The token is per-install and
    survives restarts because it lives in the data directory.

    Raises ``OSError`` if the data directory cannot be written.
    """
    path = Path(path)
    try:
        existing = path.read_text().strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    token = secrets.token_hex(_TOKEN_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened 0600: a token that is briefly world-readable has leaked.
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(fd, "w") as handle:
        handle.write(token + "\n")
    path.chmod(0o600)
    return token
