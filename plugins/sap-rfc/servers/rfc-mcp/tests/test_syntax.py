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
