import pytest

from tools.test_run import _build_free_selinfo


def test_build_free_selinfo_parameters_only():
    out = _build_free_selinfo({"P_DATE": "20260510", "P_FLAG": "X"}, None)
    assert {"SELNAME": "P_DATE", "KIND": "P", "SIGN": "I", "OPTION": "EQ", "LOW": "20260510", "HIGH": ""} in out
    assert {"SELNAME": "P_FLAG", "KIND": "P", "SIGN": "I", "OPTION": "EQ", "LOW": "X", "HIGH": ""} in out
    assert len(out) == 2


def test_build_free_selinfo_select_options_only():
    out = _build_free_selinfo(
        None,
        [
            {"name": "SO_BUKRS", "sign": "I", "option": "EQ", "low": "1000", "high": ""},
            {"name": "SO_BUKRS", "sign": "I", "option": "BT", "low": "2000", "high": "2999"},
            {"name": "SO_DATE", "sign": "E", "option": "EQ", "low": "20260101", "high": ""},
        ],
    )
    bukrs = [r for r in out if r["SELNAME"] == "SO_BUKRS"]
    assert len(bukrs) == 2
    assert bukrs[1]["OPTION"] == "BT"
    assert bukrs[1]["HIGH"] == "2999"
    assert all(r["KIND"] == "S" for r in out)


def test_build_free_selinfo_uppercases_names():
    out = _build_free_selinfo({"p_x": "v"}, [{"name": "so_y", "sign": "I", "option": "EQ", "low": "z", "high": ""}])
    names = [r["SELNAME"] for r in out]
    assert "P_X" in names
    assert "SO_Y" in names


def test_build_free_selinfo_empty_inputs():
    assert _build_free_selinfo(None, None) == []
    assert _build_free_selinfo({}, []) == []


from tools.test_run import _parse_joblog, _parse_syslog_for_dump, _detect_dump_in_joblog


def test_parse_joblog_normalizes_rows():
    raw = [
        {
            "LOG_DATE": "20260510",
            "LOG_TIME": "120015",
            "MESSAGE_ID": "00",
            "MESSAGE_NUMBER": "671",
            "MESSAGE_TYPE": "E",
            "MESSAGE": "Job cancelled after system exception ERROR_MESSAGE",
        },
        {
            "LOG_DATE": "20260510",
            "LOG_TIME": "120014",
            "MESSAGE_ID": "BT",
            "MESSAGE_NUMBER": "043",
            "MESSAGE_TYPE": "S",
            "MESSAGE": "Job started",
        },
    ]
    out = _parse_joblog(raw)
    assert out[0]["msg_class"] == "00"
    assert out[0]["msg_no"] == "671"
    assert out[0]["msg_type"] == "E"
    assert out[0]["timestamp"] == "20260510120015"


def test_detect_dump_in_joblog_finds_error_message():
    rows = [
        {"msg_class": "00", "msg_no": "671", "text": "Job cancelled after system exception ERROR_MESSAGE", "msg_type": "E", "timestamp": "20260510120015"},
    ]
    out = _detect_dump_in_joblog(rows)
    assert out is not None
    assert out["runtime_error"] == "ERROR_MESSAGE"


def test_detect_dump_in_joblog_returns_none_for_clean_run():
    rows = [
        {"msg_class": "BT", "msg_no": "043", "text": "ok", "msg_type": "S", "timestamp": "20260510120015"},
    ]
    assert _detect_dump_in_joblog(rows) is None


def test_parse_syslog_for_dump_extracts_runtime_error_and_tid():
    raw = [
        {
            "USER": "MHRYTSELIAK",
            "MSGNO": "AB0",
            "TEXT": "Run-time error MESSAGE_TYPE_X has occurred. TID 008__08...0001",
            "DATE": "20260510",
            "TIME": "120016",
        }
    ]
    out = _parse_syslog_for_dump(raw)
    assert out is not None
    assert out["runtime_error"] == "MESSAGE_TYPE_X"
    assert out["tid"] == "008__08...0001"


def test_parse_syslog_for_dump_returns_none_when_no_match():
    raw = [{"USER": "ME", "MSGNO": "L01", "TEXT": "logon", "DATE": "20260510", "TIME": "120000"}]
    assert _parse_syslog_for_dump(raw) is None
