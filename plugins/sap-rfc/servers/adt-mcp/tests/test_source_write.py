import pytest
import responses

from tools.source_write import _update_source_impl


BASE = "https://sap.example.com:8443"
OBJ = "/sap/bc/adt/programs/programs/ZFOO"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)


@pytest.fixture
def source_file(tmp_path, monkeypatch):
    # Pretend the cache lives under tmp_path so the safety guard accepts files
    # we write here. update_source rejects paths outside the cache root by design.
    monkeypatch.setattr("tools.source_write._SAFE_ROOT", tmp_path.resolve())
    p = tmp_path / "ZFOO.abap"
    p.write_text("REPORT zfoo.\nWRITE 'hi'.\n", encoding="utf-8")
    return str(p)


def test_update_source_rejects_path_outside_cache(base, tmp_path):
    # Path lives outside the cache root — must be refused before any HTTP call.
    p = tmp_path / "evil.abap"
    p.write_text("REPORT evil.", encoding="utf-8")
    r = _update_source_impl(
        name="ZFOO", kind="program",
        source_file=str(p), transport="DEVK900123",
    )
    assert r["error"] == "SourceFileOutsideCache"


def _add_csrf():
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, headers={"x-csrf-token": "T"}, body="<ok/>",
    )


LOCK_BODY = (
    '<asx:abap xmlns:asx="http://www.sap.com/abapxml"><asx:values>'
    '<DATA><LOCK_HANDLE>HANDLE123</LOCK_HANDLE></DATA>'
    '</asx:values></asx:abap>'
)


@responses.activate
def test_update_source_full_lock_put_unlock_flow(base, source_file):
    _add_csrf()
    responses.add(responses.POST, BASE + OBJ, status=200, body=LOCK_BODY,
        match=[responses.matchers.query_param_matcher(
            {"_action": "LOCK", "accessMode": "MODIFY"})])
    responses.add(responses.PUT, BASE + OBJ + "/source/main",
        status=200, body="",
        match=[responses.matchers.query_param_matcher(
            {"lockHandle": "HANDLE123", "corrNr": "DEVK900123"})])
    responses.add(responses.POST, BASE + OBJ, status=200, body="",
        match=[responses.matchers.query_param_matcher(
            {"_action": "UNLOCK", "lockHandle": "HANDLE123"})])
    r = _update_source_impl(
        name="ZFOO", kind="program",
        source_file=source_file, transport="DEVK900123",
    )
    assert r["status"] == "ok"
    assert r["action"] == "updated"
    assert r["line_count"] == 2


@responses.activate
def test_update_source_unlocks_even_when_put_fails(base, source_file):
    _add_csrf()
    responses.add(responses.POST, BASE + OBJ, status=200, body=LOCK_BODY,
        match=[responses.matchers.query_param_matcher(
            {"_action": "LOCK", "accessMode": "MODIFY"})])
    responses.add(responses.PUT, BASE + OBJ + "/source/main",
        status=400,
        headers={"Content-Type": "application/xml"},
        body='<exc:exception xmlns:exc="x"><type>SyntaxError</type>'
             '<localizedMessage>Bad code</localizedMessage></exc:exception>')
    unlock_called = {"yes": False}
    def _cb(request):
        unlock_called["yes"] = True
        return (200, {}, "")
    responses.add_callback(responses.POST, BASE + OBJ, callback=_cb,
        match=[responses.matchers.query_param_matcher(
            {"_action": "UNLOCK", "lockHandle": "HANDLE123"})])
    r = _update_source_impl(
        name="ZFOO", kind="program",
        source_file=source_file, transport="DEVK900123",
    )
    assert r["error"] == "ADTError"
    assert r["http_status"] == 400
    assert unlock_called["yes"] is True
