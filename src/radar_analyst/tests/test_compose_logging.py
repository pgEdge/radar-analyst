"""Logs must not be able to fill the disk.

Two paths can grow without limit in a container deployment and both
are quiet until the volume is full.

The database image runs PostgreSQL's own logging collector, writing
into `log/` inside PGDATA. Its defaults bound the file *count*, one
per weekday truncated on reuse, but `log_rotation_size` is 0, so a
single day of heavy logging grows one file until there is no room
left. It also hides everything from `docker compose logs db`.

Docker's json-file driver has no size limit unless one is set, so
the analyst's own stdout accumulates on the host indefinitely.

The fix for both is the same: send the database's log to stdout like
every other container, and cap the driver.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.test.yml")

pytestmark = pytest.mark.skipif(
    not (_REPO_ROOT / "docker-compose.yml").is_file(),
    reason="compose files are only present in a source checkout",
)


def _read(name: str) -> str:
    return (_REPO_ROOT / name).read_text()


def _uncommented(text: str) -> str:
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


def _services_block(text: str) -> str:
    """Return just the services, without the volumes that share names."""
    body = _uncommented(text)
    start = body.index("\nservices:")
    end = body.index("\nvolumes:", start)
    return body[start:end]


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_database_logs_to_stdout(name: str) -> None:
    """Nothing accumulates inside the data volume, and logs are visible.

    With the collector on, `docker compose logs db` shows one line
    saying the real log went somewhere else.
    """
    text = _uncommented(_read(name))
    assert "logging_collector=off" in text, (
        f"{name} lets the database write logs into its own volume, "
        "where nothing rotates them by size"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_every_service_caps_its_log_driver(name: str) -> None:
    """Docker's default json-file driver keeps everything forever."""
    text = _services_block(_read(name))
    services = text.count("\n  db:") + text.count("\n  app:")
    assert services == 2, f"{name} does not define both services"
    assert text.count("max-size:") == services, (
        f"{name} does not cap max-size on every service"
    )
    assert text.count("max-file:") == services, (
        f"{name} does not cap max-file on every service"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_cap_is_a_real_bound(name: str) -> None:
    """A cap of "0" or an unparseable size is not a cap."""
    import re

    text = _services_block(_read(name))
    sizes = re.findall(r'max-size:\s*"?([0-9]+)([kmg])"?', text)
    assert sizes, f"{name} has no parseable max-size"
    for value, _unit in sizes:
        assert int(value) > 0, f"{name} sets max-size to zero"
    files = re.findall(r'max-file:\s*"?([0-9]+)"?', text)
    assert files, f"{name} has no parseable max-file"
    for value in files:
        assert int(value) >= 1, f"{name} sets max-file below one"
