"""A build from the checkout never takes the published image's name.

Compose runs any local image that has the name a service asks for,
and pulls only when there is none. A build tagged with the published
name would therefore stand in for the published image on every later
run without the build overlay, until the next pull.

These are text checks against the compose files, as in
``test_compose_exposure.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    not (_REPO_ROOT / "docker-compose.build.yml").is_file(),
    reason="compose files are only present in a source checkout",
)


def _images(name: str) -> list[str]:
    text = (_REPO_ROOT / name).read_text()
    return re.findall(r"^\s+image:\s*(\S+)", text, re.MULTILINE)


def test_the_build_overlay_names_its_own_image() -> None:
    built = _images("docker-compose.build.yml")
    assert len(built) == 1, "the overlay must name the image it builds"
    assert built[0] not in _images("docker-compose.yml")
