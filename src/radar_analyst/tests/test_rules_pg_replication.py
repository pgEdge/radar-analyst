"""Tests for rules/pg_replication.py: streaming replicas,
WAL receiver, subscriptions."""

from __future__ import annotations

from radar_analyst.parse.pg_wal import (
    ReplicationReplica,
    ReplicationSlot,
    ReplicationSlots,
    Subscription,
)
from radar_analyst.rules.pg_replication import (
    inactive_slot_present,
    lag_bytes_high,
    replica_disconnected,
    replica_lag_high,
    replica_not_streaming,
    subscription_not_running,
)


def _replica(
    state: str = "streaming",
    replay_lag_s: float | None = None,
    application_name: str = "standby1",
    sync_state: str = "async",
    sent_lsn: str = "",
    replay_lsn: str = "",
) -> ReplicationReplica:
    return ReplicationReplica(
        application_name=application_name,
        client_addr="10.0.0.2",
        state=state,
        sync_state=sync_state,
        replay_lag_s=replay_lag_s,
        sent_lsn=sent_lsn,
        replay_lsn=replay_lsn,
    )


def _physical_slot(
    slot_name: str,
    active: bool = False,
) -> ReplicationSlot:
    return ReplicationSlot(
        slot_name=slot_name,
        slot_type="physical",
        database="",
        active=active,
        restart_lsn="",
        wal_status="reserved",
    )


def _logical_slot(slot_name: str) -> ReplicationSlot:
    return ReplicationSlot(
        slot_name=slot_name,
        slot_type="logical",
        database="mydb",
        active=False,
        restart_lsn="",
        wal_status="reserved",
    )


# ---------------------------------------------------------------
# replica_not_streaming
# ---------------------------------------------------------------

def test_replica_not_streaming_warns_on_stopped() -> None:
    parsed = {
        "pg.replication": [
            _replica(state="stopped"),
        ]
    }
    out = replica_not_streaming(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.repl.replica_not_streaming"


def test_replica_not_streaming_silent_on_streaming() -> None:
    parsed = {"pg.replication": [_replica(state="streaming")]}
    assert replica_not_streaming(parsed) == []


def test_replica_not_streaming_silent_on_catchup() -> None:
    # catchup is a normal transient state: not a warning.
    parsed = {"pg.replication": [_replica(state="catchup")]}
    assert replica_not_streaming(parsed) == []


def test_replica_not_streaming_silent_on_empty_list() -> None:
    assert replica_not_streaming({"pg.replication": []}) == []


def test_replica_not_streaming_silent_when_no_data() -> None:
    assert replica_not_streaming({}) == []


def test_replica_not_streaming_warns_only_problem_replicas() -> None:
    parsed = {
        "pg.replication": [
            _replica(state="streaming", application_name="ok"),
            _replica(state="startup", application_name="bad"),
        ]
    }
    out = replica_not_streaming(parsed)
    assert len(out) == 1
    assert "bad" in out[0].title or "bad" in out[0].detail


# ---------------------------------------------------------------
# replica_lag_high
# ---------------------------------------------------------------

def test_replica_lag_warns_at_5_minutes() -> None:
    parsed = {
        "pg.replication": [
            _replica(replay_lag_s=5 * 60.0)  # exactly 5 min
        ]
    }
    out = replica_lag_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.repl.replica_lag"


def test_replica_lag_critical_at_30_minutes() -> None:
    parsed = {
        "pg.replication": [
            _replica(replay_lag_s=30 * 60.0)
        ]
    }
    out = replica_lag_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_replica_lag_silent_below_threshold() -> None:
    parsed = {
        "pg.replication": [
            _replica(replay_lag_s=4 * 60.0)  # 4 min < 5 min
        ]
    }
    assert replica_lag_high(parsed) == []


def test_replica_lag_silent_when_lag_is_none() -> None:
    parsed = {"pg.replication": [_replica(replay_lag_s=None)]}
    assert replica_lag_high(parsed) == []


def test_replica_lag_silent_when_no_data() -> None:
    assert replica_lag_high({}) == []


def test_replica_lag_reports_worst_replica() -> None:
    # When multiple replicas lag, we get one finding per lagging
    # replica so the DBA can see all of them.
    parsed = {
        "pg.replication": [
            _replica(
                replay_lag_s=10 * 60.0,
                application_name="slow1",
            ),
            _replica(
                replay_lag_s=2 * 60.0,
                application_name="ok",
            ),
            _replica(
                replay_lag_s=35 * 60.0,
                application_name="slow2",
            ),
        ]
    }
    out = replica_lag_high(parsed)
    assert len(out) == 2  # slow1 + slow2, not ok
    severities = {f.severity for f in out}
    assert "critical" in severities  # slow2 triggers critical


# ---------------------------------------------------------------
# subscription_not_running
# ---------------------------------------------------------------

def _sub(
    subname: str,
    pid: int | None,
) -> Subscription:
    return Subscription(subname=subname, pid=pid)


def test_subscription_not_running_warns_when_no_pid() -> None:
    parsed = {
        "pg.subscriptions": [
            _sub("stuck_sub", pid=None),
        ]
    }
    out = subscription_not_running(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.repl.subscription_not_running"
    assert "stuck_sub" in out[0].title or (
        "stuck_sub" in out[0].detail
    )


def test_subscription_not_running_silent_when_pid_present() -> None:
    parsed = {"pg.subscriptions": [_sub("mysub", pid=9999)]}
    assert subscription_not_running(parsed) == []


def test_subscription_not_running_silent_on_empty_list() -> None:
    assert (
        subscription_not_running({"pg.subscriptions": []}) == []
    )


def test_subscription_not_running_silent_when_no_data() -> None:
    assert subscription_not_running({}) == []


# ---------------------------------------------------------------
# lag_bytes_high
# ---------------------------------------------------------------

def test_lag_bytes_warns_at_100mb() -> None:
    # 0x6400000 = 100 * 1024 * 1024 exactly
    parsed = {
        "pg.replication": [
            _replica(
                sent_lsn="0/06400000",
                replay_lsn="0/00000000",
            )
        ]
    }
    out = lag_bytes_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.repl.lag_bytes"


def test_lag_bytes_critical_at_over_1gb() -> None:
    # 0x40000001 = 1073741825 > 1 GiB
    parsed = {
        "pg.replication": [
            _replica(
                sent_lsn="0/40000001",
                replay_lsn="0/00000000",
            )
        ]
    }
    out = lag_bytes_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_lag_bytes_silent_below_threshold() -> None:
    # 0x5FFFFFF = 100663295 < 100 MiB
    parsed = {
        "pg.replication": [
            _replica(
                sent_lsn="0/05FFFFFF",
                replay_lsn="0/00000000",
            )
        ]
    }
    assert lag_bytes_high(parsed) == []


def test_lag_bytes_silent_when_no_lsn_fields() -> None:
    parsed = {"pg.replication": [_replica()]}
    assert lag_bytes_high(parsed) == []


def test_lag_bytes_silent_when_no_data() -> None:
    assert lag_bytes_high({}) == []


def test_lag_bytes_one_finding_per_lagging_replica() -> None:
    parsed = {
        "pg.replication": [
            _replica(
                sent_lsn="0/40000001",
                replay_lsn="0/00000000",
                application_name="slow1",
            ),
            _replica(
                sent_lsn="0/01000000",
                replay_lsn="0/00000000",
                application_name="ok",
            ),
        ]
    }
    out = lag_bytes_high(parsed)
    assert len(out) == 1
    assert "slow1" in out[0].title or "slow1" in out[0].detail


# ---------------------------------------------------------------
# replica_disconnected
# ---------------------------------------------------------------

def test_replica_disconnected_fires_when_physical_slot_has_no_replica(
) -> None:
    slots = ReplicationSlots(all=[_physical_slot("standby1")])
    parsed = {
        "pg.replication_slots": slots,
        "pg.replication": [],
    }
    out = replica_disconnected(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.repl.replica_disconnected"
    assert "standby1" in out[0].title or "standby1" in out[0].detail


def test_replica_disconnected_silent_when_slot_matches_replica(
) -> None:
    slots = ReplicationSlots(all=[_physical_slot("standby1")])
    parsed = {
        "pg.replication_slots": slots,
        "pg.replication": [_replica(application_name="standby1")],
    }
    assert replica_disconnected(parsed) == []


def test_replica_disconnected_ignores_logical_slots() -> None:
    slots = ReplicationSlots(all=[_logical_slot("logslot")])
    parsed = {
        "pg.replication_slots": slots,
        "pg.replication": [],
    }
    assert replica_disconnected(parsed) == []


def test_replica_disconnected_silent_when_no_physical_slots() -> None:
    parsed = {
        "pg.replication_slots": ReplicationSlots(all=[]),
        "pg.replication": [],
    }
    assert replica_disconnected(parsed) == []


def test_replica_disconnected_silent_when_no_data() -> None:
    assert replica_disconnected({}) == []


def test_replica_disconnected_only_flags_missing_replicas() -> None:
    slots = ReplicationSlots(
        all=[
            _physical_slot("connected"),
            _physical_slot("gone"),
        ]
    )
    parsed = {
        "pg.replication_slots": slots,
        "pg.replication": [_replica(application_name="connected")],
    }
    out = replica_disconnected(parsed)
    assert len(out) == 1
    assert "gone" in out[0].title or "gone" in out[0].detail


# ---------------------------------------------------------------
# Existing slot rule still works (regression guard)
# ---------------------------------------------------------------

def test_inactive_slot_still_fires() -> None:
    slots = ReplicationSlots(
        all=[
            ReplicationSlot(
                slot_name="dead_slot",
                slot_type="physical",
                database="",
                active=False,
                restart_lsn="",
                wal_status="extended",
            )
        ]
    )
    parsed = {"pg.replication_slots": slots}
    out = inactive_slot_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


# ----------------------------------------------------------------------
# logical_replication_spilling
# ----------------------------------------------------------------------


def test_logical_spilling_silent_when_no_data() -> None:
    from radar_analyst.rules.pg_replication import (
        logical_replication_spilling,
    )

    assert logical_replication_spilling({}) == []


def test_logical_spilling_silent_when_quiet() -> None:
    from radar_analyst.parse.pg_stat_replication_slots import (
        SlotStat,
        StatReplicationSlots,
    )
    from radar_analyst.rules.pg_replication import (
        logical_replication_spilling,
    )

    parsed = {
        "pg.stat_replication_slots": StatReplicationSlots(
            rows=[
                SlotStat(
                    slot_name="quiet",
                    spill_count=0,
                    spill_bytes=0,
                ),
            ]
        )
    }
    assert logical_replication_spilling(parsed) == []


def test_logical_spilling_warns_when_spilling() -> None:
    from radar_analyst.parse.pg_stat_replication_slots import (
        SlotStat,
        StatReplicationSlots,
    )
    from radar_analyst.rules.pg_replication import (
        logical_replication_spilling,
    )

    parsed = {
        "pg.stat_replication_slots": StatReplicationSlots(
            rows=[
                SlotStat(
                    slot_name="noisy",
                    spill_txns=10,
                    spill_count=20,
                    spill_bytes=104857600,
                ),
                SlotStat(
                    slot_name="quiet",
                ),
            ]
        )
    }
    findings = logical_replication_spilling(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.repl.logical_spilling"
    assert f.severity == "warning"
    assert "noisy" in f.detail
