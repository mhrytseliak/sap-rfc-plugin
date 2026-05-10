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
