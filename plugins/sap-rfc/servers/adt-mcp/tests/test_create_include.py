import pytest
import responses
from responses import matchers

from tools.create_include import _create_include_impl, _build_body


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


def test_build_body_has_include_namespace_and_type():
    body = _build_body("ZTEST_TOP", "hello", "ZPKG", "APOPOV")
    assert 'xmlns:include="http://www.sap.com/adt/programs/includes"' in body
    assert 'xmlns:adtcore="http://www.sap.com/adt/core"' in body
    assert 'adtcore:name="ZTEST_TOP"' in body
    assert 'adtcore:description="hello"' in body
    assert 'adtcore:type="PROG/I"' in body
    assert 'adtcore:responsible="APOPOV"' in body
    assert '<adtcore:packageRef adtcore:name="ZPKG"/>' in body
    assert body.startswith('<?xml')
    assert body.endswith('</include:abapInclude>')
    # No containerRef when master_program omitted
    assert 'containerRef' not in body


def test_build_body_emits_container_ref_when_master_program_given():
    body = _build_body("ZTEST_TOP", "hello", "ZPKG", "APOPOV",
                       master_program="ZTEST_MAIN")
    assert '<include:containerRef' in body
    assert 'adtcore:name="ZTEST_MAIN"' in body
    assert 'adtcore:type="PROG/P"' in body
    assert 'adtcore:uri="/sap/bc/adt/programs/programs/ztest_main"' in body


def test_build_body_uppercases_master_program():
    body = _build_body("ZTEST_TOP", "hello", "ZPKG", "APOPOV",
                       master_program="ztest_main")
    # Attribute is upper-case; URI path is lower-case (SAP convention)
    assert 'adtcore:name="ZTEST_MAIN"' in body
    assert '/sap/bc/adt/programs/programs/ztest_main"' in body


@responses.activate
def test_create_include_transportable_posts_with_corrnr(base):
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
        responses.POST, BASE + "/sap/bc/adt/programs/includes",
        callback=_cb,
        match=[matchers.query_param_matcher({"corrNr": "DEVK900555"})],
    )
    r = _create_include_impl(
        name="ztest_top", devclass="zpkg", description="top",
        transport="DEVK900555",
    )
    assert r["status"] == "ok"
    assert r["name"] == "ZTEST_TOP"
    assert r["devclass"] == "ZPKG"
    assert r["transport"] == "DEVK900555"
    assert captured["ct"] == "application/*"
    assert 'adtcore:name="ZTEST_TOP"' in captured["body"]
    assert 'include:abapInclude' in captured["body"]


def test_create_include_rejects_transportable_without_transport(base):
    r = _create_include_impl(name="ZTEST_TOP", devclass="ZPKG",
                             description="x")
    assert r["error"] == "TransportRequired"


@responses.activate
def test_create_include_local_tmp_does_not_require_transport(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )
    seen_qs = {}

    def _cb(request):
        seen_qs["url"] = request.url
        return (200, {}, "")

    responses.add_callback(
        responses.POST, BASE + "/sap/bc/adt/programs/includes",
        callback=_cb,
    )
    r = _create_include_impl(name="ZLOCAL_TOP", devclass="$TMP",
                             description="x")
    assert r["status"] == "ok"
    assert "corrNr" not in seen_qs["url"]


def test_create_include_missing_author_errors_out(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)
    keyring_stub.set_password("sap-rfc", "user", "")
    r = _create_include_impl(name="ZTEST_TOP", devclass="$TMP",
                             description="x")
    assert r["error"] == "NoAuthor"
