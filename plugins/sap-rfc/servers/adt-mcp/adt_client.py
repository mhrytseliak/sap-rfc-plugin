"""Thin HTTP session wrapper for ADT calls - auth, sap-client, CSRF, locks."""
from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET

import keyring
import requests
from requests.auth import HTTPBasicAuth

import discovery
from errors import ADTError

SERVICE = "sap-rfc"


def _kr(key: str, default: str = "") -> str:
    return keyring.get_password(SERVICE, key) or default


_KIND_TO_PREFIX = {
    "program": "/sap/bc/adt/programs/programs",
    "include": "/sap/bc/adt/programs/includes",
    "class": "/sap/bc/adt/oo/classes",
    "interface": "/sap/bc/adt/oo/interfaces",
}


def OBJECT_URI(name: str, kind: str, *, group: str | None = None) -> str:
    """Build the ADT URI for an ABAP object."""
    name = name.upper()
    if kind == "fm":
        if not group:
            raise ValueError("kind='fm' requires group=<function group name>")
        return f"/sap/bc/adt/functions/groups/{group.upper()}/fmodules/{name}"
    try:
        return f"{_KIND_TO_PREFIX[kind]}/{name}"
    except KeyError:
        raise ValueError(f"unsupported kind: {kind!r}")


class ADTClient:
    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        self.base = base_url or discovery.find_adt_url()
        self.timeout = timeout or int(_kr("adt_timeout", "30"))
        self.s = requests.Session()
        self.s.auth = HTTPBasicAuth(_kr("user"), _kr("passwd"))
        self.s.headers.update({
            "sap-client": _kr("client"),
            "Accept": "application/xml,*/*;q=0.1",
        })
        verify = _kr("adt_verify_tls", "0") == "1"
        self.s.verify = verify
        self._verify = verify
        self._warnings_ctx: warnings.catch_warnings | None = None
        self._csrf: str | None = None

    def __enter__(self):
        if not self._verify:
            # Scope InsecureRequestWarning suppression to this session only —
            # a later session with adt_verify_tls=1 should see warnings again.
            self._warnings_ctx = warnings.catch_warnings()
            self._warnings_ctx.__enter__()
            warnings.filterwarnings("ignore",
                message="Unverified HTTPS request",
                category=Warning)
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
        return self

    def __exit__(self, *exc):
        self.s.close()
        if self._warnings_ctx is not None:
            self._warnings_ctx.__exit__(*exc)
            self._warnings_ctx = None

    def _ensure_csrf(self):
        if self._csrf:
            return
        r = self.s.get(
            self.base + "/sap/bc/adt/core/discovery",
            headers={"x-csrf-token": "fetch"},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise ADTError.from_response(r)
        self._csrf = r.headers.get("x-csrf-token", "")
        if self._csrf:
            self.s.headers["x-csrf-token"] = self._csrf

    def _request(self, method: str, path: str, **kw):
        kw.setdefault("timeout", self.timeout)
        r = self.s.request(method, self.base + path, **kw)
        if r.status_code >= 400:
            raise ADTError.from_response(r)
        return r

    def get(self, path, **kw):
        return self._request("GET", path, **kw)

    def post(self, path, **kw):
        self._ensure_csrf()
        return self._request("POST", path, **kw)

    def put(self, path, **kw):
        self._ensure_csrf()
        return self._request("PUT", path, **kw)

    def delete(self, path, **kw):
        self._ensure_csrf()
        return self._request("DELETE", path, **kw)

    # High-level
    def _set_stateful(self, on: bool) -> None:
        # SAP ADT lock is a stateful operation. Without this header every
        # request lands on a different work process and the lock evaporates
        # before the subsequent PUT, producing HTTP 423 "resource not locked".
        if on:
            self.s.headers["X-sap-adt-sessiontype"] = "stateful"
        else:
            self.s.headers.pop("X-sap-adt-sessiontype", None)

    def lock(self, obj_uri: str) -> str:
        self._set_stateful(True)
        r = self.post(
            obj_uri,
            params={"_action": "LOCK", "accessMode": "MODIFY"},
            headers={"Accept": "application/vnd.sap.as+xml"},
        )
        return _extract_lock_handle(r.text)

    def unlock(self, obj_uri: str, handle: str) -> None:
        try:
            self.post(obj_uri, params={"_action": "UNLOCK", "lockHandle": handle})
        finally:
            self._set_stateful(False)


def _extract_lock_handle(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "LOCK_HANDLE" and el.text:
            return el.text.strip()
    raise ADTError(200, "NoLockHandle", "LOCK response missing LOCK_HANDLE")
