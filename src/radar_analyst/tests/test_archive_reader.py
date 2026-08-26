"""Tests for the archive walker and file-kind classifier."""

import zipfile
from pathlib import Path

import pytest

from radar_analyst.archive.reader import (
    MAX_ENTRIES,
    MAX_ENTRY_SIZE_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    ClassifiedEntry,
    ZipSafetyError,
    classify,
    list_entries,
    open_entry,
    walk,
)


def _make_zip(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    """Write a zip at tmp_path/fake.zip with the given entries."""
    z_path = tmp_path / "fake.zip"
    with zipfile.ZipFile(z_path, "w") as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    return z_path


def test_list_entries_returns_each_file(tmp_path: Path) -> None:
    z = _make_zip(
        tmp_path,
        {
            "postgresql/version.tsv": b"version\nPostgreSQL 17.0\n",
            "system/sysctl.out": b"vm.swappiness = 10\n",
        },
    )
    entries = list_entries(z)
    paths = {e.path for e in entries}
    assert paths == {
        "postgresql/version.tsv",
        "system/sysctl.out",
    }


def test_list_entries_skips_directories(tmp_path: Path) -> None:
    z_path = tmp_path / "fake.zip"
    with zipfile.ZipFile(z_path, "w") as zf:
        zf.writestr("postgresql/", b"")
        zf.writestr("postgresql/version.tsv", b"x")
    entries = list_entries(z_path)
    paths = [e.path for e in entries]
    assert paths == ["postgresql/version.tsv"]


def test_classify_known_fixed_path() -> None:
    ce = classify("postgresql/version.tsv")
    assert ce is not None
    assert ce.kind == "pg.version"
    assert ce.dbname is None


def test_classify_pg_settings_path() -> None:
    ce = classify("postgresql/configuration.tsv")
    assert ce is not None
    assert ce.kind == "pg.settings"


def test_classify_sysctl_path() -> None:
    ce = classify("system/sysctl.out")
    assert ce is not None
    assert ce.kind == "sys.sysctl"


def test_classify_proc_meminfo_path() -> None:
    ce = classify("system/proc/meminfo.out")
    assert ce is not None
    assert ce.kind == "sys.proc.meminfo"


def test_classify_per_database_path() -> None:
    ce = classify("databases/mydb/extensions.tsv")
    assert ce is not None
    assert ce.kind == "pg.db.extensions"
    assert ce.dbname == "mydb"


def test_classify_pg_statviz_path() -> None:
    ce = classify("pg_statviz/mydb/buf.tsv")
    assert ce is not None
    assert ce.kind == "pg_statviz.buf"
    assert ce.dbname == "mydb"


def test_classify_unknown_returns_none() -> None:
    assert classify("not/a/real/file.txt") is None
    assert classify("postgresql/unexpected.tsv") is None


def test_walk_separates_known_from_unknown(tmp_path: Path) -> None:
    z = _make_zip(
        tmp_path,
        {
            "postgresql/version.tsv": b"x",
            "system/sysctl.out": b"x",
            "something/unknown.bin": b"x",
            "databases/mydb/tables.tsv": b"x",
        },
    )
    classified, unknown = walk(z)
    kinds = {c.kind for c in classified}
    assert kinds == {
        "pg.version",
        "sys.sysctl",
        "pg.db.tables",
    }
    assert unknown == ["something/unknown.bin"]


def test_classified_entry_is_immutable() -> None:
    ce = ClassifiedEntry(
        path="postgresql/version.tsv",
        size=42,
        kind="pg.version",
        dbname=None,
    )
    # frozen dataclass: attribute writes must raise.
    try:
        ce.kind = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ClassifiedEntry should be frozen")


# ---------------------------------------------------------------------
# DoS / zip-bomb safety
# ---------------------------------------------------------------------


def test_list_entries_rejects_too_many_entries(
    tmp_path: Path,
) -> None:
    z_path = tmp_path / "many.zip"
    with zipfile.ZipFile(z_path, "w") as zf:
        for i in range(MAX_ENTRIES + 1):
            zf.writestr(f"f{i}.txt", b"x")
    with pytest.raises(ZipSafetyError):
        list_entries(z_path)


def test_list_entries_rejects_per_entry_too_large(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Shrink the per-entry ceiling just for this test so we don't have
    # to actually emit a huge file.
    monkeypatch.setattr(
        "radar_analyst.archive.reader.MAX_ENTRY_SIZE_BYTES", 64
    )
    z = _make_zip(tmp_path, {"postgresql/version.tsv": b"x" * 128})
    with pytest.raises(ZipSafetyError):
        list_entries(z)


def test_list_entries_rejects_total_uncompressed_too_large(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "radar_analyst.archive.reader.MAX_TOTAL_UNCOMPRESSED_BYTES",
        128,
    )
    z = _make_zip(
        tmp_path,
        {
            "postgresql/version.tsv": b"x" * 100,
            "system/sysctl.out": b"y" * 100,
        },
    )
    with pytest.raises(ZipSafetyError):
        list_entries(z)


def test_open_entry_missing_path_raises(tmp_path: Path) -> None:
    z = _make_zip(tmp_path, {"postgresql/version.tsv": b"x"})
    with pytest.raises(KeyError), open_entry(z, "nope.tsv") as fh:
        fh.read()


def test_public_limits_are_sane() -> None:
    # Sanity: limits should be high enough that a real radar zip
    # fits comfortably (a pg_statviz-heavy sample was 789 MiB total
    # / 186 MiB largest entry) and a pgEdge-scale instance with
    # hundreds of databases (each contributing 28 files) has
    # headroom on entry count: while still rejecting catastrophic
    # DoS inputs.
    assert MAX_ENTRIES >= 50_000
    assert MAX_ENTRY_SIZE_BYTES >= 200 * 1024 * 1024
    assert MAX_TOTAL_UNCOMPRESSED_BYTES >= 1024 * 1024 * 1024
    assert (
        MAX_TOTAL_UNCOMPRESSED_BYTES
        >= 2 * MAX_ENTRY_SIZE_BYTES
    )


# ---------------------------------------------------------------------
# Streaming: open_entry must not buffer the whole entry in memory.
# ---------------------------------------------------------------------


def test_open_entry_yields_file_like_and_streams(
    tmp_path: Path,
) -> None:
    # 4 MiB synthetic entry. open_entry must return something we can
    # iterate without loading the whole payload.
    payload = b"x" * (4 * 1024 * 1024)
    z = _make_zip(tmp_path, {"postgresql/version.tsv": payload})
    total = 0
    with open_entry(z, "postgresql/version.tsv") as fh:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
    assert total == len(payload)


def test_open_entry_enforces_max_bytes_on_read(
    tmp_path: Path,
) -> None:
    z = _make_zip(
        tmp_path,
        {"postgresql/version.tsv": b"x" * 1024},
    )
    with pytest.raises(ZipSafetyError), open_entry(
        z, "postgresql/version.tsv", max_bytes=10
    ) as fh:
        # Trigger the cap on the first read.
        fh.read(1024)


def test_open_entry_iterates_in_chunks(
    tmp_path: Path,
) -> None:
    payload = (
        b"line1\n" + b"line2\n" + b"line3\n" + b"line4\n"
    )
    z = _make_zip(tmp_path, {"postgresql/version.tsv": payload})
    chunks: list[bytes] = []
    with open_entry(z, "postgresql/version.tsv") as fh:
        for chunk in fh:
            chunks.append(chunk)
    assert b"".join(chunks) == payload
