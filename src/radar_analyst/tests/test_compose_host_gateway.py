"""The default Ollama address must resolve inside the container.

``host.docker.internal`` is Docker Desktop's name for the machine
running Docker, and the compose file's default Ollama address uses
it. Docker Engine on Linux does not define the name, so the compose
file has to map it to the host gateway itself, or the ``local``
provider fails there with its default settings.

This is a text check against the compose file, in the same spirit as
the exposure and logging checks beside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

pytestmark = pytest.mark.skipif(
    not _COMPOSE.is_file(),
    reason="compose files are only present in a source checkout",
)


def test_the_analyst_can_resolve_the_docker_host() -> None:
    text = _COMPOSE.read_text()
    assert "host.docker.internal:host-gateway" in text, (
        "docker-compose.yml does not map host.docker.internal, so "
        "the default Ollama address fails on Docker Engine for Linux"
    )
