"""The state database must be reachable only by the analyst.

Not publishing the database's port is not enough. A container's
bridge address is routable from the host it runs on, so a server
listening on all interfaces is reachable by every local process
whether or not compose maps a port. The analyst therefore reaches
PostgreSQL over a unix socket in a volume the two containers share,
and the server keeps the image's default of listening on its own
loopback only.

These are text checks against the compose files, which is enough to
catch the two edits that would undo it. ``test-radar-analyst.sh``
proves the property itself against a running stack.
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


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_database_does_not_listen_on_every_interface(
    name: str,
) -> None:
    text = _read(name)
    assert "listen_addresses=*" not in text, (
        f"{name} opens the database to every interface, which puts "
        "it within reach of any process on the host"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_database_port_is_not_published(name: str) -> None:
    published = [
        line
        for line in text_lines(_read(name))
        if line.lstrip().startswith("-") and ":5432" in line
    ]
    assert not published, (
        f"{name} publishes the database port: {published}"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_analyst_connects_over_the_shared_socket(
    name: str,
) -> None:
    text = _read(name)
    assert "host=/run/postgresql" in text, (
        f"{name} does not point the analyst at the unix socket"
    )
    assert text.count("sock:/run/postgresql") == 2, (
        f"{name} must mount the socket volume in both services"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_database_checks_the_password(name: str) -> None:
    """The image trusts its socket and loopback unless told otherwise."""
    text = _read(name)
    for flag in ("--auth-local=scram-sha-256", "--auth-host=scram-sha-256"):
        assert flag in text, (
            f"{name} lets a connection in without the password"
        )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_password_stays_out_of_the_connection_url(name: str) -> None:
    """Compose cannot percent-encode, so @, / or % would break a URL."""
    text = _read(name)
    assert "postgresql://radar_analyst@/radar_analyst" in text, (
        f"{name} puts the database password in the connection URL"
    )
    assert "PGPASSWORD:" in text, (
        f"{name} does not hand the password to libpq"
    )


@pytest.mark.parametrize("name", _COMPOSE_FILES)
def test_the_console_is_published_on_loopback_only(
    name: str,
) -> None:
    """The analyst is a local tool; only 8080 is exposed, on 127.0.0.1."""
    published = [
        line.strip()
        for line in text_lines(_read(name))
        if line.lstrip().startswith("-") and ":8080" in line
    ]
    assert published, f"{name} publishes nothing"
    for line in published:
        assert "127.0.0.1:" in line, (
            f"{name} exposes the console beyond loopback: {line}"
        )


def text_lines(text: str) -> list[str]:
    """Return *text* split into lines, comments removed."""
    return [
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    ]
