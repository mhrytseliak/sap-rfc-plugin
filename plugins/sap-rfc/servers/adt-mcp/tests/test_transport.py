import pytest
import responses

from tools.transport import _transport_of_object_impl, _parse_transports


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


def _asx(inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">'
        '<asx:values><DATA>' + inner + '</DATA></asx:values></asx:abap>'
    )


LOCKED_BY_TR = _asx(
    '<REQUESTS/>'
    '<LOCKS><CTS_OBJECT_LOCK>'
    '<OBJECT_KEY><PGMID>LIMU</PGMID><OBJECT>REPS</OBJECT>'
    '<OBJ_NAME>ZFOO</OBJ_NAME></OBJECT_KEY>'
    '<LOCK_HOLDER>'
    '<REQ_HEADER><TRKORR>DEVK900123</TRKORR><TRFUNCTION>K</TRFUNCTION>'
    '<TRSTATUS>D</TRSTATUS><AS4USER>APOPOV</AS4USER>'
    '<AS4TEXT>my change</AS4TEXT></REQ_HEADER>'
    '<TASK_HEADERS><CTS_TASK_HEADER>'
    '<TRKORR>DEVK900124</TRKORR><TRFUNCTION>S</TRFUNCTION><TRSTATUS>D</TRSTATUS>'
    '<AS4USER>APOPOV</AS4USER><AS4TEXT>my change</AS4TEXT>'
    '</CTS_TASK_HEADER></TASK_HEADERS>'
    '</LOCK_HOLDER>'
    '</CTS_OBJECT_LOCK></LOCKS>'
)


NO_LOCK = _asx('<REQUESTS/><LOCKS/>')


def test_parse_transports_extracts_locking_request():
    out = _parse_transports(LOCKED_BY_TR)
    trkorrs = [t["trkorr"] for t in out]
    assert trkorrs == ["DEVK900123"]
    req = out[0]
    assert req["type"] == "K"
    assert req["status"] == "D"
    assert req["owner"] == "APOPOV"
    assert req["text"] == "my change"


def test_parse_transports_empty_when_no_locks():
    assert _parse_transports(NO_LOCK) == []


@responses.activate
def test_transport_of_object_no_lock_returns_empty(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/cts/transportchecks",
        status=200, body=NO_LOCK,
    )
    r = _transport_of_object_impl("ZFOO", "program")
    assert r["in_transport"] is False
    assert r["transports"] == []


@responses.activate
def test_transport_of_object_returns_locking_transport(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/cts/transportchecks",
        status=200, body=LOCKED_BY_TR,
    )
    r = _transport_of_object_impl("ZFOO", "program")
    assert r["in_transport"] is True
    trkorrs = {t["trkorr"] for t in r["transports"]}
    assert "DEVK900123" in trkorrs
