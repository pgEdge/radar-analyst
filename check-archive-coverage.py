#!/usr/bin/env python3
"""Report radar archive paths the analyst does not classify.

The classifier in ``archive/reader.py`` is a hand-maintained mirror
of radar's collection tasks, and radar is the source of truth. A
path radar adds is unknown here until somebody lists it, and the
only symptom is a valid archive reporting unrecognised files.

Needs a radar checkout, so it cannot run in CI. Run it whenever
radar may have moved: at the start of a harvest, before adding
parser or rule support for an archive entry, and after pulling
radar.

    ./check-archive-coverage.py [path-to-radar]

Exits 0 when every radar path classifies, 1 when any does not, and
2 when radar cannot be read.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


_READER = Path(__file__).parent / "src/radar_analyst/archive/reader.py"
_PATH_RE = re.compile(
    r'"((?:postgresql|databases|pg_statviz|spock|pgbouncer|system)'
    r'/[^"]*)"'
)
# Parent directory of a per-database tree -> reader stem set.
_TREES = {
    "databases": "_DB_STEMS",
    "pg_statviz": "_STATVIZ_STEMS",
    "spock": "_SPOCK_STEMS",
}


def radar_paths(radar: Path) -> set[str]:
    """Archive paths radar's production sources can write."""
    out: set[str] = set()
    for go in sorted(radar.glob("*.go")):
        if go.name.endswith("_test.go"):
            continue
        out |= set(_PATH_RE.findall(go.read_text()))
    return out


def _stems(src: str, name: str) -> set[str]:
    m = re.search(
        name + r":\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)",
        src,
        re.S,
    )
    return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()


def reader_knowledge() -> tuple[set[str], dict[str, set[str]]]:
    """The classifier's fixed paths, and its per-tree stem sets."""
    src = _READER.read_text()
    fixed = {
        a or b
        for a, b in re.findall(
            r'^\s*"([^"]+)":\s*$|^\s*"([^"]+)":\s*"', src, re.M
        )
    }
    # Package-manager dumps are registered in a loop, not literally.
    for pkg in re.findall(r'^\s+"(packages[^"]+)",', src, re.M):
        fixed.add(f"system/{pkg}.out")
    return fixed, {p: _stems(src, n) for p, n in _TREES.items()}


def unclassified(paths: set[str]) -> list[str]:
    """Radar paths the classifier would return None for."""
    fixed, trees = reader_knowledge()
    missing: list[str] = []
    for path in sorted(paths):
        if "%s" in path:
            parent = path.split("/", 1)[0]
            stem = path.rsplit("/", 1)[1].rsplit(".", 1)[0]
            if parent in trees and stem not in trees[parent]:
                missing.append(path)
        elif path not in fixed:
            missing.append(path)
    return missing


def main(argv: list[str]) -> int:
    """Compare radar's paths against the classifier."""
    radar = Path(argv[1] if len(argv) > 1 else "../radar").resolve()
    if not radar.is_dir() or not list(radar.glob("*.go")):
        print(f"no radar checkout at {radar}", file=sys.stderr)
        return 2
    paths = radar_paths(radar)
    if not paths:
        print(f"no archive paths found in {radar}", file=sys.stderr)
        return 2
    missing = unclassified(paths)
    print(f"radar {radar}: {len(paths)} archive paths")
    if not missing:
        print("all classified")
        return 0
    print(f"\n{len(missing)} NOT classified by archive/reader.py:")
    for path in missing:
        print(f"  {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
