"""Tests for the postgresql/configuration.tsv (pg_settings) parser."""

from radar_analyst.parse.pg_settings import parse_pg_settings


_SAMPLE = (
    "name\tsetting\tunit\tcategory\tshort_desc\n"
    "shared_buffers\t16384\t8kB\tResource Usage / Memory\t"
    "Sets the number of shared memory buffers used by the server.\n"
    "work_mem\t4096\tkB\tResource Usage / Memory\t"
    "Sets the maximum memory to be used for query workspaces.\n"
    "max_connections\t100\t\tConnections and Authentication "
    "/ Connections\tSets the maximum number of concurrent "
    "connections.\n"
)


def test_empty_input_returns_empty_settings() -> None:
    s = parse_pg_settings(b"")
    assert s.all == {}


def test_parses_all_rows() -> None:
    s = parse_pg_settings(_SAMPLE.encode())
    assert set(s.all.keys()) == {
        "shared_buffers",
        "work_mem",
        "max_connections",
    }


def test_setting_fields_are_captured() -> None:
    s = parse_pg_settings(_SAMPLE.encode())
    shb = s.all["shared_buffers"]
    assert shb.name == "shared_buffers"
    assert shb.setting == "16384"
    assert shb.unit == "8kB"
    assert shb.category.startswith("Resource Usage")
    assert "shared memory" in shb.short_desc


def test_get_returns_setting_or_none() -> None:
    s = parse_pg_settings(_SAMPLE.encode())
    assert s.get("shared_buffers") is not None
    assert s.get("no_such_setting") is None


def test_setting_without_unit_has_empty_unit() -> None:
    s = parse_pg_settings(_SAMPLE.encode())
    assert s.all["max_connections"].unit == ""
