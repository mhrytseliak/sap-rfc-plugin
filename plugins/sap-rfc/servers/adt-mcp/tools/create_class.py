"""adt-mcp: create_class - create a new global ABAP class (CLAS/OC) via ADT.

Endpoint: POST /sap/bc/adt/oo/classes[?corrNr=<TR>]
Content-Type: application/*
Body: class:abapClass header with packageRef. No source is sent in this call -
after the header is created, source is uploaded via `update_source`
(kind='class') and activated via `activate` (kind='class').

The created object is an empty shell (PUBLIC FINAL CREATE PUBLIC, empty
DEFINITION/IMPLEMENTATION) and inactive. Typical flow:
  transport_create -> create_class -> update_source (full class body in one
  payload on source/main) -> syntax_check -> activate.

`transport` is required when devclass is NOT '$TMP'.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

import keyring

from adt_client import ADTClient
from errors import ADTError, ADTNotAvailable

SERVICE = "sap-rfc"


def _build_body(name: str, description: str, devclass: str,
                responsible: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<class:abapClass'
        ' xmlns:class="http://www.sap.com/adt/oo/classes"'
        ' xmlns:adtcore="http://www.sap.com/adt/core"'
        f' adtcore:description="{escape(description)}"'
        f' adtcore:name="{escape(name)}"'
        ' adtcore:type="CLAS/OC"'
        ' adtcore:language="EN"'
        ' adtcore:masterLanguage="EN"'
        f' adtcore:responsible="{escape(responsible)}">'
        f'<adtcore:packageRef adtcore:name="{escape(devclass)}"/>'
        '</class:abapClass>'
    )


def _create_class_impl(name: str, devclass: str, description: str,
                       transport: str | None = None) -> dict:
    try:
        name_u = name.upper()
        devclass_u = devclass.upper()
        if devclass_u != "$TMP" and not transport:
            return {"error": "TransportRequired",
                    "detail": (f"devclass {devclass_u!r} is transportable;"
                               " pass transport=<TRKORR>.")}
        responsible = (keyring.get_password(SERVICE, "user") or "").upper()
        if not responsible:
            return {"error": "NoAuthor",
                    "detail": "SAP user not in keyring; run /sap-connect."}
        body = _build_body(name_u, description, devclass_u, responsible)
        params = {"corrNr": transport} if transport else None
        with ADTClient() as c:
            c.post(
                "/sap/bc/adt/oo/classes",
                params=params,
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/*"},
            )
        return {
            "status": "ok",
            "name": name_u,
            "devclass": devclass_u,
            "transport": transport or "",
            "description": description,
        }
    except ADTNotAvailable as e:
        return {"error": "ADTNotAvailable", "detail": str(e)}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def create_class(name: str, devclass: str, description: str,
                     transport: str | None = None) -> dict:
        """Create a new global ABAP class (CLAS/OC) via ADT.

        Creates an empty shell (PUBLIC FINAL CREATE PUBLIC, empty
        DEFINITION/IMPLEMENTATION), inactive. Upload the full class body in
        one payload via `update_source(name, kind='class', source_file=...)`,
        then `activate(objects=[{name, kind:'class'}])`.

        ABAP classes have no per-method write endpoint - the entire class
        (DEFINITION + IMPLEMENTATION) is written to source/main in a single
        PUT. Local types / test classes live in separate includes but are
        optional for v1.

        ALWAYS confirm with the user before calling: show (name, devclass,
        transport, description) and only proceed on explicit approval.

        Args:
            name: Class name (upper-cased; Y/Z prefix for customer namespace;
                max 30 chars).
            devclass: Development class / package. Use '$TMP' for local
                (no transport required).
            description: Short text shown in SE80 (<= 70 chars typical).
            transport: TRKORR that will carry the creation. Required unless
                devclass='$TMP'.

        Returns:
            {status: 'ok', name, devclass, transport, description}
            or {error: 'ADTNotAvailable' | 'ADTError' | 'TransportRequired' |
                      'NoAuthor' | ..., ...}.
        """
        return _create_class_impl(name, devclass, description, transport)
