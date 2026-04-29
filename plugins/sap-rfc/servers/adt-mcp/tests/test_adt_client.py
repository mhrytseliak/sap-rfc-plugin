import pytest
import responses

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError


BASE = "https://sap.example.com:8443"


@pytest.fixture
def client(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)
    return ADTClient()


def test_object_uri_program():
    assert OBJECT_URI("ZFOO", "program") == "/sap/bc/adt/programs/programs/ZFOO"


def test_object_uri_class_uppercased():
    assert OBJECT_URI("zcl_bar", "class") == "/sap/bc/adt/oo/classes/ZCL_BAR"


def test_object_uri_fm_needs_group():
    with pytest.raises(ValueError):
        OBJECT_URI("ZFM", "fm")
    assert OBJECT_URI("ZFM", "fm", group="ZGRP") == \
        "/sap/bc/adt/functions/groups/ZGRP/fmodules/ZFM"


def test_object_uri_unknown_kind():
    with pytest.raises(ValueError):
        OBJECT_URI("X", "widget")


@responses.activate
def test_get_has_basic_auth_and_sap_client(client):
    responses.add(responses.GET, f"{BASE}/any", status=200, body="ok")
    client.get("/any")
    call = responses.calls[0].request
    assert "Basic " in call.headers["Authorization"]
    assert call.headers["sap-client"] == "999"


@responses.activate
def test_post_fetches_csrf_then_reuses_it(client):
    responses.add(
        responses.GET, f"{BASE}/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "TOKEN42"}, body="<ok/>",
    )
    responses.add(responses.POST, f"{BASE}/x", status=201)
    responses.add(responses.POST, f"{BASE}/y", status=201)
    client.post("/x"); client.post("/y")
    # discovery fetched once, then two POSTs - 3 calls total
    assert len(responses.calls) == 3
    assert responses.calls[0].request.headers["x-csrf-token"] == "fetch"
    assert responses.calls[1].request.headers["x-csrf-token"] == "TOKEN42"
    assert responses.calls[2].request.headers["x-csrf-token"] == "TOKEN42"


@responses.activate
def test_non_2xx_raises_adt_error(client):
    responses.add(
        responses.GET, f"{BASE}/bad", status=403,
        headers={"Content-Type": "application/xml"},
        body=(
            '<exc:exception xmlns:exc="http://www.sap.com/abapxml/types/defined">'
            '<type>NotAuth</type>'
            '<localizedMessage lang="EN">No authorization</localizedMessage>'
            '</exc:exception>'
        ),
    )
    with pytest.raises(ADTError) as ei:
        client.get("/bad")
    assert ei.value.status == 403
    assert "authorization" in ei.value.message.lower()


@responses.activate
def test_lock_and_unlock(client):
    responses.add(
        responses.GET, f"{BASE}/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    lock_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<asx:abap xmlns:asx="http://www.sap.com/abapxml"><asx:values>'
        '<DATA><LOCK_HANDLE>HANDLE123</LOCK_HANDLE></DATA>'
        '</asx:values></asx:abap>'
    )
    responses.add(
        responses.POST,
        f"{BASE}/sap/bc/adt/programs/programs/ZFOO",
        status=200, body=lock_body,
        match=[responses.matchers.query_param_matcher(
            {"_action": "LOCK", "accessMode": "MODIFY"})],
    )
    responses.add(
        responses.POST,
        f"{BASE}/sap/bc/adt/programs/programs/ZFOO",
        status=200, body="",
        match=[responses.matchers.query_param_matcher(
            {"_action": "UNLOCK", "lockHandle": "HANDLE123"})],
    )
    h = client.lock("/sap/bc/adt/programs/programs/ZFOO")
    assert h == "HANDLE123"
    # LOCK must flip the session to stateful - without this header SAP drops
    # the lock before the subsequent PUT lands (HTTP 423).
    lock_req = responses.calls[1].request
    assert lock_req.headers.get("X-sap-adt-sessiontype") == "stateful"
    client.unlock("/sap/bc/adt/programs/programs/ZFOO", h)
    # UNLOCK clears the stateful header so later calls on the same session
    # don't keep pinning to a stateful work process.
    assert "X-sap-adt-sessiontype" not in client.s.headers
