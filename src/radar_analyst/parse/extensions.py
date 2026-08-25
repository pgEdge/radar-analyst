"""Parse ``postgresql/available_extensions.tsv``.

Source view: ``pg_available_extension_versions``. Radar dumps every
available version of every extension along with an ``installed``
boolean marking the row that matches what the cluster currently
runs. We collapse those rows into ``ExtensionVersionInfo`` entries
keyed by extension name, so a rule can flag the ones whose
installed version is older than the highest available.

Version comparison: strip alphabetic characters, replace ``-``
with ``.``, split on ``.``, compare as a tuple of ints. That is
intentionally tolerant of pre-release-style suffixes
(``1.0.1-beta`` becomes ``(1, 0, 1)``) and matches what an
operator sees in ``pg_extension.extversion``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radar_analyst.parse.tsv import parse_tsv_bytes

_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"name", "version", "installed"}
)
_LETTER_RE = re.compile(r"[a-zA-Z]")


def _ver_tuple(version: str) -> tuple[int, ...]:
    cleaned = _LETTER_RE.sub("", version).replace("-", ".")
    out: list[int] = []
    for piece in cleaned.split("."):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            continue
    return tuple(out)


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"t", "true", "yes", "1"}


@dataclass(frozen=True)
class ExtensionVersionInfo:
    """Installed vs default version for one extension."""
    name: str
    installed: str
    latest: str

    @property
    def is_outdated(self) -> bool:
        """Whether the installed version trails the default."""
        return _ver_tuple(self.latest) > _ver_tuple(self.installed)


@dataclass(frozen=True)
class AvailableExtensions:
    """All extensions, with an outdated view."""
    by_name: dict[str, ExtensionVersionInfo]

    def outdated(self) -> list[ExtensionVersionInfo]:
        """The extensions whose installed version trails."""
        return [
            e for e in self.by_name.values() if e.is_outdated
        ]


def parse_available_extensions(
    data: bytes,
) -> AvailableExtensions:
    """Parse ``available_extensions.tsv`` into ``AvailableExtensions``.

    Returns an empty result when the TSV is empty or missing any of
    the required columns (``name``, ``version``, ``installed``).
    """
    table = parse_tsv_bytes(data)
    if not _REQUIRED_COLUMNS.issubset(table.columns):
        return AvailableExtensions(by_name={})

    installed_for: dict[str, str] = {}
    versions_for: dict[str, list[str]] = {}
    for row in table.rows:
        name = row.get("name", "")
        version = row.get("version", "")
        if not name or not version:
            continue
        versions_for.setdefault(name, []).append(version)
        if _is_true(row.get("installed", "")):
            installed_for[name] = version

    out: dict[str, ExtensionVersionInfo] = {}
    for name, versions in versions_for.items():
        installed = installed_for.get(name)
        if installed is None:
            continue
        latest = max(versions, key=_ver_tuple)
        out[name] = ExtensionVersionInfo(
            name=name, installed=installed, latest=latest,
        )
    return AvailableExtensions(by_name=out)
