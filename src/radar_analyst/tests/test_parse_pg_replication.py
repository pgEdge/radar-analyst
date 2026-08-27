"""Tests for the replication parsers in pg_wal.py.

Streaming replicas, the WAL receiver, and subscriptions.
"""

from __future__ import annotations

from radar_analyst.parse.pg_wal import (
    ReplicationOrigin,
    ReplicationReplica,
    Subscription,
    WalPosition,
    WalReceiver,
    lsn_to_int,
    parse_replication,
    parse_replication_origins,
    parse_subscriptions,
    parse_wal_position,
    parse_wal_receiver,
)


# ---------------------------------------------------------------
# parse_replication (pg_stat_replication)
# ---------------------------------------------------------------

_REPLICATION_TSV = (
    "pid\tusename\tapplication_name\tclient_addr\tstate\t"
    "sent_lsn\twrite_lsn\tflush_lsn\treplay_lsn\t"
    "write_lag\tflush_lag\treplay_lag\tsync_state\n"
    "12345\treplicator\tstandby1\t10.0.0.2\tstreaming\t"
    "0/3000000\t0/3000000\t0/2FF0000\t0/2FE0000\t"
    "00:00:00.1\t00:00:00.2\t00:00:05.3\tasync\n"
    "12346\treplicator\tstandby2\t10.0.0.3\tcatchup\t"
    "0/3000000\t0/2FF0000\t0/2FE0000\t0/2FD0000\t"
    "\t\t00:02:10\tasync\n"
)


def test_parse_replication_returns_replicas() -> None:
    result = parse_replication(_REPLICATION_TSV.encode())
    assert result is not None
    assert len(result) == 2


def test_parse_replication_first_replica_fields() -> None:
    result = parse_replication(_REPLICATION_TSV.encode())
    assert result is not None
    r = result[0]
    assert isinstance(r, ReplicationReplica)
    assert r.application_name == "standby1"
    assert r.client_addr == "10.0.0.2"
    assert r.state == "streaming"
    assert r.sync_state == "async"
    # replay_lag "00:00:05.3" → 5.3 seconds
    assert r.replay_lag_s is not None
    assert abs(r.replay_lag_s - 5.3) < 0.01


def test_parse_replication_second_replica_catchup_state() -> None:
    result = parse_replication(_REPLICATION_TSV.encode())
    assert result is not None
    r = result[1]
    assert r.state == "catchup"
    # "00:02:10" → 130 seconds
    assert r.replay_lag_s is not None
    assert abs(r.replay_lag_s - 130.0) < 0.01


def test_parse_replication_empty_returns_empty_list() -> None:
    tsv = (
        "pid\tusename\tapplication_name\tclient_addr\tstate\t"
        "sent_lsn\twrite_lsn\tflush_lsn\treplay_lsn\t"
        "write_lag\tflush_lag\treplay_lag\tsync_state\n"
    )
    result = parse_replication(tsv.encode())
    assert result == []


def test_parse_replication_totally_empty_returns_none() -> None:
    assert parse_replication(b"") is None


def test_parse_replication_null_lag_is_none() -> None:
    # NULL replay_lag (empty field) → None
    tsv = (
        "pid\tusename\tapplication_name\tclient_addr\tstate\t"
        "sent_lsn\twrite_lsn\tflush_lsn\treplay_lsn\t"
        "write_lag\tflush_lag\treplay_lag\tsync_state\n"
        "99\treplicator\tstandby3\t10.0.0.4\tstreaming\t"
        "0/1\t0/1\t0/1\t0/1\t\t\t\tasync\n"
    )
    result = parse_replication(tsv.encode())
    assert result is not None
    assert result[0].replay_lag_s is None


# ---------------------------------------------------------------
# parse_wal_receiver (pg_stat_wal_receiver on a standby)
# ---------------------------------------------------------------

_WAL_RECEIVER_TSV = (
    "pid\tstatus\treceive_start_lsn\treceive_start_tli\t"
    "written_lsn\tflushed_lsn\treceived_tli\t"
    "last_msg_send_time\tlast_msg_receipt_time\t"
    "latest_end_lsn\tlatest_end_time\tslot_name\t"
    "sender_host\tsender_port\tconninfo\n"
    "5678\tstreaming\t0/1000000\t1\t"
    "0/3000000\t0/3000000\t1\t"
    "2024-01-01 12:00:00+00\t2024-01-01 12:00:00.5+00\t"
    "0/3000000\t2024-01-01 12:00:00+00\tmy_slot\t"
    "10.0.0.1\t5432\thost=10.0.0.1 port=5432\n"
)


def test_parse_wal_receiver_fields() -> None:
    result = parse_wal_receiver(_WAL_RECEIVER_TSV.encode())
    assert result is not None
    assert isinstance(result, WalReceiver)
    assert result.status == "streaming"
    assert result.sender_host == "10.0.0.1"
    assert result.sender_port == 5432
    assert result.slot_name == "my_slot"


def test_parse_wal_receiver_empty_returns_none() -> None:
    tsv = (
        "pid\tstatus\treceive_start_lsn\treceive_start_tli\t"
        "written_lsn\tflushed_lsn\treceived_tli\t"
        "last_msg_send_time\tlast_msg_receipt_time\t"
        "latest_end_lsn\tlatest_end_time\tslot_name\t"
        "sender_host\tsender_port\tconninfo\n"
    )
    assert parse_wal_receiver(tsv.encode()) is None


def test_parse_wal_receiver_totally_empty_returns_none() -> None:
    assert parse_wal_receiver(b"") is None


# ---------------------------------------------------------------
# parse_subscriptions (pg_stat_subscription)
# ---------------------------------------------------------------

_SUBSCRIPTIONS_TSV = (
    "subid\tsubname\tpid\trelid\t"
    "received_lsn\tlast_msg_send_time\tlast_msg_receipt_time\t"
    "latest_end_lsn\tlatest_end_time\n"
    "16384\tmysub\t9999\t\t"
    "0/2000000\t2024-01-01 12:00:00+00\t2024-01-01 12:00:01+00\t"
    "0/2000000\t2024-01-01 12:00:00+00\n"
    "16385\tstuck_sub\t\t\t"
    "0/1000000\t2024-01-01 10:00:00+00\t2024-01-01 10:00:01+00\t"
    "0/1800000\t2024-01-01 10:00:00+00\n"
)


def test_parse_subscriptions_returns_subscriptions() -> None:
    result = parse_subscriptions(_SUBSCRIPTIONS_TSV.encode())
    assert result is not None
    assert len(result) == 2


def test_parse_subscriptions_running_sub_has_pid() -> None:
    result = parse_subscriptions(_SUBSCRIPTIONS_TSV.encode())
    assert result is not None
    running = result[0]
    assert isinstance(running, Subscription)
    assert running.subname == "mysub"
    assert running.pid is not None


def test_parse_subscriptions_stuck_sub_has_no_pid() -> None:
    result = parse_subscriptions(_SUBSCRIPTIONS_TSV.encode())
    assert result is not None
    stuck = result[1]
    assert stuck.subname == "stuck_sub"
    assert stuck.pid is None


def test_parse_subscriptions_empty_returns_empty_list() -> None:
    tsv = (
        "subid\tsubname\tpid\trelid\t"
        "received_lsn\tlast_msg_send_time\tlast_msg_receipt_time\t"
        "latest_end_lsn\tlatest_end_time\n"
    )
    result = parse_subscriptions(tsv.encode())
    assert result == []


def test_parse_subscriptions_totally_empty_returns_none() -> None:
    assert parse_subscriptions(b"") is None


# ---------------------------------------------------------------
# lsn_to_int helper
# ---------------------------------------------------------------

def test_lsn_to_int_parses_segment_and_offset() -> None:
    # 1/4E58EBC8 → (0x1 << 32) | 0x4E58EBC8
    assert lsn_to_int("1/4E58EBC8") == (1 << 32) | 0x4E58EBC8


def test_lsn_to_int_zero() -> None:
    assert lsn_to_int("0/00000000") == 0


def test_lsn_to_int_empty_returns_none() -> None:
    assert lsn_to_int("") is None


def test_lsn_to_int_invalid_returns_none() -> None:
    assert lsn_to_int("not/valid") is None


def test_lsn_to_int_single_part_returns_none() -> None:
    assert lsn_to_int("0") is None


# ---------------------------------------------------------------
# ReplicationReplica.lsn_lag_bytes property
# ---------------------------------------------------------------

def test_lsn_lag_bytes_exactly_100mb() -> None:
    # 0x6400000 = 100 * 1024 * 1024
    r = ReplicationReplica(
        application_name="s1",
        client_addr="10.0.0.1",
        state="streaming",
        sync_state="async",
        replay_lag_s=None,
        sent_lsn="0/06400000",
        replay_lsn="0/00000000",
    )
    assert r.lsn_lag_bytes == 100 * 1024 * 1024


def test_lsn_lag_bytes_none_when_no_lsn() -> None:
    r = ReplicationReplica(
        application_name="s1",
        client_addr="10.0.0.1",
        state="streaming",
        sync_state="async",
        replay_lag_s=None,
    )
    assert r.lsn_lag_bytes is None


def test_lsn_lag_bytes_none_when_replay_ahead_of_sent() -> None:
    # Replay LSN > sent LSN (shouldn't happen in practice but
    # must not return a negative value).
    r = ReplicationReplica(
        application_name="s1",
        client_addr="10.0.0.1",
        state="streaming",
        sync_state="async",
        replay_lag_s=None,
        sent_lsn="0/1000000",
        replay_lsn="0/2000000",
    )
    assert r.lsn_lag_bytes is None


def test_parse_replication_captures_lsn_fields() -> None:
    result = parse_replication(_REPLICATION_TSV.encode())
    assert result is not None
    r = result[0]
    assert r.sent_lsn == "0/3000000"
    assert r.replay_lsn == "0/2FE0000"


# ---------------------------------------------------------------
# parse_wal_position
# ---------------------------------------------------------------

_WAL_POSITION_PRIMARY_TSV = (
    "current_wal_lsn\tcurrent_wal_insert_lsn\t"
    "current_wal_flush_lsn\tis_in_recovery\t"
    "last_wal_receive_lsn\tlast_wal_replay_lsn\t"
    "last_xact_replay_timestamp\n"
    "1/4E58EBC8\t1/4E58EBC8\t1/4E58EBC8\tfalse\t\t\t\n"
)

_WAL_POSITION_STANDBY_TSV = (
    "current_wal_lsn\tcurrent_wal_insert_lsn\t"
    "current_wal_flush_lsn\tis_in_recovery\t"
    "last_wal_receive_lsn\tlast_wal_replay_lsn\t"
    "last_xact_replay_timestamp\n"
    "\t\t\ttrue\t"
    "0/3000000\t0/2FE0000\t2024-01-01 12:00:00+00\n"
)


def test_parse_wal_position_primary() -> None:
    result = parse_wal_position(_WAL_POSITION_PRIMARY_TSV.encode())
    assert result is not None
    assert isinstance(result, WalPosition)
    assert result.is_in_recovery is False
    assert result.current_wal_lsn == "1/4E58EBC8"
    assert result.last_wal_receive_lsn == ""


def test_parse_wal_position_standby() -> None:
    result = parse_wal_position(_WAL_POSITION_STANDBY_TSV.encode())
    assert result is not None
    assert result.is_in_recovery is True
    assert result.last_wal_receive_lsn == "0/3000000"
    assert result.last_wal_replay_lsn == "0/2FE0000"
    assert result.last_xact_replay_timestamp == "2024-01-01 12:00:00+00"


def test_parse_wal_position_empty_returns_none() -> None:
    tsv = (
        "current_wal_lsn\tcurrent_wal_insert_lsn\t"
        "current_wal_flush_lsn\tis_in_recovery\t"
        "last_wal_receive_lsn\tlast_wal_replay_lsn\t"
        "last_xact_replay_timestamp\n"
    )
    assert parse_wal_position(tsv.encode()) is None


def test_parse_wal_position_totally_empty_returns_none() -> None:
    assert parse_wal_position(b"") is None


# ---------------------------------------------------------------
# parse_replication_origins
# ---------------------------------------------------------------

_REPLICATION_ORIGINS_TSV = (
    "local_id\texternal_id\tremote_lsn\tlocal_lsn\n"
    "1\tmysub\t0/3000000\t0/2FE0000\n"
)


def test_parse_replication_origins_populated() -> None:
    result = parse_replication_origins(
        _REPLICATION_ORIGINS_TSV.encode()
    )
    assert result is not None
    assert len(result) == 1
    o = result[0]
    assert isinstance(o, ReplicationOrigin)
    assert o.local_id == "1"
    assert o.external_id == "mysub"
    assert o.remote_lsn == "0/3000000"
    assert o.local_lsn == "0/2FE0000"


def test_parse_replication_origins_header_only_returns_empty() -> None:
    tsv = "local_id\texternal_id\tremote_lsn\tlocal_lsn\n"
    result = parse_replication_origins(tsv.encode())
    assert result == []


def test_parse_replication_origins_totally_empty_returns_none() -> None:
    assert parse_replication_origins(b"") is None
