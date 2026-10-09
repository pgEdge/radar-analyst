"""A radar archive read by read_and_parse, then checked by the rules.

Each archive holds only the entries one case needs, written the
way radar writes them: Go's ``%v`` layout for timestamps, NULL as
an empty field.
"""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from radar_analyst.analyze.parsing import read_and_parse


_PG_VERSION = (
    "version\nPostgreSQL 15.8 on x86_64-pc-linux-gnu, "
    "compiled by gcc 11.5.0, 64-bit\n"
)


def _archive(tmp_path: Path, entries: dict[str, str]) -> Path:
    z = tmp_path / "radar-testhost-20260101-000000.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        for name, body in entries.items():
            zf.writestr(name, body)
    return z


def test_bgwriter_stats_reset_in_utc_is_read(tmp_path: Path) -> None:
    z = _archive(tmp_path, {
        "postgresql/bgwriter.tsv": (
            "checkpoints_timed\tcheckpoints_req\t"
            "checkpoint_write_time\tcheckpoint_sync_time\t"
            "buffers_checkpoint\tbuffers_clean\tmaxwritten_clean\t"
            "buffers_backend\tbuffers_backend_fsync\tbuffers_alloc\t"
            "stats_reset\n"
            "100\t10\t1.5e+06\t2000\t50000\t3000\t20\t40000\t0\t"
            "900000\t2026-02-02 06:15:30.12345 +0000 UTC\n"
        ),
    })
    parsed = read_and_parse(z)[0]
    assert parsed["pg.bgwriter"].stats_reset == datetime(
        2026, 2, 2, 6, 15, 30, 123450, tzinfo=UTC
    )
