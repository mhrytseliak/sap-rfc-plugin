"""adt-mcp: create_program - create a new ABAP report (executable program) via ADT.

Endpoint: POST /sap/bc/adt/programs/programs[?corrNr=<TR>]
Content-Type: application/*  (per abap-adt-api reference implementation)
Body: program:abapProgram header with packageRef. No source is sent in this
call - after the header is created, source is uploaded via `update_source`.

The created object is inactive and empty. Typical flow:
  transport_create -> create_program -> update_source -> syntax_check ->
  (fix) -> syntax_check -> activate.

`transport` is required when devclass is NOT '$TMP' (SAP rejects transportable
creates without corrNr).
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
        '<program:abapProgram'
        ' xmlns:program="http://www.sap.com/adt/programs/programs"'
        ' xmlns:adtcore="http://www.sap.com/adt/core"'
        f' adtcore:description="{escape(description)}"'
        f' adtcore:name="{escape(name)}"'
        ' adtcore:type="PROG/P"'
        ' adtcore:language="EN"'
        ' adtcore:masterLanguage="EN"'
        f' adtcore:responsible="{escape(responsible)}">'
        f'<adtcore:packageRef adtcore:name="{escape(devclass)}"/>'
        '</program:abapProgram>'
    )


def _create_program_impl(name: str, devclass: str, description: str,
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
                "/sap/bc/adt/programs/programs",
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
        return {"error": "ADTNotAvailable", "detail": str(e), "tried": e.tried}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def create_program(name: str, devclass: str, description: str,
                       transport: str | None = None) -> dict:
        """Create a new ABAP executable program (REPORT) via ADT.

        Creates the object header only; source is empty and inactive. Upload
        source via `update_source` and then call `activate`.

        ALWAYS confirm with the user before calling: show (name, devclass,
        transport, description) and only proceed on explicit approval.

        Args:
            name: Program name (upper-cased; max 30 chars; Y/Z prefix for
                customer namespace).
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
        return _create_program_impl(name, devclass, description, transport)
