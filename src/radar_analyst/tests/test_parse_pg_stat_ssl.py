"""Tests for parse/pg_stat_ssl.py."""

from radar_analyst.parse.pg_stat_ssl import (
    SslConnection,
    StatSsl,
    parse_stat_ssl,
)


_HEADER = (
    "pid\tssl\tversion\tcipher\tbits\tclient_dn\tclient_serial\t"
    "issuer_dn\tusename\tapplication_name\tclient_addr\n"
)


def test_empty_returns_empty() -> None:
    assert parse_stat_ssl(b"").rows == []


def test_missing_columns_returns_empty() -> None:
    assert parse_stat_ssl(b"pid\n123\n").rows == []


def test_parse_one_secure_one_insecure() -> None:
    tsv = (
        _HEADER
        + "100\tt\tTLSv1.3\tTLS_AES_256_GCM\t256\t\t\t\tapp\tweb\t10.0.0.1\n"
        + "101\tf\t\t\t\t\t\t\tpgbouncer\tpgb\t/tmp\n"
    )
    out = parse_stat_ssl(tsv.encode())
    assert isinstance(out, StatSsl)
    assert len(out) == 2
    assert isinstance(out.rows[0], SslConnection)
    assert out.rows[0].ssl is True
    assert out.rows[1].ssl is False


def test_insecure_filter() -> None:
    tsv = (
        _HEADER
        + "100\tt\t\t\t\t\t\t\t\t\t\n"
        + "101\tf\t\t\t\t\t\t\t\t\t\n"
        + "102\tf\t\t\t\t\t\t\t\t\t\n"
    )
    out = parse_stat_ssl(tsv.encode())
    bad = out.insecure()
    assert len(bad) == 2
    assert all(not c.ssl for c in bad)


def test_drops_blank_pid_row() -> None:
    tsv = (
        _HEADER
        + "\tt\t\t\t\t\t\t\t\t\t\n"
        + "100\tf\t\t\t\t\t\t\t\t\t\n"
    )
    out = parse_stat_ssl(tsv.encode())
    assert len(out) == 1
    assert out.rows[0].pid == "100"
