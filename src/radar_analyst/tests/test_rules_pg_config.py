"""Tests for the pg_config rule pack."""

import pytest

from radar_analyst.parse.extensions import (
    AvailableExtensions,
    ExtensionVersionInfo,
)
from radar_analyst.parse.pg_settings import PgSetting, PgSettings
from radar_analyst.rules.pg_config import (
    enable_indexonlyscan_off,
    enable_indexscan_off,
    excessive_logging,
    outdated_extensions,
    shared_buffers_low,
    track_counts_off,
)


def _settings(
    shared_buffers_setting: str, shared_buffers_unit: str = "8kB"
) -> PgSettings:
    return PgSettings(
        all={
            "shared_buffers": PgSetting(
                name="shared_buffers",
                setting=shared_buffers_setting,
                unit=shared_buffers_unit,
                category="Resource Usage / Memory",
                short_desc="Sets shared memory buffer count.",
            )
        }
    )


def test_fires_on_default_128mb_with_53gib_ram() -> None:
    # The real sarlacc zip: shared_buffers = 16384 × 8 kB = 128 MiB,
    # MemTotal ≈ 53.6 GiB.
    parsed = {
        "pg.settings": _settings("16384"),
        "sys.proc.meminfo": {"MemTotal": 57_515_069_440},
    }
    findings = shared_buffers_low(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.config.shared_buffers_low"
    assert f.severity == "warning"
    assert "10%" in f.title


def test_silent_when_shared_buffers_is_above_10_percent() -> None:
    # 8 GiB shared_buffers on a 64 GiB host = 12.5% → no finding.
    sb_8gib_in_8kb = str((8 * 1024 * 1024 * 1024) // (8 * 1024))
    parsed = {
        "pg.settings": _settings(sb_8gib_in_8kb),
        "sys.proc.meminfo": {
            "MemTotal": 64 * 1024 * 1024 * 1024
        },
    }
    assert shared_buffers_low(parsed) == []


def test_silent_when_parser_data_missing() -> None:
    assert shared_buffers_low({}) == []
    assert (
        shared_buffers_low(
            {"pg.settings": _settings("16384")}
        )
        == []
    )


def test_handles_mb_unit() -> None:
    # shared_buffers = 128 with unit "MB" = 128 MiB on 53.6 GiB.
    parsed = {
        "pg.settings": _settings("128", "MB"),
        "sys.proc.meminfo": {"MemTotal": 57_515_069_440},
    }
    findings = shared_buffers_low(parsed)
    assert len(findings) == 1


def test_registry_includes_the_rule() -> None:
    from radar_analyst.rules.base import REGISTRY

    assert any(
        fn is shared_buffers_low
        for fn in REGISTRY.get("PostgreSQL Configuration", [])
    )


# ----------------------------------------------------------------------
# track_counts / enable_indexscan / enable_indexonlyscan
# ----------------------------------------------------------------------


def _bool_setting(name: str, value: str) -> PgSettings:
    return PgSettings(
        all={
            name: PgSetting(
                name=name,
                setting=value,
                unit="",
                category="Statistics",
                short_desc="",
            )
        }
    )


def test_track_counts_off_fires_when_disabled() -> None:
    findings = track_counts_off(
        {"pg.settings": _bool_setting("track_counts", "off")}
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "pg.config.track_counts_off"
    assert findings[0].severity == "warning"


def test_track_counts_off_silent_when_on() -> None:
    assert track_counts_off(
        {"pg.settings": _bool_setting("track_counts", "on")}
    ) == []


def test_track_counts_off_silent_when_missing() -> None:
    assert track_counts_off({}) == []
    assert track_counts_off(
        {"pg.settings": PgSettings(all={})}
    ) == []


def test_enable_indexscan_off_fires_when_disabled() -> None:
    findings = enable_indexscan_off(
        {"pg.settings": _bool_setting("enable_indexscan", "off")}
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "pg.config.enable_indexscan_off"
    assert findings[0].severity == "warning"


def test_enable_indexscan_off_silent_when_on() -> None:
    assert enable_indexscan_off(
        {"pg.settings": _bool_setting("enable_indexscan", "on")}
    ) == []


def test_enable_indexonlyscan_off_fires_when_disabled() -> None:
    findings = enable_indexonlyscan_off(
        {
            "pg.settings": _bool_setting(
                "enable_indexonlyscan", "off"
            )
        }
    )
    assert len(findings) == 1
    assert findings[0].rule_id == (
        "pg.config.enable_indexonlyscan_off"
    )


def test_enable_indexonlyscan_off_silent_when_on() -> None:
    assert enable_indexonlyscan_off(
        {
            "pg.settings": _bool_setting(
                "enable_indexonlyscan", "on"
            )
        }
    ) == []


# ----------------------------------------------------------------------
# excessive_logging
# ----------------------------------------------------------------------


def _multi(**kv: str) -> PgSettings:
    return PgSettings(
        all={
            k: PgSetting(
                name=k, setting=v, unit="",
                category="Reporting and Logging",
                short_desc="",
            )
            for k, v in kv.items()
        }
    )


def test_excessive_logging_fires_log_statement_all() -> None:
    findings = excessive_logging(
        {"pg.settings": _multi(log_statement="all")}
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "pg.config.excessive_logging"
    assert "log_statement" in findings[0].detail


def test_excessive_logging_fires_log_min_duration_zero() -> None:
    findings = excessive_logging(
        {
            "pg.settings": _multi(
                log_min_duration_statement="0"
            )
        }
    )
    assert len(findings) == 1
    assert "log_min_duration_statement" in findings[0].detail


def test_excessive_logging_fires_debug_log_min_messages() -> None:
    for level in (
        "debug1", "debug2", "debug3", "debug4", "debug5",
    ):
        findings = excessive_logging(
            {"pg.settings": _multi(log_min_messages=level)}
        )
        assert len(findings) == 1
        assert "log_min_messages" in findings[0].detail


def test_excessive_logging_aggregates_multiple_offenders() -> None:
    findings = excessive_logging(
        {
            "pg.settings": _multi(
                log_statement="mod",
                log_min_duration_statement="0",
                log_min_messages="debug2",
            )
        }
    )
    assert len(findings) == 1
    detail = findings[0].detail
    assert "log_statement" in detail
    assert "log_min_duration_statement" in detail
    assert "log_min_messages" in detail


def test_excessive_logging_silent_on_safe_values() -> None:
    parsed = {
        "pg.settings": _multi(
            log_statement="ddl",
            log_min_duration_statement="-1",
            log_min_messages="warning",
        )
    }
    assert excessive_logging(parsed) == []


def test_excessive_logging_silent_when_missing() -> None:
    assert excessive_logging({}) == []
    assert excessive_logging(
        {"pg.settings": PgSettings(all={})}
    ) == []


# ----------------------------------------------------------------------
# outdated_extensions
# ----------------------------------------------------------------------


def test_outdated_extensions_fires_for_upgradable() -> None:
    av = AvailableExtensions(
        by_name={
            "pg_stat_statements": ExtensionVersionInfo(
                name="pg_stat_statements",
                installed="1.10",
                latest="1.11",
            ),
            "pgcrypto": ExtensionVersionInfo(
                name="pgcrypto", installed="1.3", latest="1.3",
            ),
        }
    )
    findings = outdated_extensions(
        {"pg.available_extensions": av}
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.config.outdated_extensions"
    assert f.severity == "info"
    assert "pg_stat_statements" in f.detail
    assert "pgcrypto" not in f.detail


def test_outdated_extensions_silent_when_all_current() -> None:
    av = AvailableExtensions(
        by_name={
            "pgcrypto": ExtensionVersionInfo(
                name="pgcrypto", installed="1.3", latest="1.3",
            ),
        }
    )
    assert outdated_extensions(
        {"pg.available_extensions": av}
    ) == []


def test_outdated_extensions_silent_when_data_missing() -> None:
    assert outdated_extensions({}) == []


# ----------------------------------------------------------------------
# shared_buffers_high
# ----------------------------------------------------------------------


def test_shared_buffers_high_silent_below_40_pct() -> None:
    from radar_analyst.rules.pg_config import shared_buffers_high

    sb_2gib = (2 * 1024 * 1024 * 1024) // (8 * 1024)
    parsed = {
        "pg.settings": _settings(str(sb_2gib)),
        "sys.proc.meminfo": {"MemTotal": 64 * 1024 ** 3},
    }
    assert shared_buffers_high(parsed) == []


def test_shared_buffers_high_warns_above_40_pct() -> None:
    from radar_analyst.rules.pg_config import shared_buffers_high

    sb_30gib = (30 * 1024 * 1024 * 1024) // (8 * 1024)
    parsed = {
        "pg.settings": _settings(str(sb_30gib)),
        "sys.proc.meminfo": {"MemTotal": 64 * 1024 ** 3},
    }
    findings = shared_buffers_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


# ----------------------------------------------------------------------
# maintenance_work_mem_low
# ----------------------------------------------------------------------


def test_maintenance_work_mem_low_silent_on_small_host() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        maintenance_work_mem_low,
    )

    settings = PgSettings(
        all={
            "maintenance_work_mem": PgSetting(
                name="maintenance_work_mem",
                setting="65536",  # 64 MiB
                unit="kB",
                category="Resource Usage / Memory",
                short_desc="",
            )
        }
    )
    parsed = {
        "pg.settings": settings,
        "sys.proc.meminfo": {"MemTotal": 8 * 1024 ** 3},
    }
    # 8 GiB host: below floor; no finding regardless of value.
    assert maintenance_work_mem_low(parsed) == []


def test_maintenance_work_mem_low_info_on_big_host() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        maintenance_work_mem_low,
    )

    settings = PgSettings(
        all={
            "maintenance_work_mem": PgSetting(
                name="maintenance_work_mem",
                setting="65536",
                unit="kB",
                category="Resource Usage / Memory",
                short_desc="",
            )
        }
    )
    parsed = {
        "pg.settings": settings,
        "sys.proc.meminfo": {"MemTotal": 64 * 1024 ** 3},
    }
    findings = maintenance_work_mem_low(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "info"


# ----------------------------------------------------------------------
# max_wal_size_low
# ----------------------------------------------------------------------


def test_max_wal_size_low_info_at_default() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import max_wal_size_low

    settings = PgSettings(
        all={
            "max_wal_size": PgSetting(
                name="max_wal_size",
                setting="1024",
                unit="MB",
                category="Write-Ahead Log",
                short_desc="",
            )
        }
    )
    findings = max_wal_size_low({"pg.settings": settings})
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_max_wal_size_low_silent_when_raised() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import max_wal_size_low

    settings = PgSettings(
        all={
            "max_wal_size": PgSetting(
                name="max_wal_size",
                setting="8192",  # 8 GiB
                unit="MB",
                category="Write-Ahead Log",
                short_desc="",
            )
        }
    )
    assert max_wal_size_low({"pg.settings": settings}) == []


# ----------------------------------------------------------------------
# checkpoint_timeout_short
# ----------------------------------------------------------------------


def test_checkpoint_timeout_short_silent_at_default() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        checkpoint_timeout_short,
    )

    settings = PgSettings(
        all={
            "checkpoint_timeout": PgSetting(
                name="checkpoint_timeout",
                setting="300",
                unit="s",
                category="Write-Ahead Log",
                short_desc="",
            )
        }
    )
    assert checkpoint_timeout_short(
        {"pg.settings": settings}
    ) == []


def test_checkpoint_timeout_short_info_below_5min() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        checkpoint_timeout_short,
    )

    settings = PgSettings(
        all={
            "checkpoint_timeout": PgSetting(
                name="checkpoint_timeout",
                setting="60",
                unit="s",
                category="Write-Ahead Log",
                short_desc="",
            )
        }
    )
    findings = checkpoint_timeout_short(
        {"pg.settings": settings}
    )
    assert len(findings) == 1
    assert findings[0].severity == "info"


# ----------------------------------------------------------------------
# missing_essential_preload_libs
# ----------------------------------------------------------------------


def test_preload_libs_silent_when_pg_stat_statements_loaded() -> (
    None
):
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        missing_essential_preload_libs,
    )

    settings = PgSettings(
        all={
            "shared_preload_libraries": PgSetting(
                name="shared_preload_libraries",
                setting="pg_stat_statements,auto_explain",
                unit="",
                category="Resource Usage",
                short_desc="",
            )
        }
    )
    assert missing_essential_preload_libs(
        {"pg.settings": settings}
    ) == []


def test_preload_libs_warns_when_pgss_missing() -> None:
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        missing_essential_preload_libs,
    )

    settings = PgSettings(
        all={
            "shared_preload_libraries": PgSetting(
                name="shared_preload_libraries",
                setting="",
                unit="",
                category="Resource Usage",
                short_desc="",
            )
        }
    )
    findings = missing_essential_preload_libs(
        {"pg.settings": settings}
    )
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "pg_stat_statements" in findings[0].detail


def test_preload_libs_silent_when_only_pgss_loaded() -> None:
    # auto_explain and other diagnostic libs are deliberately not
    # recommended: pg_stat_statements alone is enough.
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        missing_essential_preload_libs,
    )

    settings = PgSettings(
        all={
            "shared_preload_libraries": PgSetting(
                name="shared_preload_libraries",
                setting="pg_stat_statements",
                unit="",
                category="Resource Usage",
                short_desc="",
            )
        }
    )
    assert missing_essential_preload_libs(
        {"pg.settings": settings}
    ) == []


def test_preload_libs_does_not_recommend_auto_explain() -> None:
    # Regression guard: auto_explain must never appear in the
    # finding's detail. It's a diagnostic tool, not a default.
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings
    from radar_analyst.rules.pg_config import (
        missing_essential_preload_libs,
    )

    settings = PgSettings(
        all={
            "shared_preload_libraries": PgSetting(
                name="shared_preload_libraries",
                setting="",  # nothing loaded → fires
                unit="",
                category="Resource Usage",
                short_desc="",
            )
        }
    )
    findings = missing_essential_preload_libs(
        {"pg.settings": settings}
    )
    assert len(findings) == 1
    assert "auto_explain" not in findings[0].detail
    assert "auto_explain" not in findings[0].title


# ----------------------------------------------------------------------
# pg_version_eol
# ----------------------------------------------------------------------


def test_pg_version_eol_silent_when_unknown_major() -> None:
    from radar_analyst.parse.pg_version import PgVersionInfo
    from radar_analyst.rules.pg_config import pg_version_eol

    parsed = {
        "pg.version": PgVersionInfo(
            raw="PostgreSQL 99", major=99, minor=0
        )
    }
    assert pg_version_eol(parsed) == []


def test_pg_version_eol_critical_for_pg11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.pg_config as mod
    from radar_analyst.parse.pg_version import PgVersionInfo

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return date(2026, 1, 1)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "pg.version": PgVersionInfo(
            raw="PostgreSQL 11.22", major=11, minor=22
        )
    }
    findings = mod.pg_version_eol(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"


def test_pg_version_eol_warning_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.pg_config as mod
    from radar_analyst.parse.pg_version import PgVersionInfo

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            # 5 months before PG 14 EOL (2026-11-12)
            return date(2026, 6, 12)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "pg.version": PgVersionInfo(
            raw="PostgreSQL 14.5", major=14, minor=5
        )
    }
    findings = mod.pg_version_eol(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_pg_version_eol_silent_far_from_eol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    import radar_analyst.rules.pg_config as mod
    from radar_analyst.parse.pg_version import PgVersionInfo

    class _Fixed(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return date(2026, 1, 1)

    monkeypatch.setattr(mod, "date", _Fixed)
    parsed = {
        "pg.version": PgVersionInfo(
            raw="PostgreSQL 17.2", major=17, minor=2
        )
    }
    assert mod.pg_version_eol(parsed) == []


# ----------------------------------------------------------------------
# max_connections_high
# ----------------------------------------------------------------------


def _max_conn_settings(n: int) -> PgSettings:
    return PgSettings(
        all={
            "max_connections": PgSetting(
                name="max_connections",
                setting=str(n),
                unit="",
                category="Connections",
                short_desc="",
            )
        }
    )


def test_max_connections_silent_below_200() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    parsed = {
        "pg.settings": _max_conn_settings(150),
        "sys.lscpu": {"CPU(s)": "4"},
    }
    assert max_connections_high(parsed) == []


def test_max_connections_info_in_200_to_499() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    parsed = {
        "pg.settings": _max_conn_settings(300),
        "sys.lscpu": {"CPU(s)": "200"},  # 4×200 = 800 > 300
    }
    findings = max_connections_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_max_connections_warns_at_500_even_with_huge_cpu() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    parsed = {
        "pg.settings": _max_conn_settings(500),
        "sys.lscpu": {"CPU(s)": "256"},  # 4×256 = 1024 > 500
    }
    findings = max_connections_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_max_connections_warns_when_over_4x_cpu() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    # 250 conn on 8 cores = 31.25× cores. 4×8 = 32. So 250 > 32 → warn.
    parsed = {
        "pg.settings": _max_conn_settings(250),
        "sys.lscpu": {"CPU(s)": "8"},
    }
    findings = max_connections_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    # Detail should mention CPU multiplier when that's the trigger.
    assert "CPU" in findings[0].detail or "core" in findings[0].detail


def test_max_connections_silent_when_proportional_to_cpu() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    # 150 conn on 64 cores: under both thresholds.
    parsed = {
        "pg.settings": _max_conn_settings(150),
        "sys.lscpu": {"CPU(s)": "64"},
    }
    assert max_connections_high(parsed) == []


def test_max_connections_falls_back_when_cpu_unknown() -> None:
    # No sys.lscpu data → only the absolute thresholds apply.
    from radar_analyst.rules.pg_config import max_connections_high

    parsed = {
        "pg.settings": _max_conn_settings(300),
    }
    findings = max_connections_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_max_connections_silent_when_no_settings() -> None:
    from radar_analyst.rules.pg_config import max_connections_high

    assert max_connections_high({}) == []
