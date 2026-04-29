"""Shared pytest fixtures for adt-mcp tests.

Mocks OS keyring (so tests do not touch Windows Credential Manager) and the
rfc connection factory (so tests do not hit a live SAP system).
"""
import sys
from pathlib import Path

import pytest

# Make adt-mcp modules importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _KeyringStub:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, key):
        return self.store.get((service, key))

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def delete_password(self, service, key):
        self.store.pop((service, key), None)


@pytest.fixture
def keyring_stub(monkeypatch):
    stub = _KeyringStub()
    import keyring as real_kr
    monkeypatch.setattr(real_kr, "get_password", stub.get_password)
    monkeypatch.setattr(real_kr, "set_password", stub.set_password)
    monkeypatch.setattr(real_kr, "delete_password", stub.delete_password)
    # seed with standard creds
    stub.set_password("sap-rfc", "ashost", "sap.example.com")
    stub.set_password("sap-rfc", "sysnr", "00")
    stub.set_password("sap-rfc", "client", "999")
    stub.set_password("sap-rfc", "user", "TESTUSER")
    stub.set_password("sap-rfc", "passwd", "secret")
    stub.set_password("sap-rfc", "lang", "EN")
    return stub


class FakeConnection:
    """Minimal pyrfc.Connection stand-in; returns canned ICM_GET_INFO."""

    def __init__(self, servlist=None):
        self._servlist = servlist or [
            {"ACTIVE": "X", "PROTOCOL": 2, "HOSTNAME": "sap-dev.example.com", "SERVICE": "8443"},
            {"ACTIVE": "X", "PROTOCOL": 1, "HOSTNAME": "sap-dev.example.com", "SERVICE": "8000"},
            {"ACTIVE": "X", "PROTOCOL": 4, "HOSTNAME": "sap-dev.example.com", "SERVICE": "2525"},
        ]

    def call(self, fm, **_):
        if fm == "ICM_GET_INFO":
            return {"INFO_DATA": {}, "SERVLIST": self._servlist}
        raise RuntimeError(f"unstubbed FM: {fm}")

    def close(self):  # pyrfc API
        pass


@pytest.fixture
def fake_conn(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr("discovery._open_rfc_connection", lambda: conn)
    return conn
