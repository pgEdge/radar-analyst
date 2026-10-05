"""Every make target runs, whatever files sit beside the Makefile.

make skips a target that is not declared phony as up to date when a
file of its name exists, so each target is run, as a dry run, with
such a file present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


_MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"

pytestmark = pytest.mark.skipif(
    not _MAKEFILE.is_file() or shutil.which("make") is None,
    reason="needs a source checkout and make",
)


def _targets() -> list[str]:
    if not _MAKEFILE.is_file():
        return []
    return re.findall(
        r"^([a-z][a-z0-9-]*):", _MAKEFILE.read_text(), re.MULTILINE
    )


@pytest.mark.parametrize("target", _targets())
def test_a_file_named_after_the_target_does_not_stop_it(
    target: str, tmp_path: Path
) -> None:
    (tmp_path / target).touch()
    proc = subprocess.run(
        ["make", "--dry-run", "--file", str(_MAKEFILE), target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "is up to date" not in proc.stdout + proc.stderr
