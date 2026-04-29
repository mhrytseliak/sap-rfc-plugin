"""Resolve the ADT base URL for the currently-connected SAP system.

Strategy: cached keyring value -> ICM_GET_INFO via RFC -> TCP+HTTP probe ->
keyring cache. Raises ADTNotAvailable if no candidate answers.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import keyring
import requests
from requests.auth import HTTPBasicAuth

from errors import ADTNotAvailable

SERVICE = "sap-rfc"
TCP_TIMEOUT = 4
HTTP_TIMEOUT = 10
DISCOVERY_PATH = "/sap/bc/adt/core/discovery"


def _open_rfc_connection():
    """Import rfc-mcp's get_connection() lazily so tests can patch it."""
    rfc_dir = Path(__file__).resolve().parents[1] / "rfc-mcp"
    if str(rfc_dir) not in sys.path:
        sys.path.insert(0, str(rfc_dir))
    from connection import get_connection  # type: ignore
    return get_connection()


def _tcp_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return True
    except OSError:
        return False


def _http_probe(base_url: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True when server speaks ADT (HTTP 200 or 401)."""
    user = keyring.get_password(SERVICE, "user") or ""
    passwd = keyring.get_password(SERVICE, "passwd") or ""
    client = keyring.get_password(SERVICE, "client") or ""
    verify = keyring.get_password(SERVICE, "adt_verify_tls") == "1"
    try:
        r = requests.get(
            base_url + DISCOVERY_PATH,
            auth=HTTPBasicAuth(user, passwd),
            headers={
                "sap-client": client,
                "Accept": "application/atomsvc+xml,application/xml,*/*;q=0.1",
            },
            timeout=HTTP_TIMEOUT,
            verify=verify,
        )
        return (r.status_code in (200, 401), f"http {r.status_code}")
    except requests.RequestException as e:
        return (False, f"{type(e).__name__}: {e}")


def _candidates_from_icm() -> list[str]:
    """Call ICM_GET_INFO, return ordered list of base URLs (HTTPS first)."""
    conn = _open_rfc_connection()
    try:
        r = conn.call("ICM_GET_INFO")
    finally:
        try: conn.close()
        except Exception: pass

    https_urls, http_urls = [], []
    for row in r.get("SERVLIST", []) or []:
        if row.get("ACTIVE") != "X":
            continue
        proto = row.get("PROTOCOL")
        host = (row.get("HOSTNAME") or "").strip()
        port = str(row.get("SERVICE") or "").strip()
        if not host or not port:
            continue
        if proto == 2:
            https_urls.append(f"https://{host}:{port}")
        elif proto == 1:
            http_urls.append(f"http://{host}:{port}")
    return https_urls + http_urls


def _parse_host_port(url: str) -> tuple[str, int]:
    scheme, _, body = url.partition("://")
    body = body.rstrip("/")
    host, sep, port = body.partition(":")
    if not sep:
        port = "443" if scheme == "https" else "80"
    return host, int(port)


def find_adt_url() -> str:
    tried: list[dict] = []

    cached = keyring.get_password(SERVICE, "adt_url")
    if cached:
        host, port = _parse_host_port(cached)
        if _tcp_reachable(host, port):
            ok, reason = _http_probe(cached)
            if ok:
                return cached
            tried.append({"url": cached, "reason": f"cached unreachable: {reason}"})
        else:
            tried.append({"url": cached, "reason": "cached: tcp unreachable"})
        # Stale cache: drop it so ICM fallback below (or the next invocation)
        # isn't pinned to a URL that no longer works (e.g. VPN change).
        try:
            keyring.delete_password(SERVICE, "adt_url")
        except keyring.errors.PasswordDeleteError:
            pass

    for url in _candidates_from_icm():
        host, port = _parse_host_port(url)
        if not _tcp_reachable(host, port):
            tried.append({"url": url, "reason": "tcp unreachable"})
            continue
        ok, reason = _http_probe(url)
        if ok:
            keyring.set_password(SERVICE, "adt_url", url)
            return url
        tried.append({"url": url, "reason": reason})

    raise ADTNotAvailable(tried)
