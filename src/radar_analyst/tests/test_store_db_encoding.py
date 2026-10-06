"""Refusing a state database whose text comes back as bytes.

Under the SQL_ASCII encoding psycopg hands back ``bytes`` for text
columns rather than ``str``. Nothing raises at connection time: the
damage shows up later as a job whose ``state`` never equals "done",
a progress stream that waits forever for a job that already
finished, and a 500 from the first rule that calls a string method.
Checking once at startup turns all of that into one clear message.
"""

from __future__ import annotations

import logging

import pytest

from radar_analyst.store.db import check_server_encoding


def test_utf8_is_accepted() -> None:
    check_server_encoding("UTF8")


def test_bytes_are_refused_with_the_fix_in_the_message() -> None:
    """SQL_ASCII is what makes psycopg return bytes."""
    with pytest.raises(RuntimeError) as excinfo:
        check_server_encoding(b"SQL_ASCII")

    message = str(excinfo.value)
    assert "SQL_ASCII" in message
    assert "UTF8" in message


def test_the_message_names_the_setting_that_fixes_it() -> None:
    """Whoever hits this needs to know what to change."""
    with pytest.raises(RuntimeError) as excinfo:
        check_server_encoding(b"SQL_ASCII")

    assert "POSTGRES_INITDB_ARGS" in str(excinfo.value)


def test_a_decodable_non_utf8_encoding_warns_but_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LATIN1 still decodes, so it is a warning and not a refusal."""
    with caplog.at_level(logging.WARNING):
        check_server_encoding("LATIN1")

    assert any(
        "LATIN1" in record.message for record in caplog.records
    )


def test_sql_ascii_reported_as_text_is_still_refused() -> None:
    """The encoding is refused by name, not only by what it returns.

    A driver could decode this one setting and still hand back bytes
    for every other text column, so the name alone is enough.
    """
    with pytest.raises(RuntimeError):
        check_server_encoding("SQL_ASCII")
