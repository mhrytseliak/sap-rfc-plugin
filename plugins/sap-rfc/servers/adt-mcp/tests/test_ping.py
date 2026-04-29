import pytest
import responses

from tools.ping import _ping_impl


BASE = "https://sap.example.com:8443"


@pytest.fixture
def base(keyring_stub, monkeypatch):
    monkeypatch.setattr("adt_client.discovery.find_adt_url", lambda: BASE)
    return BASE


@responses.activate
def test_ping_returns_ok_and_entry_count(base):
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<app:service xmlns:app="http://www.w3.org/2007/app">'
        '<app:workspace><app:collection href="a"/><app:collection href="b"/></app:workspace>'
        '</app:service>'
    )
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=200, body=body, headers={"Content-Type": "application/atomsvc+xml"},
    )
    r = _ping_impl()
    assert r["status"] == "ok"
    assert r["base_url"] == BASE
    assert r["core_discovery_entries"] == 2


@responses.activate
def test_ping_maps_401_to_adt_error(base):
    responses.add(
        responses.GET, BASE + "/sap/bc/adt/core/discovery",
        status=401,
        headers={"Content-Type": "application/xml"},
        body=('<exc:exception xmlns:exc="x"><type>AuthFail</type>'
              '<localizedMessage>nope</localizedMessage></exc:exception>'),
    )
    r = _ping_impl()
    assert r["error"] == "ADTError"
    assert r["http_status"] == 401


def test_ping_maps_discovery_failure(monkeypatch, keyring_stub):
    from errors import ADTNotAvailable
    def _boom(): raise ADTNotAvailable([{"url": "https://x", "reason": "nope"}])
    monkeypatch.setattr("adt_client.discovery.find_adt_url", _boom)
    r = _ping_impl()
    assert r["error"] == "ADTNotAvailable"
    assert r["tried"][0]["reason"] == "nope"
