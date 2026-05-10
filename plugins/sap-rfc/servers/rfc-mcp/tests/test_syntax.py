from tools.syntax import _parse_messages


def test_parse_messages_normalizes_keys():
    raw = [
        {
            "STMT_CNT": 0,
            "INCNAME": "ZTEST",
            "LINE": 5,
            "COL": 12,
            "SPRAS": "E",
            "KEYWORD": "DATA",
            "MSGNUMBER": "0042",
            "MESSAGE": "Field XYZ unknown.",
            "KIND": "E",
        }
    ]
    out = _parse_messages(raw)
    assert out == [
        {
            "include": "ZTEST",
            "line": 5,
            "col": 12,
            "keyword": "DATA",
            "msg_no": "0042",
            "message": "Field XYZ unknown.",
            "kind": "E",
        }
    ]


def test_parse_messages_handles_missing_fields():
    raw = [{"INCNAME": "ZX", "LINE": 1, "MESSAGE": "boom"}]
    out = _parse_messages(raw)
    assert out[0]["include"] == "ZX"
    assert out[0]["line"] == 1
    assert out[0]["col"] == 0
    assert out[0]["keyword"] == ""
    assert out[0]["msg_no"] == ""
    assert out[0]["message"] == "boom"
    assert out[0]["kind"] == ""


def test_parse_messages_empty_table():
    assert _parse_messages([]) == []


from unittest.mock import MagicMock, patch

from tools.syntax import _syntax_check_impl


def _fake_conn(errors=None, warnings=None, infos=None, subrc=0):
    conn = MagicMock()
    conn.call.return_value = {
        "P_ERRORS": errors or [],
        "P_WARNINGS": warnings or [],
        "P_INFOS": infos or [],
        "P_LONGTEXT": [],
        "P_COMMENTS": b"",
        "P_SUBRC": subrc,
    }
    return conn


def test_syntax_check_clean_program(monkeypatch):
    conn = _fake_conn()
    monkeypatch.setattr("tools.syntax.get_connection", lambda: conn)
    monkeypatch.setattr("tools.syntax.keyring.get_password", lambda *_: "EN")

    out = _syntax_check_impl("ZGOOD", "program")

    assert out == {"ok": True, "errors": [], "warnings": [], "infos": [], "subrc": 0}
    conn.call.assert_called_once()
    args, kwargs = conn.call.call_args
    assert args[0] == "RS_ABAP_SYNTAX_CHECK_E"
    assert kwargs["P_PROGRAM"] == "ZGOOD"
    assert kwargs["P_LANGU"] == "E"


def test_syntax_check_reports_errors(monkeypatch):
    conn = _fake_conn(
        errors=[{"INCNAME": "ZBAD", "LINE": 7, "COL": 1, "MESSAGE": "Boom", "KIND": "E"}],
        subrc=8,
    )
    monkeypatch.setattr("tools.syntax.get_connection", lambda: conn)
    monkeypatch.setattr("tools.syntax.keyring.get_password", lambda *_: "EN")

    out = _syntax_check_impl("ZBAD", "program")

    assert out["ok"] is False
    assert out["errors"][0]["include"] == "ZBAD"
    assert out["errors"][0]["line"] == 7
    assert out["subrc"] == 8


def test_syntax_check_uppercases_name(monkeypatch):
    conn = _fake_conn()
    monkeypatch.setattr("tools.syntax.get_connection", lambda: conn)
    monkeypatch.setattr("tools.syntax.keyring.get_password", lambda *_: "EN")

    _syntax_check_impl("zlower", "program")

    _, kwargs = conn.call.call_args
    assert kwargs["P_PROGRAM"] == "ZLOWER"
