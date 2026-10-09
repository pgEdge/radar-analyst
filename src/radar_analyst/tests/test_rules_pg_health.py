"""Tests for the Internals & I/O Health rule pack."""

from radar_analyst.parse.databases import DatabaseInfo
from radar_analyst.parse.pg_db_indexes import IndexesPerDb, IndexRow
from radar_analyst.parse.pg_db_sequences import (
    SequenceRow,
    SequencesPerDb,
)
from radar_analyst.parse.pg_db_tables import TableRow, TablesPerDb
from radar_analyst.parse.pg_settings import PgSetting, PgSettings
from radar_analyst.parse.pg_wal import PgArchiver
from radar_analyst.rules.pg_health import (
    archiver_failing,
    autoanalyze_lagging,
    autovacuum_disabled_per_table,
    autovacuum_lagging,
    duplicate_indexes,
    invalid_databases,
    invalid_indexes,
    mxid_wraparound_high,
    sequence_exhaustion,
    tables_high_dead_rows,
    toast_dominates_heap,
    txid_wraparound_high,
    unlogged_tables_present,
    unused_indexes,
)


def _seq(
    name: str,
    *,
    schema: str = "public",
    last: int = 0,
    max_v: int = 2_147_483_647,
    min_v: int = 1,
) -> SequenceRow:
    return SequenceRow(
        schemaname=schema,
        sequencename=name,
        last_value=last,
        max_value=max_v,
        min_value=min_v,
    )


def _idx(
    name: str,
    *,
    schema: str = "public",
    table: str = "t",
    relid: str = "16400",
    indclass: str = "10001",
    indkey: str = "1",
    valid: bool = True,
    primary: bool = False,
    unique: bool = False,
    size: int = 1024,
    scan: int = 1,
) -> IndexRow:
    return IndexRow(
        schemaname=schema,
        tablename=table,
        indexname=name,
        indrelid=relid,
        indclass=indclass,
        indkey=indkey,
        indisvalid=valid,
        indisprimary=primary,
        indisunique=unique,
        index_size=size,
        idx_scan=scan,
    )


def _table(
    schema: str = "public",
    name: str = "t",
    *,
    live: int = 0,
    dead: int = 0,
    persistence: str = "p",
    reloptions: list[str] | None = None,
    heap_size: int = 0,
    toast_size: int | None = None,
    reltuples: float = 0.0,
    mod_since_analyze: int = 0,
    autoanalyze_age: int | None = None,
) -> TableRow:
    return TableRow(
        schemaname=schema,
        tablename=name,
        relpersistence=persistence,
        reloptions=reloptions or [],
        n_live_tup=live,
        n_dead_tup=dead,
        heap_size=heap_size,
        toast_size=toast_size,
        reltuples=reltuples,
        n_mod_since_analyze=mod_since_analyze,
        last_autoanalyze_age_seconds=autoanalyze_age,
    )


def _settings(values: dict[str, str]) -> PgSettings:
    return PgSettings(
        all={
            name: PgSetting(
                name=name,
                setting=setting,
                unit="",
                category="",
                short_desc="",
            )
            for name, setting in values.items()
        }
    )


def _db(
    name: str,
    *,
    age: int | None = None,
    mxid_age: int | None = None,
    connlimit: int = -1,
    is_template: bool = False,
) -> DatabaseInfo:
    return DatabaseInfo(
        datname=name,
        datistemplate=is_template,
        datallowconn=True,
        datconnlimit=connlimit,
        datfrozenxid=None,
        frozenxid_age=age,
        datminmxid=None,
        minmxid_age=mxid_age,
    )


# ----------------------------------------------------------------------
# txid_wraparound_high
# ----------------------------------------------------------------------


def test_txid_wraparound_silent_below_warn() -> None:
    parsed = {
        "pg.databases": [
            _db("postgres", age=200_000_000),
            _db("mydb", age=499_999_999),
        ]
    }
    assert txid_wraparound_high(parsed) == []


def test_txid_wraparound_warning_at_500m() -> None:
    parsed = {
        "pg.databases": [
            _db("postgres", age=100_000_000),
            _db("mydb", age=500_000_000),
        ]
    }
    findings = txid_wraparound_high(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.health.txid_wraparound_high"
    assert f.severity == "warning"
    assert "mydb" in f.title


def test_txid_wraparound_critical_at_critical_age() -> None:
    parsed = {
        "pg.databases": [
            _db("doomed", age=1_700_000_000),
        ]
    }
    findings = txid_wraparound_high(parsed)
    assert findings[0].severity == "critical"


def test_txid_wraparound_picks_worst_database() -> None:
    parsed = {
        "pg.databases": [
            _db("a", age=1_100_000_000),
            _db("b", age=1_800_000_000),
            _db("c", age=300_000_000),
        ]
    }
    findings = txid_wraparound_high(parsed)
    assert len(findings) == 1
    assert "b" in findings[0].title
    assert findings[0].severity == "critical"


def test_txid_wraparound_silent_when_age_unknown() -> None:
    # Older radar archives don't carry frozenxid_age: rule
    # must not fire on missing data.
    parsed = {"pg.databases": [_db("postgres", age=None)]}
    assert txid_wraparound_high(parsed) == []


def test_txid_wraparound_silent_when_no_data() -> None:
    assert txid_wraparound_high({}) == []
    assert txid_wraparound_high({"pg.databases": []}) == []


# ----------------------------------------------------------------------
# invalid_databases
# ----------------------------------------------------------------------


def test_invalid_databases_fires_on_minus_two_connlimit() -> None:
    parsed = {
        "pg.databases": [
            _db("good", connlimit=-1),
            _db("doomed", connlimit=-2),
        ]
    }
    findings = invalid_databases(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.health.invalid_databases"
    assert f.severity == "critical"
    assert "doomed" in f.detail


def test_invalid_databases_silent_when_all_healthy() -> None:
    parsed = {
        "pg.databases": [
            _db("postgres", connlimit=-1),
            _db("mydb", connlimit=100),
        ]
    }
    assert invalid_databases(parsed) == []


def test_invalid_databases_silent_when_no_data() -> None:
    assert invalid_databases({}) == []


# ----------------------------------------------------------------------
# tables_high_dead_rows
# ----------------------------------------------------------------------


def test_tables_high_dead_rows_silent_when_no_data() -> None:
    assert tables_high_dead_rows({}) == []
    assert tables_high_dead_rows({"pg.db.tables": {}}) == []


def test_tables_high_dead_rows_silent_below_threshold() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(name="t", live=10000, dead=1500),
                ]
            ),
        }
    }
    assert tables_high_dead_rows(parsed) == []


def test_tables_high_dead_rows_warns_at_20_percent() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(name="hot", live=4000, dead=2000),
                ]
            ),
        }
    }
    findings = tables_high_dead_rows(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "warning"
    assert "hot" in f.detail


def test_tables_high_dead_rows_critical_on_huge_offender() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="rotten",
                        live=100_000,
                        dead=200_000,
                    ),
                ]
            ),
        }
    }
    findings = tables_high_dead_rows(parsed)
    assert findings[0].severity == "critical"


def test_tables_high_dead_rows_after_a_counter_restart() -> None:
    # No vacuum or analyze on record: reltuples is the live count.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="big",
                        live=650,
                        dead=135_000,
                        reltuples=1.2e8,
                    ),
                ]
            ),
        }
    }
    assert tables_high_dead_rows(parsed) == []


def test_tables_high_dead_rows_skips_low_volume_tables() -> None:
    # Tiny tables with high dead ratios shouldn't trigger.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(name="tiny", live=100, dead=200),
                ]
            ),
        }
    }
    assert tables_high_dead_rows(parsed) == []


# ----------------------------------------------------------------------
# autovacuum_disabled_per_table
# ----------------------------------------------------------------------


def test_autovacuum_disabled_silent_when_none() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[_table(name="ok", live=1, dead=0)],
            ),
        }
    }
    assert autovacuum_disabled_per_table(parsed) == []


def test_autovacuum_disabled_critical_when_present() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="frozen",
                        reloptions=["autovacuum_enabled=off"],
                    ),
                    _table(name="ok"),
                ]
            ),
        }
    }
    findings = autovacuum_disabled_per_table(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "critical"
    assert "mydb/public.frozen" in f.detail


# ----------------------------------------------------------------------
# toast_dominates_heap
# ----------------------------------------------------------------------

_MIB = 1024 * 1024


def test_toast_dominates_silent_when_no_data() -> None:
    assert toast_dominates_heap({}) == []
    assert toast_dominates_heap({"pg.db.tables": {}}) == []


def test_toast_dominates_silent_below_size_floor() -> None:
    # An 8 KiB heap with 144 KiB TOAST is 18× ratio yet
    # operationally meaningless, so it must not fire. (Modeled
    # on a tiny real-world contacts table.)
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="contacts",
                        heap_size=8 * 1024,
                        toast_size=144 * 1024,
                    ),
                ]
            ),
        }
    }
    assert toast_dominates_heap(parsed) == []


def test_toast_dominates_silent_when_ratio_below_two() -> None:
    # Big TOAST (200 MiB) but matching heap (300 MiB): ratio 0.67,
    # not dominant. A wide bytea-heavy app table growing in
    # proportion is fine.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="docs",
                        heap_size=300 * _MIB,
                        toast_size=200 * _MIB,
                    ),
                ]
            ),
        }
    }
    assert toast_dominates_heap(parsed) == []


def test_toast_dominates_silent_when_toast_below_floor() -> None:
    # Ratio is 5× but absolute TOAST is only 50 MiB: below the
    # 100 MiB operational floor. Must not fire.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="t",
                        heap_size=10 * _MIB,
                        toast_size=50 * _MIB,
                    ),
                ]
            ),
        }
    }
    assert toast_dominates_heap(parsed) == []


def test_toast_dominates_fires_when_both_thresholds_met() -> None:
    # Heap 100 MiB, TOAST 1 GiB: 10× ratio, well above the 100
    # MiB absolute floor. Schema-design red flag.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="documents",
                        heap_size=100 * _MIB,
                        toast_size=1024 * _MIB,
                    ),
                ]
            ),
        }
    }
    findings = toast_dominates_heap(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.health.toast_dominates_heap"
    assert f.severity == "info"
    assert "mydb/public.documents" in f.detail


def test_toast_dominates_fires_at_zero_heap_when_toast_huge() -> None:
    # Edge case: heap = 0 (rare but possible after TRUNCATE that
    # somehow left TOAST behind, or a pathological bulk-load
    # state). With heap=0 we can't compute a ratio, but a
    # multi-GiB TOAST sitting on an empty heap is a strong signal.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="orphan",
                        heap_size=0,
                        toast_size=2 * 1024 * _MIB,
                    ),
                ]
            ),
        }
    }
    findings = toast_dominates_heap(parsed)
    assert len(findings) == 1
    assert "mydb/public.orphan" in findings[0].detail


def test_toast_dominates_silent_when_toast_size_none() -> None:
    # Older parsers / no-TOAST tables: toast_size is None.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="t",
                        heap_size=500 * _MIB,
                        toast_size=None,
                    ),
                ]
            ),
        }
    }
    assert toast_dominates_heap(parsed) == []


def test_toast_dominates_lists_top_offenders_sorted() -> None:
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _table(
                        name="small_offender",
                        heap_size=50 * _MIB,
                        toast_size=200 * _MIB,
                    ),
                    _table(
                        name="big_offender",
                        heap_size=200 * _MIB,
                        toast_size=4 * 1024 * _MIB,
                    ),
                ]
            ),
        }
    }
    findings = toast_dominates_heap(parsed)
    assert len(findings) == 1
    detail = findings[0].detail
    # Biggest TOAST first.
    assert detail.index("big_offender") < (
        detail.index("small_offender")
    )


# ----------------------------------------------------------------------
# duplicate_indexes
# ----------------------------------------------------------------------


def test_duplicate_indexes_silent_when_none() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx("idx_a", indkey="1"),
                    _idx("idx_b", indkey="2"),
                ]
            )
        }
    }
    assert duplicate_indexes(parsed) == []


def test_duplicate_indexes_warns_on_semantic_dupe() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx("idx_a", indkey="1", size=8192),
                    _idx("idx_b", indkey="1", size=8192),
                    _idx("idx_other", indkey="2"),
                ]
            )
        }
    }
    findings = duplicate_indexes(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "idx_a" in findings[0].detail
    assert "idx_b" in findings[0].detail


def test_duplicate_indexes_silent_when_no_dedup_data() -> None:
    # Pre-0.5.0 radar zips have only schemaname / tablename /
    # indexname / indexdef in indexes.tsv: the dedup-key columns
    # (indrelid, indclass, indkey, indexprs, indpred) don't exist
    # so the parser fills them with empty strings. Without the
    # gate, every index would land in one giant false-positive
    # duplicate group.
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "idx_a",
                        relid="",
                        indclass="",
                        indkey="",
                    ),
                    _idx(
                        "idx_b",
                        relid="",
                        indclass="",
                        indkey="",
                    ),
                    _idx(
                        "idx_c",
                        relid="",
                        indclass="",
                        indkey="",
                    ),
                ]
            )
        }
    }
    assert duplicate_indexes(parsed) == []


# ----------------------------------------------------------------------
# invalid_indexes
# ----------------------------------------------------------------------


def test_invalid_indexes_critical_when_present() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx("good", valid=True),
                    _idx("broken", valid=False),
                ]
            )
        }
    }
    findings = invalid_indexes(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert "mydb/public.broken" in findings[0].detail


def test_invalid_indexes_silent_when_all_valid() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[_idx("good", valid=True)]
            )
        }
    }
    assert invalid_indexes(parsed) == []


# ----------------------------------------------------------------------
# unused_indexes
# ----------------------------------------------------------------------


def test_unused_indexes_silent_below_size_floor() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "small_unused",
                        scan=0,
                        size=1024 * 1024,  # 1 MiB
                    ),
                ]
            )
        }
    }
    assert unused_indexes(parsed) == []


def test_unused_indexes_info_at_64mib() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "big_dead",
                        scan=0,
                        size=128 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    findings = unused_indexes(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert "big_dead" in findings[0].detail


def test_unused_indexes_excludes_primary_keys() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "users_pkey",
                        scan=0,
                        size=200 * 1024 * 1024,
                        primary=True,
                    ),
                ]
            )
        }
    }
    assert unused_indexes(parsed) == []


def test_unused_indexes_silent_when_scanned() -> None:
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "live",
                        scan=1,
                        size=200 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    assert unused_indexes(parsed) == []


def test_unused_indexes_detail_is_factual_not_a_procedure() -> None:
    # The rule must not gesture at "verifying" idx_scan via
    # stats_reset or any other counter-watching ceremony.
    # Resetting a counter that's already 0 yields another 0:
    # an incoherent verification step. The rule states the fact
    # and trusts the operator to evaluate it.
    parsed = {
        "pg.db.indexes": {
            "mydb": IndexesPerDb(
                rows=[
                    _idx(
                        "fat_dead",
                        scan=0,
                        size=200 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    findings = unused_indexes(parsed)
    detail = findings[0].detail.lower()
    assert "verify" not in detail
    assert "stats_reset" not in detail
    assert "pg_stat_reset" not in detail
    assert "business cycle" not in detail


# ----------------------------------------------------------------------
# sequence_exhaustion
# ----------------------------------------------------------------------


def test_sequence_exhaustion_silent_when_no_data() -> None:
    assert sequence_exhaustion({}) == []


def test_sequence_exhaustion_silent_for_unbounded_bigint() -> None:
    parsed = {
        "pg.db.sequences": {
            "mydb": SequencesPerDb(
                rows=[
                    SequenceRow(
                        schemaname="public",
                        sequencename="ids",
                        last_value=1_000_000,
                        max_value=9_223_372_036_854_775_807,
                        min_value=1,
                    ),
                ]
            )
        }
    }
    assert sequence_exhaustion(parsed) == []


def test_sequence_exhaustion_info_under_10_percent() -> None:
    parsed = {
        "pg.db.sequences": {
            "mydb": SequencesPerDb(
                rows=[
                    _seq(
                        "small_ids",
                        last=1_988_854_775,
                    ),  # ~7.4% remaining
                ]
            )
        }
    }
    findings = sequence_exhaustion(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_sequence_exhaustion_warning_under_5_percent() -> None:
    parsed = {
        "pg.db.sequences": {
            "mydb": SequencesPerDb(
                rows=[
                    _seq(
                        "small_ids",
                        last=2_080_000_000,
                    ),  # ~3.1% remaining
                ]
            )
        }
    }
    findings = sequence_exhaustion(parsed)
    assert findings[0].severity == "warning"


def test_sequence_exhaustion_critical_under_1_percent() -> None:
    parsed = {
        "pg.db.sequences": {
            "mydb": SequencesPerDb(
                rows=[
                    _seq(
                        "doomed_ids",
                        last=2_140_000_000,
                    ),  # ~0.35% remaining
                ]
            )
        }
    }
    findings = sequence_exhaustion(parsed)
    assert findings[0].severity == "critical"


def test_sequence_exhaustion_picks_worst_severity() -> None:
    parsed = {
        "pg.db.sequences": {
            "mydb": SequencesPerDb(
                rows=[
                    _seq("nine_pct", last=1_990_000_000),
                    _seq("two_pct", last=2_120_000_000),
                    _seq("half_pct", last=2_140_000_000),
                ]
            )
        }
    }
    findings = sequence_exhaustion(parsed)
    assert findings[0].severity == "critical"
    # All three should still appear in the title count
    assert "1" in findings[0].title


# ----------------------------------------------------------------------
# bloat_high
# ----------------------------------------------------------------------


def test_bloat_high_silent_when_no_data() -> None:
    from radar_analyst.rules.pg_health import bloat_high

    assert bloat_high({}) == []


def test_bloat_high_pgstattuple_warns_on_heavy_dead_pct() -> None:
    from radar_analyst.parse.pg_db_bloat import (
        PgStatTuplePerDb,
        PgStatTupleRow,
    )
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.pgstattuple": {
            "mydb": PgStatTuplePerDb(
                rows=[
                    PgStatTupleRow(
                        schemaname="public",
                        tablename="orders",
                        dead_tuple_percent=35.0,
                        dead_tuple_len=200 * 1024 * 1024,
                    ),
                    PgStatTupleRow(
                        schemaname="public",
                        tablename="ok",
                        dead_tuple_percent=5.0,
                    ),
                ]
            )
        }
    }
    findings = bloat_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "orders" in findings[0].detail


def test_bloat_high_pgstattuple_skips_below_size_floor() -> None:
    from radar_analyst.parse.pg_db_bloat import (
        PgStatTuplePerDb,
        PgStatTupleRow,
    )
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.pgstattuple": {
            "mydb": PgStatTuplePerDb(
                rows=[
                    PgStatTupleRow(
                        schemaname="public",
                        tablename="tiny",
                        dead_tuple_percent=80.0,
                        dead_tuple_len=512 * 1024,
                    ),
                ]
            )
        }
    }
    assert bloat_high(parsed) == []


def test_bloat_high_heuristic_silent_below_50pct_ratio() -> None:
    # 1.95× = 49% wasted, just under the 50% (2.0×) heuristic
    # warn threshold. Must not fire even with massive wastedbytes.
    from radar_analyst.parse.pg_db_bloat import BloatPerDb, BloatRow
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.bloat": {
            "mydb": BloatPerDb(
                rows=[
                    BloatRow(
                        schemaname="public",
                        tablename="t",
                        table_bloat_ratio=1.95,
                        wastedbytes=512 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    assert bloat_high(parsed) == []


def test_bloat_high_heuristic_warns_at_50pct_ratio() -> None:
    # Exactly 2.0× = 50% wasted should warn (assuming size floor met).
    from radar_analyst.parse.pg_db_bloat import BloatPerDb, BloatRow
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.bloat": {
            "mydb": BloatPerDb(
                rows=[
                    BloatRow(
                        schemaname="public",
                        tablename="t",
                        table_bloat_ratio=2.0,
                        wastedbytes=512 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    findings = bloat_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_bloat_high_falls_back_to_heuristic() -> None:
    from radar_analyst.parse.pg_db_bloat import BloatPerDb, BloatRow
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.bloat": {
            "mydb": BloatPerDb(
                rows=[
                    BloatRow(
                        schemaname="public",
                        tablename="historic",
                        table_bloat_ratio=2.5,
                        wastedbytes=512 * 1024 * 1024,
                    ),
                ]
            )
        }
    }
    findings = bloat_high(parsed)
    assert len(findings) == 1
    assert "historic" in findings[0].detail


def test_bloat_high_pgstattuple_takes_precedence_when_both() -> None:
    # Same table appears in both: the pgstattuple result is
    # authoritative; the heuristic shouldn't double-count.
    from radar_analyst.parse.pg_db_bloat import (
        BloatPerDb,
        BloatRow,
        PgStatTuplePerDb,
        PgStatTupleRow,
    )
    from radar_analyst.rules.pg_health import bloat_high

    parsed = {
        "pg.db.pgstattuple": {
            "mydb": PgStatTuplePerDb(
                rows=[
                    PgStatTupleRow(
                        schemaname="public",
                        tablename="orders",
                        dead_tuple_percent=35.0,
                        dead_tuple_len=200 * 1024 * 1024,
                    ),
                ]
            )
        },
        "pg.db.bloat": {
            "mydb": BloatPerDb(
                rows=[
                    BloatRow(
                        schemaname="public",
                        tablename="orders",
                        table_bloat_ratio=2.5,
                        wastedbytes=512 * 1024 * 1024,
                    ),
                ]
            )
        },
    }
    findings = bloat_high(parsed)
    # Only one offender (deduped)
    assert "1 table" in findings[0].title


# ----------------------------------------------------------------------
# archiver_failing: existing rule, sanity check still works
# ----------------------------------------------------------------------


def test_archiver_failing_fires_on_recent_failure() -> None:
    a = PgArchiver(
        archived_count=10,
        failed_count=3,
        last_archived_wal="000000010000000000000005",
        last_archived_time="2026-04-01 12:00:00",
        last_failed_wal="000000010000000000000006",
        last_failed_time="2026-04-01 13:00:00",
    )
    findings = archiver_failing({"pg.archiver": a})
    assert len(findings) == 1
    assert findings[0].rule_id == "pg.wal.archiver_failures"


# ----------------------------------------------------------------------
# autovacuum_lagging
# ----------------------------------------------------------------------


def _av_table(
    name: str,
    *,
    schema: str = "public",
    reltuples: float = 0.0,
    n_live_tup: int = 0,
    n_dead_tup: int = 0,
    last_autovacuum_age_seconds: int | None = None,
    n_ins_since_vacuum: int | None = None,
) -> TableRow:
    return TableRow(
        schemaname=schema,
        tablename=name,
        reltuples=reltuples,
        n_live_tup=n_live_tup,
        n_dead_tup=n_dead_tup,
        n_ins_since_vacuum=n_ins_since_vacuum,
        last_autovacuum_age_seconds=last_autovacuum_age_seconds,
    )


def test_autovacuum_lagging_silent_when_no_data() -> None:
    assert autovacuum_lagging({}) == []
    assert autovacuum_lagging({"pg.db.tables": {}}) == []


def test_autovacuum_lagging_silent_on_pre_0_5_0_zip() -> None:
    # The age column wasn't collected; field is None even if
    # the table is way over the dead-tup threshold. The rule
    # silently skips so we don't over-fire on missing data.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "huge_dirty",
                        reltuples=10_000.0,
                        n_dead_tup=1_000_000,
                        last_autovacuum_age_seconds=None,
                    ),
                ]
            )
        }
    }
    assert autovacuum_lagging(parsed) == []


def test_autovacuum_lagging_silent_when_age_under_one_hour() -> None:
    # Recently autovacuumed: even if dead-tup is over the
    # threshold, autovacuum is doing its job.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "fresh",
                        reltuples=10_000.0,
                        n_dead_tup=1_000_000,
                        last_autovacuum_age_seconds=600,  # 10 min
                    ),
                ]
            )
        }
    }
    assert autovacuum_lagging(parsed) == []


def test_autovacuum_lagging_silent_when_under_eligibility() -> None:
    # > 1 h old but the dead-tup count is below the eligibility
    # threshold (defaults: 50 + 0.2 * reltuples = 50 + 200 = 250
    # for a 1000-row table). 100 dead is fine.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "small",
                        reltuples=1_000.0,
                        n_dead_tup=100,
                        last_autovacuum_age_seconds=7200,
                    ),
                ]
            )
        }
    }
    assert autovacuum_lagging(parsed) == []


def test_autovacuum_lagging_warns_when_eligible_and_overdue() -> None:
    # 1000-row table with default thresholds → eligibility
    # ≈ 50 + 0.2 × 1000 = 250 dead tuples. 1000 dead tuples
    # crosses that, AND last autovacuum was 2 hours ago.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "stuck",
                        reltuples=1_000.0,
                        n_dead_tup=1_000,
                        last_autovacuum_age_seconds=7200,
                    ),
                ]
            )
        }
    }
    findings = autovacuum_lagging(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].rule_id == "pg.health.autovacuum_lagging"
    assert "stuck" in findings[0].detail


def test_autovacuum_lagging_fires_on_insert_arm() -> None:
    # PG13+ insert-arm: when an append-only table accumulates
    # inserts past the insert threshold AND wasn't autovacuumed
    # recently, the insert-driven freeze pass is overdue.
    # Defaults: 1000 + 0.2 * 1000 = 1200 inserts.
    parsed = {
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "log_table",
                        reltuples=1_000.0,
                        n_dead_tup=0,
                        n_ins_since_vacuum=10_000,
                        last_autovacuum_age_seconds=7200,
                    ),
                ]
            )
        }
    }
    findings = autovacuum_lagging(parsed)
    assert len(findings) == 1


def test_autovacuum_lagging_uses_pg_settings_when_present() -> None:
    # If autovacuum is more aggressive than defaults (lower
    # threshold), more tables qualify as overdue.
    from radar_analyst.parse.pg_settings import PgSetting, PgSettings

    settings = PgSettings(
        all={
            "autovacuum_vacuum_threshold": PgSetting(
                name="autovacuum_vacuum_threshold",
                setting="10",
                unit="",
                category="Autovacuum",
                short_desc="",
            ),
            "autovacuum_vacuum_scale_factor": PgSetting(
                name="autovacuum_vacuum_scale_factor",
                setting="0.05",
                unit="",
                category="Autovacuum",
                short_desc="",
            ),
        }
    )
    # 1000-row table, 100 dead tup. Default eligibility = 250
    # (so wouldn't fire). Tuned eligibility = 10 + 0.05*1000 = 60.
    # 100 > 60 → fires.
    parsed = {
        "pg.settings": settings,
        "pg.db.tables": {
            "mydb": TablesPerDb(
                rows=[
                    _av_table(
                        "tuned",
                        reltuples=1_000.0,
                        n_dead_tup=100,
                        last_autovacuum_age_seconds=7200,
                    ),
                ]
            )
        },
    }
    findings = autovacuum_lagging(parsed)
    assert len(findings) == 1


# ----------------------------------------------------------------------
# mxid_wraparound_high
# ----------------------------------------------------------------------


def test_mxid_wraparound_silent_below_warn() -> None:
    parsed = {"pg.databases": [_db("mydb", mxid_age=499_999_999)]}
    assert mxid_wraparound_high(parsed) == []


def test_mxid_wraparound_warns_at_500m() -> None:
    """The same tiers as the TXID rule: the ceilings are identical."""
    parsed = {"pg.databases": [_db("mydb", mxid_age=500_000_000)]}
    out = mxid_wraparound_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.health.mxid_wraparound_high"


def test_mxid_wraparound_critical_at_failsafe() -> None:
    parsed = {"pg.databases": [_db("mydb", mxid_age=1_600_000_000)]}
    out = mxid_wraparound_high(parsed)
    assert out[0].severity == "critical"


def test_mxid_wraparound_honours_a_tuned_failsafe() -> None:
    """A host that raised the failsafe has not reached it yet."""
    parsed = {
        "pg.databases": [_db("mydb", mxid_age=1_600_000_000)],
        "pg.settings": _settings(
            {"vacuum_multixact_failsafe_age": "2000000000"}
        ),
    }
    assert mxid_wraparound_high(parsed)[0].severity == "warning"


def test_mxid_wraparound_reports_the_worst_database() -> None:
    parsed = {
        "pg.databases": [
            _db("quiet", mxid_age=1_000),
            _db("busy", mxid_age=900_000_000),
        ]
    }
    out = mxid_wraparound_high(parsed)
    assert "busy" in out[0].title


def test_mxid_wraparound_ignores_databases_without_the_column() -> None:
    """Older radars ship a narrower column set; None is not zero."""
    parsed = {"pg.databases": [_db("mydb", mxid_age=None)]}
    assert mxid_wraparound_high(parsed) == []


def test_mxid_wraparound_says_it_cannot_see_members_space() -> None:
    """Two counters exhaust independently; we only carry one."""
    parsed = {"pg.databases": [_db("mydb", mxid_age=600_000_000)]}
    assert "member" in mxid_wraparound_high(parsed)[0].detail


def test_mxid_wraparound_is_independent_of_txid() -> None:
    """A cluster can be fine on one counter and in trouble on the other."""
    parsed = {"pg.databases": [_db("mydb", age=1_000, mxid_age=900_000_000)]}
    assert txid_wraparound_high(parsed) == []
    assert len(mxid_wraparound_high(parsed)) == 1


# ----------------------------------------------------------------------
# autoanalyze_lagging
# ----------------------------------------------------------------------


def _tpd(rows: list[TableRow]) -> dict[str, TablesPerDb]:
    return {"mydb": TablesPerDb(rows=rows)}


def test_autoanalyze_silent_when_not_eligible() -> None:
    """Below the analyze threshold there is nothing to say."""
    parsed = {
        "pg.db.tables": _tpd(
            [
                _table(
                    name="t",
                    reltuples=1000.0,
                    mod_since_analyze=10,
                    autoanalyze_age=99_999,
                )
            ]
        )
    }
    assert autoanalyze_lagging(parsed) == []


def test_autoanalyze_fires_when_eligible_and_stale() -> None:
    """50 + 0.1 x 1000 = 150 modifications makes it eligible."""
    parsed = {
        "pg.db.tables": _tpd(
            [
                _table(
                    name="t",
                    reltuples=1000.0,
                    mod_since_analyze=500,
                    autoanalyze_age=7200,
                )
            ]
        )
    }
    out = autoanalyze_lagging(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.health.autoanalyze_lagging"
    assert "mydb/public.t" in out[0].detail


def test_autoanalyze_uses_its_own_scale_factor() -> None:
    """0.1, not the vacuum arm's 0.2: 150 fires where 250 would not."""
    row = _table(
        name="t",
        reltuples=1000.0,
        mod_since_analyze=200,
        autoanalyze_age=7200,
    )
    assert len(autoanalyze_lagging({"pg.db.tables": _tpd([row])})) == 1


def test_autoanalyze_respects_configured_settings() -> None:
    """A host that raised the scale factor is not overdue at 200."""
    settings = _settings({"autovacuum_analyze_scale_factor": "0.5"})
    row = _table(
        name="t",
        reltuples=1000.0,
        mod_since_analyze=200,
        autoanalyze_age=7200,
    )
    parsed = {"pg.db.tables": _tpd([row]), "pg.settings": settings}
    assert autoanalyze_lagging(parsed) == []


def test_autoanalyze_silent_when_recently_analysed() -> None:
    """Eligible but analysed ten minutes ago is autovacuum working."""
    row = _table(
        name="t",
        reltuples=1000.0,
        mod_since_analyze=5000,
        autoanalyze_age=600,
    )
    assert autoanalyze_lagging({"pg.db.tables": _tpd([row])}) == []


def test_autoanalyze_skips_tables_without_an_age() -> None:
    """Pre-0.5.0 zips carry no age; missing data must not over-fire."""
    row = _table(
        name="t",
        reltuples=1000.0,
        mod_since_analyze=5000,
        autoanalyze_age=None,
    )
    assert autoanalyze_lagging({"pg.db.tables": _tpd([row])}) == []


def test_autoanalyze_counts_every_offender() -> None:
    rows = [
        _table(
            name=f"t{i}",
            reltuples=1000.0,
            mod_since_analyze=5000,
            autoanalyze_age=7200,
        )
        for i in range(7)
    ]
    out = autoanalyze_lagging({"pg.db.tables": _tpd(rows)})
    assert "7 table(s)" in out[0].title
    assert "+2 more" in out[0].detail


def test_autoanalyze_silent_without_tables() -> None:
    assert autoanalyze_lagging({}) == []


# ----------------------------------------------------------------------
# unlogged_tables_present
# ----------------------------------------------------------------------


def test_unlogged_silent_without_replication() -> None:
    """On a single node an unlogged table means nothing worth saying."""
    parsed = {
        "pg.db.tables": _tpd([_table(name="cache", persistence="u")])
    }
    assert unlogged_tables_present(parsed) == []


def test_unlogged_reported_when_replication_is_configured() -> None:
    from radar_analyst.parse.pg_wal import (
        ReplicationSlot,
        ReplicationSlots,
    )

    slots = ReplicationSlots(
        all=[
            ReplicationSlot(
                slot_name="s1",
                slot_type="physical",
                database="",
                active=True,
                restart_lsn="0/1000000",
                wal_status="reserved",
            )
        ]
    )
    parsed = {
        "pg.db.tables": _tpd([_table(name="cache", persistence="u")]),
        "pg.replication_slots": slots,
    }
    out = unlogged_tables_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "info"
    assert out[0].rule_id == "pg.health.unlogged_tables"
    assert "cache" in out[0].detail


def test_unlogged_silent_when_every_table_is_permanent() -> None:
    from radar_analyst.parse.pg_wal import (
        ReplicationSlot,
        ReplicationSlots,
    )

    slots = ReplicationSlots(
        all=[
            ReplicationSlot(
                slot_name="s1",
                slot_type="physical",
                database="",
                active=True,
                restart_lsn="0/1000000",
                wal_status="reserved",
            )
        ]
    )
    parsed = {
        "pg.db.tables": _tpd([_table(name="t", persistence="p")]),
        "pg.replication_slots": slots,
    }
    assert unlogged_tables_present(parsed) == []
