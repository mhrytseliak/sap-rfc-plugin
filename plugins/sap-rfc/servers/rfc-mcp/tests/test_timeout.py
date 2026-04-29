"""Tests for the rfc-mcp timeout helper."""
from __future__ import annotations

import time

import pytest

import timeout as timeout_module
from timeout import RFCTimeout, with_timeout, get_rfc_timeout, DEFAULT_RFC_TIMEOUT


def test_with_timeout_returns_value_when_fast():
    assert with_timeout(lambda: 42, seconds=2) == 42


def test_with_timeout_passes_args_and_kwargs():
    def add(a, b, *, c):
        return a + b + c
    assert with_timeout(add, 1, 2, c=3, seconds=2) == 6


def test_with_timeout_raises_rfctimeout_when_slow():
    def hang():
        time.sleep(5)
        return "should not reach"
    start = time.monotonic()
    with pytest.raises(RFCTimeout) as exc_info:
        with_timeout(hang, seconds=1)
    elapsed = time.monotonic() - start
    # Returns within ~1s of the timeout, not after the 5s sleep finishes.
    assert elapsed < 2.5, f"with_timeout took {elapsed}s, expected ~1s"
    assert "1s" in str(exc_info.value)
    assert "rfc_timeout" in str(exc_info.value)


def test_with_timeout_propagates_exceptions_from_callable():
    def boom():
        raise ValueError("from worker")
    with pytest.raises(ValueError, match="from worker"):
        with_timeout(boom, seconds=2)


def test_get_rfc_timeout_returns_default_when_keyring_missing(monkeypatch):
    monkeypatch.setattr(timeout_module.keyring, "get_password", lambda *a, **k: None)
    assert get_rfc_timeout() == DEFAULT_RFC_TIMEOUT


def test_get_rfc_timeout_parses_int(monkeypatch):
    monkeypatch.setattr(timeout_module.keyring, "get_password", lambda *a, **k: "120")
    assert get_rfc_timeout() == 120


def test_get_rfc_timeout_falls_back_on_invalid(monkeypatch):
    monkeypatch.setattr(timeout_module.keyring, "get_password", lambda *a, **k: "not-a-number")
    assert get_rfc_timeout() == DEFAULT_RFC_TIMEOUT


def test_get_rfc_timeout_falls_back_on_zero_or_negative(monkeypatch):
    monkeypatch.setattr(timeout_module.keyring, "get_password", lambda *a, **k: "0")
    assert get_rfc_timeout() == DEFAULT_RFC_TIMEOUT
    monkeypatch.setattr(timeout_module.keyring, "get_password", lambda *a, **k: "-5")
    assert get_rfc_timeout() == DEFAULT_RFC_TIMEOUT
