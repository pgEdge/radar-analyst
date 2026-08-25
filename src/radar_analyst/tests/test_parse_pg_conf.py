"""Tests for parse/pg_conf.py: file_settings, hba_file_rules,
db_role_setting parsers."""

from __future__ import annotations

from radar_analyst.parse.pg_conf import (
    DbRoleSetting,
    FileSetting,
    HbaRule,
    parse_db_role_setting,
    parse_file_settings,
    parse_hba_file_rules,
)

# ---------------------------------------------------------------
# parse_file_settings
# ---------------------------------------------------------------

_FILE_SETTINGS_TSV = (
    "sourcefile\tsourceline\tseqno\tname\tsetting\tapplied\terror\n"
    "/etc/postgresql/18/main/postgresql.conf\t60\t5\t"
    "listen_addresses\t*\ttrue\t\n"
    "/etc/postgresql/18/main/postgresql.conf\t64\t6\t"
    "port\t5432\ttrue\t\n"
    "/etc/postgresql/18/main/postgresql.conf\t100\t7\t"
    "max_connections\t100\tfalse\tbad_value\n"
)


def test_parse_file_settings_returns_list() -> None:
    result = parse_file_settings(_FILE_SETTINGS_TSV.encode())
    assert result is not None
    assert len(result) == 3


def test_parse_file_settings_first_row_fields() -> None:
    result = parse_file_settings(_FILE_SETTINGS_TSV.encode())
    assert result is not None
    s = result[0]
    assert isinstance(s, FileSetting)
    assert s.name == "listen_addresses"
    assert s.setting == "*"
    assert s.applied is True
    assert s.error == ""
    assert s.sourcefile == "/etc/postgresql/18/main/postgresql.conf"
    assert s.sourceline == 60


def test_parse_file_settings_applied_false_with_error() -> None:
    result = parse_file_settings(_FILE_SETTINGS_TSV.encode())
    assert result is not None
    s = result[2]
    assert s.name == "max_connections"
    assert s.applied is False
    assert s.error == "bad_value"


def test_parse_file_settings_header_only_returns_empty() -> None:
    tsv = (
        "sourcefile\tsourceline\tseqno\tname\t"
        "setting\tapplied\terror\n"
    )
    result = parse_file_settings(tsv.encode())
    assert result == []


def test_parse_file_settings_totally_empty_returns_none() -> None:
    assert parse_file_settings(b"") is None


# ---------------------------------------------------------------
# parse_hba_file_rules
# ---------------------------------------------------------------

_HBA_RULES_TSV = (
    "rule_number\tfile_name\tline_number\ttype\tdatabase\t"
    "user_name\taddress\tnetmask\tauth_method\toptions\terror\n"
    "1\t/etc/postgresql/18/main/pg_hba.conf\t118\t"
    "local\t{all}\t{postgres}\t\t\ttrust\t\t\n"
    "2\t/etc/postgresql/18/main/pg_hba.conf\t119\t"
    "host\t{all}\t{replicator}\t172.17.0.0\t255.255.0.0\t"
    "md5\t\t\n"
    "3\t/etc/postgresql/18/main/pg_hba.conf\t125\t"
    "local\t{all}\t{all}\t\t\tscram-sha-256\t\t\n"
    "4\t/etc/postgresql/18/main/pg_hba.conf\t130\t"
    "host\t{all}\t{all}\t0.0.0.0\t0.0.0.0\t"
    "trust\t\tbad line\n"
)


def test_parse_hba_rules_returns_list() -> None:
    result = parse_hba_file_rules(_HBA_RULES_TSV.encode())
    assert result is not None
    assert len(result) == 4


def test_parse_hba_rules_first_row_fields() -> None:
    result = parse_hba_file_rules(_HBA_RULES_TSV.encode())
    assert result is not None
    r = result[0]
    assert isinstance(r, HbaRule)
    assert r.rule_number == 1
    assert r.type == "local"
    assert r.auth_method == "trust"
    assert r.error == ""


def test_parse_hba_rules_md5_row() -> None:
    result = parse_hba_file_rules(_HBA_RULES_TSV.encode())
    assert result is not None
    r = result[1]
    assert r.type == "host"
    assert r.auth_method == "md5"
    assert r.address == "172.17.0.0"


def test_parse_hba_rules_error_column() -> None:
    result = parse_hba_file_rules(_HBA_RULES_TSV.encode())
    assert result is not None
    r = result[3]
    assert r.error == "bad line"


def test_parse_hba_rules_header_only_returns_empty() -> None:
    tsv = (
        "rule_number\tfile_name\tline_number\ttype\tdatabase\t"
        "user_name\taddress\tnetmask\tauth_method\toptions\terror\n"
    )
    assert parse_hba_file_rules(tsv.encode()) == []


def test_parse_hba_rules_totally_empty_returns_none() -> None:
    assert parse_hba_file_rules(b"") is None


# ---------------------------------------------------------------
# parse_db_role_setting
# ---------------------------------------------------------------

_DB_ROLE_SETTING_TSV = (
    "setdatabase\tsetrole\tsetconfig\n"
    "16384\t0\t{search_path=myschema}\n"
    "0\t16385\t{work_mem=64MB,statement_timeout=30s}\n"
)


def test_parse_db_role_setting_populated() -> None:
    result = parse_db_role_setting(_DB_ROLE_SETTING_TSV.encode())
    assert result is not None
    assert len(result) == 2


def test_parse_db_role_setting_first_row_fields() -> None:
    result = parse_db_role_setting(_DB_ROLE_SETTING_TSV.encode())
    assert result is not None
    s = result[0]
    assert isinstance(s, DbRoleSetting)
    assert s.setdatabase == "16384"
    assert s.setrole == "0"
    assert s.setconfig == "{search_path=myschema}"


def test_parse_db_role_setting_header_only_returns_empty() -> None:
    tsv = "setdatabase\tsetrole\tsetconfig\n"
    assert parse_db_role_setting(tsv.encode()) == []


def test_parse_db_role_setting_totally_empty_returns_none() -> None:
    assert parse_db_role_setting(b"") is None
