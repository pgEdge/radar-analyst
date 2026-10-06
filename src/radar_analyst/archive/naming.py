"""What radar's archive name says about the collection.

Radar writes ``radar-<hostname>-<YYYYMMDD>-<HHMMSS>.zip`` and records
no collection time inside the archive, so the name is the only
source for when the collection was taken, and the first source for
which host it came from until the archive itself has been read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath


# The hostname may contain dashes, so the match is anchored on the
# trailing timestamp rather than split on the separator.
_NAME = re.compile(
    r"^radar-(?P<host>.+)-(?P<date>\d{8})-(?P<time>\d{6})\.zip$"
)


@dataclass(frozen=True)
class ArchiveName:
    """The host and collection time read from an archive's name."""
    hostname: str
    collected_at: datetime


def parse_archive_name(name: str) -> ArchiveName | None:
    """Return what *name* says, or None if it is not radar's form.

    The time in the name carries no zone: radar formats the host's
    local clock. It is returned naive, as written.
    """
    match = _NAME.match(PurePath(name).name)
    if match is None:
        return None
    try:
        collected_at = datetime.strptime(
            match["date"] + match["time"], "%Y%m%d%H%M%S"
        )
    except ValueError:
        return None
    return ArchiveName(hostname=match["host"], collected_at=collected_at)
