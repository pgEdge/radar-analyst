"""Dependabot opens pull requests for security advisories only.

Each ecosystem gets one group that gathers its security updates into a
single pull request, and a limit of zero that keeps version updates
from opening any. These are text checks against the configuration, as
for the compose files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_CONFIG = Path(__file__).resolve().parents[3] / ".github" / "dependabot.yml"

pytestmark = pytest.mark.skipif(
    not _CONFIG.is_file(),
    reason="the Dependabot configuration is only present in a checkout",
)


def test_only_security_advisories_open_pull_requests() -> None:
    entries = re.split(
        r"\n(?=  - package-ecosystem:)", _CONFIG.read_text()
    )[1:]
    assert entries, "no ecosystems are configured"
    for entry in entries:
        name = entry.split('"')[1]
        assert "open-pull-requests-limit: 0" in entry, (
            f"{name} opens version-update pull requests"
        )
        assert "applies-to: security-updates" in entry, (
            f"{name} does not group its security updates"
        )
