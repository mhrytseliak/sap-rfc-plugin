import pytest

from tools.source_write import _validate_lines, _to_source_extended


def test_validate_lines_accepts_short_lines():
    lines = ["REPORT zfoo.", "WRITE / 'hello'."]
    assert _validate_lines(lines) is None


def test_validate_lines_rejects_overlong():
    bad = "X" * 256
    err = _validate_lines(["ok", bad, "also ok"])
    assert err == [2]


def test_validate_lines_reports_all_violations():
    bad = "X" * 256
    assert _validate_lines([bad, "ok", bad]) == [1, 3]


def test_to_source_extended_wraps_each_line():
    out = _to_source_extended(["a", "bb", ""])
    assert out == [{"LINE": "a"}, {"LINE": "bb"}, {"LINE": ""}]


from unittest.mock import MagicMock

from tools.source_write import _decide_action


def _not_found_error():
    """Build an ABAPApplicationError that imitates pyrfc's NOT_FOUND raise."""
    from pyrfc import ABAPApplicationError
    return ABAPApplicationError(
        message="Number:003 NOT_FOUND",
    )


def test_decide_action_create_program_for_executable():
    conn = MagicMock()
    conn.call.side_effect = _not_found_error()
    action, info = _decide_action(conn, "ZNEW", "1")
    assert action == "create_program"
    assert info["program_type"] == "1"


def test_decide_action_create_include_for_kind_i():
    conn = MagicMock()
    conn.call.side_effect = _not_found_error()
    action, info = _decide_action(conn, "ZNEW_I", "I")
    assert action == "create_include"


def test_decide_action_update_when_exists():
    conn = MagicMock()
    conn.call.return_value = {
        "PROG_INF": {"PROG_TYPE": "1"},
    }
    action, info = _decide_action(conn, "ZEXIST", "1")
    assert action == "update"
    assert info["program_type"] == "1"
