import pytest
import responses

from tools.activate import _activate_impl


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


@responses.activate
def test_activate_returns_ok_on_empty_200(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(responses.POST, BASE + "/sap/bc/adt/activation",
                  status=200, body="")
    r = _activate_impl([{"name": "ZFOO", "kind": "program"}])
    assert r["status"] == "ok"
    assert r["activated"] == ["ZFOO"]
    assert r["errors"] == []


@responses.activate
def test_activate_returns_errors_when_messages_present(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    body = (
        '<chkl:messages xmlns:chkl="http://www.sap.com/abapxml/checklist">'
        '<msg objUri="/sap/bc/adt/programs/programs/ZFOO" type="E"'
        '  shortText="Syntax error in line 5"/>'
        '</chkl:messages>'
    )
    responses.add(responses.POST, BASE + "/sap/bc/adt/activation",
                  status=200, body=body)
    r = _activate_impl([{"name": "ZFOO", "kind": "program"}])
    assert r["status"] == "error"
    assert len(r["errors"]) == 1
    assert "Syntax error" in r["errors"][0]["message"]
