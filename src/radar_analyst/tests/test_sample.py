"""Tests for the radar-format sample-zip generator."""

from pathlib import Path

from radar_analyst.archive.reader import walk
from radar_analyst.parse.pg_settings import parse_pg_settings
from radar_analyst.sample import build_sample_zip


def test_generated_zip_fully_classifies(tmp_path: Path) -> None:
    z = build_sample_zip(tmp_path / "sample.zip")
    classified, unknown = walk(z)
    assert unknown == []
    kinds = {c.kind for c in classified}
    assert "pg.version" in kinds
    assert "pg.settings" in kinds
    assert "sys.sysctl" in kinds
    assert "sys.proc.meminfo" in kinds
    assert "radar.meta" in kinds
    assert "pg.roles" in kinds
    assert any(k.startswith("pg_statviz.") for k in kinds)


def test_generated_settings_look_real(tmp_path: Path) -> None:
    import zipfile

    z = build_sample_zip(tmp_path / "sample.zip")
    with zipfile.ZipFile(z) as zf:
        data = zf.read("postgresql/configuration.tsv")
    settings = parse_pg_settings(data)
    assert len(settings.all) > 100
    for name in (
        "shared_buffers",
        "max_connections",
        "wal_level",
    ):
        assert settings.get(name) is not None, name


def test_generated_statviz_entry_is_sizeable(
    tmp_path: Path,
) -> None:
    # Large enough to exercise the streaming reader, small enough
    # for CI: a few MiB uncompressed.
    z = build_sample_zip(tmp_path / "sample.zip")
    classified, _ = walk(z)
    statviz = [
        c for c in classified
        if c.kind.startswith("pg_statviz.")
    ]
    assert statviz
    assert max(c.size for c in statviz) > 2 * 1024 * 1024
