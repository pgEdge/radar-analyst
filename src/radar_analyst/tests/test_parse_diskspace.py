"""Tests for parse/diskspace.py."""

from radar_analyst.parse.diskspace import parse_diskspace


_HEADER = "Filesystem      Size  Used Avail Use% Mounted on\n"


def test_empty_input_returns_empty() -> None:
    assert parse_diskspace(b"") == []


def test_parses_real_disk_row() -> None:
    tsv = (
        _HEADER
        + "/dev/root       158G  150G  5.6G  97% /\n"
    )
    out = parse_diskspace(tsv.encode())
    assert len(out) == 1
    fs = out[0]
    assert fs.filesystem == "/dev/root"
    assert fs.mountpoint == "/"
    assert fs.use_pct == 97
    assert fs.size == "158G"
    assert fs.used == "150G"
    assert fs.avail == "5.6G"


def test_skips_tmpfs_and_pseudo_filesystems() -> None:
    tsv = (
        _HEADER
        + "/dev/sda1       100G   50G   50G  50% /\n"
        + "tmpfs           3.9G  1.5M  3.9G   1% /dev/shm\n"
        + "devtmpfs        4.0G     0  4.0G   0% /dev\n"
        + "overlay         100G   80G   20G  80% /var/lib/docker\n"
        + "squashfs         60M   60M     0 100% /snap/lxd/24\n"
    )
    out = parse_diskspace(tsv.encode())
    assert len(out) == 1
    assert out[0].filesystem == "/dev/sda1"


def test_handles_mountpoint_with_spaces() -> None:
    tsv = (
        _HEADER
        + "/dev/sdb1       50G   25G  25G  50% /mnt/with spaces\n"
    )
    out = parse_diskspace(tsv.encode())
    assert len(out) == 1
    assert out[0].mountpoint == "/mnt/with spaces"


def test_skips_malformed_percentage() -> None:
    tsv = _HEADER + "/dev/x  10G  5G  5G  weird% /mnt\n"
    assert parse_diskspace(tsv.encode()) == []
