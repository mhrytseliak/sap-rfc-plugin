import socket

import pytest
import responses

import discovery
from errors import ADTNotAvailable


@pytest.fixture(autouse=True)
def _no_real_tcp(monkeypatch):
    """By default TCP probe succeeds; individual tests can override."""
    class _Sock:
        def __enter__(self): return self
        def __exit__(self, *exc): pass
    monkeypatch.setattr(discovery.socket, "create_connection", lambda *a, **kw: _Sock())


@responses.activate
def test_uses_cached_url_when_reachable(keyring_stub, fake_conn):
    import keyring
    keyring.set_password("sap-rfc", "adt_url", "https://cached.example.com:8443")
    responses.add(
        responses.GET,
        "https://cached.example.com:8443/sap/bc/adt/core/discovery",
        status=200,
        body="<ok/>",
    )
    assert discovery.find_adt_url() == "https://cached.example.com:8443"


@responses.activate
def test_prefers_https_from_icm_get_info(keyring_stub, fake_conn):
    responses.add(
        responses.GET,
        "https://sap-dev.example.com:8443/sap/bc/adt/core/discovery",
        status=200, body="<ok/>",
    )
    assert discovery.find_adt_url() == "https://sap-dev.example.com:8443"
    import keyring
    assert keyring.get_password("sap-rfc", "adt_url") == "https://sap-dev.example.com:8443"


@responses.activate
def test_falls_back_to_http_when_https_refuses(keyring_stub, fake_conn):
    responses.add(
        responses.GET,
        "https://sap-dev.example.com:8443/sap/bc/adt/core/discovery",
        status=500, body="boom",
    )
    responses.add(
        responses.GET,
        "http://sap-dev.example.com:8000/sap/bc/adt/core/discovery",
        status=401, body="<challenge/>",
    )
    # 401 counts as "ADT is there"
    assert discovery.find_adt_url() == "http://sap-dev.example.com:8000"


def test_raises_adt_not_available_when_all_probes_fail(
    keyring_stub, fake_conn, monkeypatch
):
    def _boom(*a, **kw): raise socket.timeout("nope")
    monkeypatch.setattr(discovery.socket, "create_connection", _boom)
    with pytest.raises(ADTNotAvailable) as ei:
        discovery.find_adt_url()
    assert len(ei.value.tried) >= 2
