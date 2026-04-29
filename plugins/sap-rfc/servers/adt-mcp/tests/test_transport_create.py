import pytest
import responses
from responses import matchers

from tools.transport_create import _transport_create_impl, _build_body, _parse_trkorr


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


def test_parse_trkorr_from_plain_response():
    assert _parse_trkorr("/sap/bc/adt/cts/transports/DEVK900123") == "DEVK900123"
    assert _parse_trkorr("DEVK900123") == "DEVK900123"
    assert _parse_trkorr("") == ""


def test_build_body_has_asx_abap_wrapper_and_dataname_fields():
    body = _build_body("ZPKG", "hello", "/sap/bc/adt/programs/programs/ZPROG", "I")
    assert '<asx:abap xmlns:asx="http://www.sap.com/abapxml"' in body
    assert "<DEVCLASS>ZPKG</DEVCLASS>" in body
    assert "<REQUEST_TEXT>hello</REQUEST_TEXT>" in body
    assert "<REF>/sap/bc/adt/programs/programs/ZPROG</REF>" in body
    assert "<OPERATION>I</OPERATION>" in body


@responses.activate
def test_transport_create_posts_to_cts_transports_and_returns_trkorr(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    captured = {}
    def _cb(request):
        captured["body"] = (request.body.decode()
                            if isinstance(request.body, (bytes, bytearray))
                            else request.body)
        captured["ct"] = request.headers.get("Content-Type", "")
        captured["accept"] = request.headers.get("Accept", "")
        return (200, {}, "/sap/bc/adt/cts/transports/DEVK900555")
    responses.add_callback(
        responses.POST, BASE + "/sap/bc/adt/cts/transports",
        callback=_cb,
    )
    r = _transport_create_impl(
        name="ZPROG", kind="program", devclass="ZPKG", text="my TR",
    )
    assert r["status"] == "ok"
    assert r["trkorr"] == "DEVK900555"
    assert r["devclass"] == "ZPKG"
    assert r["ref"].endswith("/ZPROG")

    assert "dataname=com.sap.adt.CreateCorrectionRequest" in captured["ct"]
    assert "application/vnd.sap.as+xml" in captured["ct"]
    assert captured["accept"] == "text/plain"
    assert "<DEVCLASS>ZPKG</DEVCLASS>" in captured["body"]
    assert "<REQUEST_TEXT>my TR</REQUEST_TEXT>" in captured["body"]
    assert "<OPERATION>I</OPERATION>" in captured["body"]


@responses.activate
def test_transport_create_passes_transport_layer_query_param(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    responses.add(
        responses.POST, BASE + "/sap/bc/adt/cts/transports",
        status=200, body="/sap/bc/adt/cts/transports/DEVK900999",
        match=[matchers.query_param_matcher({"transportLayer": "ZLAYER"})],
    )
    r = _transport_create_impl(
        name="ZPROG", kind="program", devclass="ZPKG", text="x",
        transport_layer="ZLAYER",
    )
    assert r["status"] == "ok"
    assert r["trkorr"] == "DEVK900999"


@responses.activate
def test_transport_create_invalid_kind_returns_error(base):
    r = _transport_create_impl(
        name="ZPROG", kind="bogus", devclass="ZPKG", text="x",
    )
    assert r["error"] == "InvalidKind"


@responses.activate
def test_transport_create_fm_requires_group(base):
    r = _transport_create_impl(
        name="Z_FM_X", kind="fm", devclass="ZPKG", text="x",
    )
    assert r["error"] == "InvalidKind"
