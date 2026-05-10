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


from unittest.mock import MagicMock

from tools.test_run import _test_run_impl


def _success_dispatch(status_seq):
    """Make a fake conn.call dispatcher cycling through statuses."""
    iter_status = iter(status_seq)

    def dispatch(fm, **kwargs):
        if fm == "BAPI_XMI_LOGON":
            return {"RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_OPEN":
            return {"JOBCOUNT": "12345678", "RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_ADD_ABAP_STEP":
            return {"STEP_NUMBER": 1, "RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_CLOSE":
            return {"RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_START_ASAP":
            return {"RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_STATUS_GET":
            return {"STATUS": next(iter_status), "RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_JOBLOG_READ":
            return {"JOB_PROTOCOL_NEW": [], "RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XMI_LOGOFF":
            return {"RETURN": {"TYPE": "S"}}
        return {}
    return dispatch


def test_test_run_finished_clean(monkeypatch):
    conn = MagicMock()
    conn.call.side_effect = _success_dispatch(["R", "F"])
    monkeypatch.setattr("tools.test_run.get_connection", lambda: conn)
    monkeypatch.setattr("tools.test_run.keyring.get_password", lambda *_: "MHRYTSELIAK")
    monkeypatch.setattr("tools.test_run.JOB_POLL_INTERVAL", 0)

    out = _test_run_impl("ZGOOD", None, None, None, max_wait_sec=10)

    assert out["status"] == "finished"
    assert out["dump"] is None
    assert out["jobcount"] == "12345678"


def test_test_run_aborted_pulls_syslog(monkeypatch):
    iter_status = iter(["R", "A"])

    def dispatch(fm, **kwargs):
        if fm == "BAPI_XBP_JOB_STATUS_GET":
            return {"STATUS": next(iter_status), "RETURN": {"TYPE": "S"}}
        if fm == "BAPI_XBP_JOB_JOBLOG_READ":
            return {
                "JOB_PROTOCOL_NEW": [
                    {
                        "LOG_DATE": "20260510",
                        "LOG_TIME": "120015",
                        "MESSAGE_ID": "00",
                        "MESSAGE_NUMBER": "671",
                        "MESSAGE_TYPE": "E",
                        "MESSAGE": "Job cancelled after system exception MESSAGE_TYPE_X",
                    }
                ],
                "RETURN": {"TYPE": "S"},
            }
        if fm == "RSLG_READ_FILE":
            return {
                "SYSLOG_IN_TABLE": [
                    {
                        "USER": "MHRYTSELIAK",
                        "MSGNO": "AB0",
                        "TEXT": "Run-time error MESSAGE_TYPE_X has occurred. TID 008__08...0001",
                        "DATE": "20260510",
                        "TIME": "120016",
                    }
                ]
            }
        if fm == "BAPI_XBP_JOB_OPEN":
            return {"JOBCOUNT": "1", "RETURN": {"TYPE": "S"}}
        return {"RETURN": {"TYPE": "S"}}

    conn = MagicMock()
    conn.call.side_effect = dispatch
    monkeypatch.setattr("tools.test_run.get_connection", lambda: conn)
    monkeypatch.setattr("tools.test_run.keyring.get_password", lambda *_: "MHRYTSELIAK")
    monkeypatch.setattr("tools.test_run.JOB_POLL_INTERVAL", 0)

    out = _test_run_impl("ZBAD", None, None, None, max_wait_sec=10)
    assert out["status"] == "aborted"
    assert out["dump"]["runtime_error"] == "MESSAGE_TYPE_X"
    assert out["dump"]["tid"] == "008__08...0001"


def test_test_run_timeout_returns_jobcount(monkeypatch):
    conn = MagicMock()
    conn.call.side_effect = _success_dispatch(["R"] * 100)
    monkeypatch.setattr("tools.test_run.get_connection", lambda: conn)
    monkeypatch.setattr("tools.test_run.keyring.get_password", lambda *_: "ME")
    monkeypatch.setattr("tools.test_run.JOB_POLL_INTERVAL", 0)
    # Fake a time source that exceeds max_wait_sec immediately on second poll.
    times = iter([0.0, 0.5, 100.0])
    monkeypatch.setattr("tools.test_run.time.monotonic", lambda: next(times))

    out = _test_run_impl("ZSLOW", None, None, None, max_wait_sec=5)
    assert out["status"] == "timeout"
    assert out["jobcount"] == "12345678"


def test_test_run_mutually_exclusive(monkeypatch):
    monkeypatch.setattr("tools.test_run.get_connection", lambda: MagicMock())
    monkeypatch.setattr("tools.test_run.keyring.get_password", lambda *_: "ME")
    out = _test_run_impl("ZX", {"P_X": "1"}, None, "MYVARIANT", max_wait_sec=5)
    assert out["error"] == "MutuallyExclusive"
