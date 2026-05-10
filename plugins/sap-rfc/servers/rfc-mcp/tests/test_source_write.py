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


from tools.source_write import _resolve_transport, NoOpenTransport


def _fake_e070_response(rows: list[tuple[str, str, str]]) -> dict:
    """rows: list of (TRKORR, AS4DATE, AS4TIME)."""
    return {
        "FIELDS": [
            {"FIELDNAME": "TRKORR"},
            {"FIELDNAME": "AS4DATE"},
            {"FIELDNAME": "AS4TIME"},
        ],
        "DATA": [{"WA": f"{t}|{d}|{tm}"} for t, d, tm in rows],
    }


def test_resolve_transport_picks_most_recent():
    conn = MagicMock()
    conn.call.return_value = _fake_e070_response(
        [
            ("DEVK900100", "20260301", "120000"),
            ("DEVK900200", "20260510", "090000"),
            ("DEVK900150", "20260408", "150000"),
        ]
    )
    assert _resolve_transport(conn, "MHRYTSELIAK") == "DEVK900200"


def test_resolve_transport_raises_when_none():
    conn = MagicMock()
    conn.call.return_value = _fake_e070_response([])
    with pytest.raises(NoOpenTransport):
        _resolve_transport(conn, "MHRYTSELIAK")


def test_resolve_transport_uppercases_user():
    conn = MagicMock()
    conn.call.return_value = _fake_e070_response([("DEVK900200", "20260510", "090000")])
    _resolve_transport(conn, "mhrytseliak")
    _, kwargs = conn.call.call_args
    options_text = " ".join(o["TEXT"] for o in kwargs["OPTIONS"])
    assert "AS4USER EQ 'MHRYTSELIAK'" in options_text


from tools.source_write import _upload_program_impl


def test_upload_program_creates_executable(monkeypatch, tmp_path):
    src = tmp_path / "x.abap"
    src.write_text("REPORT zx.\nWRITE 'ok'.\n")

    conn = MagicMock()
    from pyrfc import ABAPApplicationError as _A

    calls = []

    def fake_call(fm_name, **kwargs):
        calls.append((fm_name, kwargs))
        if fm_name == "RPY_PROGRAM_READ":
            raise _A(message="Number:003 NOT_FOUND")
        if fm_name == "RFC_READ_TABLE" and kwargs.get("QUERY_TABLE") == "E070":
            return {
                "FIELDS": [{"FIELDNAME": "TRKORR"}, {"FIELDNAME": "AS4DATE"}, {"FIELDNAME": "AS4TIME"}],
                "DATA": [{"WA": "DEVK900200|20260510|090000"}],
            }
        return {}

    conn.call.side_effect = fake_call
    monkeypatch.setattr("tools.source_write.get_connection", lambda: conn)
    monkeypatch.setattr("tools.source_write._post_syntax_check", lambda name, kind: {"ok": True, "errors": [], "warnings": [], "infos": [], "subrc": 0})
    monkeypatch.setattr("tools.source_write.keyring.get_password", lambda *_: "MHRYTSELIAK")

    out = _upload_program_impl(
        name="ZNEW",
        source_file=str(src),
        transport=None,
        devclass="$TMP",
        description="Test",
        program_type="1",
    )
    assert out["action"] == "created"
    assert out["kind"] == "program"
    assert out["transport"] == ""  # $TMP skips TR
    assert out["lines_uploaded"] == 2
    assert out["syntax"]["ok"] is True
    fm_names = [c[0] for c in calls]
    assert "RPY_PROGRAM_INSERT" in fm_names


def test_upload_program_rejects_overlong_line(monkeypatch, tmp_path):
    src = tmp_path / "x.abap"
    src.write_text("REPORT zx.\n" + "X" * 300 + "\n")
    monkeypatch.setattr("tools.source_write.get_connection", lambda: MagicMock())
    monkeypatch.setattr("tools.source_write.keyring.get_password", lambda *_: "ME")
    out = _upload_program_impl(
        name="ZX", source_file=str(src), transport="DEVK900200",
        devclass="$TMP", description="T", program_type="1",
    )
    assert out["error"] == "LineTooLong"
    assert "2" in out["detail"]


def test_upload_program_create_requires_devclass(monkeypatch, tmp_path):
    src = tmp_path / "x.abap"
    src.write_text("REPORT zx.\n")
    from pyrfc import ABAPApplicationError as _A
    conn = MagicMock()
    conn.call.side_effect = _A(message="Number:003 NOT_FOUND")
    monkeypatch.setattr("tools.source_write.get_connection", lambda: conn)
    monkeypatch.setattr("tools.source_write.keyring.get_password", lambda *_: "ME")
    out = _upload_program_impl(
        name="ZNEW", source_file=str(src), transport="DEVK900200",
        devclass=None, description="T", program_type="1",
    )
    assert out["error"] == "MissingArgument"
    assert "devclass" in out["detail"].lower()


def test_upload_program_updates_existing(monkeypatch, tmp_path):
    src = tmp_path / "x.abap"
    src.write_text("REPORT zx.\nWRITE 'v2'.\n")

    conn = MagicMock()
    calls = []

    def fake_call(fm_name, **kwargs):
        calls.append((fm_name, kwargs))
        if fm_name == "RPY_PROGRAM_READ":
            return {"PROG_INF": {"PROG_TYPE": "1"}}
        if fm_name == "RFC_READ_TABLE" and kwargs.get("QUERY_TABLE") == "TRDIRT":
            return {
                "FIELDS": [{"FIELDNAME": "TEXT"}, {"FIELDNAME": "SPRSL"}],
                "DATA": [{"WA": "Existing Title|E"}],
            }
        return {}

    conn.call.side_effect = fake_call
    monkeypatch.setattr("tools.source_write.get_connection", lambda: conn)
    monkeypatch.setattr("tools.source_write._post_syntax_check", lambda *_: {"ok": True, "errors": [], "warnings": [], "infos": [], "subrc": 0})
    monkeypatch.setattr("tools.source_write.keyring.get_password", lambda *_: "ME")

    out = _upload_program_impl(
        name="ZEXIST", source_file=str(src), transport="DEVK900200",
        devclass=None, description=None, program_type="1",
    )
    assert out["action"] == "updated"
    fm_names = [c[0] for c in calls]
    assert "RPY_INCLUDE_UPDATE" in fm_names
    update_kwargs = next(c[1] for c in calls if c[0] == "RPY_INCLUDE_UPDATE")
    # Existing title is carried forward (fetched from TRDIRT).
    assert update_kwargs["TITLE_STRING"] == "Existing Title"
    assert update_kwargs["INCLUDE_NAME"] == "ZEXIST"
    assert update_kwargs["TRANSPORT_NUMBER"] == "DEVK900200"
