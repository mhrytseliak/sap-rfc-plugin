import pytest
import responses

from tools.syntax import _syntax_impl


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


@responses.activate
def test_syntax_ok_when_no_messages(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/checkruns",
        status=200,
        body='<chkrun:checkMessageList xmlns:chkrun="http://www.sap.com/adt/checkrun"/>',
    )
    r = _syntax_impl("ZFOO", "program")
    assert r["syntax_ok"] is True
    assert r["errors"] == []
    assert r["warnings"] == []


@responses.activate
def test_syntax_parses_errors_and_warnings(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    body = (
        '<chkrun:checkMessageList xmlns:chkrun="http://www.sap.com/adt/checkrun"'
        ' xmlns:adtcore="http://www.sap.com/adt/core">'
        '<chkrun:checkMessage uri="/sap/bc/adt/programs/programs/ZFOO/source/main#start=5,3"'
        '  shortText="Field BAR unknown" type="E"/>'
        '<chkrun:checkMessage uri="/sap/bc/adt/programs/programs/ZFOO/source/main#start=10,1"'
        '  shortText="Obsolete statement" type="W"/>'
        '</chkrun:checkMessageList>'
    )
    responses.add(responses.POST, BASE + "/sap/bc/adt/checkruns", status=200, body=body)
    r = _syntax_impl("ZFOO", "program")
    assert r["syntax_ok"] is False
    assert len(r["errors"]) == 1
    assert r["errors"][0]["line"] == 5
    assert r["errors"][0]["col"] == 3
    assert "BAR" in r["errors"][0]["message"]
    assert len(r["warnings"]) == 1
    assert r["warnings"][0]["line"] == 10
