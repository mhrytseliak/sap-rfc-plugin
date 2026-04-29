import pytest
import responses
from responses import matchers

from tools.create_class import _create_class_impl, _build_body


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


def test_build_body_has_class_namespace_and_type():
    body = _build_body("ZCL_TEST", "hello", "ZPKG", "APOPOV")
    assert 'xmlns:class="http://www.sap.com/adt/oo/classes"' in body
    assert 'xmlns:adtcore="http://www.sap.com/adt/core"' in body
    assert 'adtcore:name="ZCL_TEST"' in body
    assert 'adtcore:description="hello"' in body
    assert 'adtcore:type="CLAS/OC"' in body
    assert 'adtcore:responsible="APOPOV"' in body
    assert '<adtcore:packageRef adtcore:name="ZPKG"/>' in body


@responses.activate
def test_create_class_transportable_posts_with_corrnr(base):
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
        return (200, {}, "")
    responses.add_callback(
        responses.POST, BASE + "/sap/bc/adt/oo/classes",
        callback=_cb,
        match=[matchers.query_param_matcher({"corrNr": "DEVK900555"})],
    )
    r = _create_class_impl(
        name="zcl_test", devclass="zpkg", description="hi",
        transport="DEVK900555",
    )
    assert r["status"] == "ok"
    assert r["name"] == "ZCL_TEST"
    assert r["devclass"] == "ZPKG"
    assert r["transport"] == "DEVK900555"
    assert captured["ct"] == "application/*"
    assert 'adtcore:name="ZCL_TEST"' in captured["body"]
    assert 'adtcore:type="CLAS/OC"' in captured["body"]


def test_create_class_rejects_transportable_without_transport(base):
    r = _create_class_impl(name="ZCL_TEST", devclass="ZPKG", description="x")
    assert r["error"] == "TransportRequired"


@responses.activate
def test_create_class_local_tmp_does_not_require_transport(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    seen_qs = {}
    def _cb(request):
        seen_qs["url"] = request.url
        return (200, {}, "")
    responses.add_callback(
        responses.POST, BASE + "/sap/bc/adt/oo/classes",
        callback=_cb,
    )
    r = _create_class_impl(name="ZCL_LOCAL", devclass="$TMP", description="x")
    assert r["status"] == "ok"
    assert "corrNr" not in seen_qs["url"]


def test_create_class_missing_author_errors_out(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)
    keyring_stub.set_password("sap-rfc", "user", "")
    r = _create_class_impl(name="ZCL_TEST", devclass="$TMP", description="x")
    assert r["error"] == "NoAuthor"
