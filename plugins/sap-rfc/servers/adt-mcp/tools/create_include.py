"""adt-mcp: create_include - create a new ABAP include via ADT.

Endpoint: POST /sap/bc/adt/programs/includes[?corrNr=<TR>]
Content-Type: application/*  (same convention as create_program)
Body: include:abapInclude header with packageRef and optional containerRef
(the master program the include belongs to). No source is sent in this call -
after the header is created, source is uploaded via `update_source`
(kind='include').

Always pass `master_program` when the include is meant to be part of a
specific report. Without it the include is created as a "standalone" include
and SAP refuses to activate it ("Select a master program for include ... in
the properties view"). You can still omit `master_program` for truly shared
includes (referenced from multiple programs) - those must be activated from
within any one of their calling programs in SE38.

The created object is inactive and empty. Typical flow:
  transport_create -> create_program (main) -> create_include (each, with
  master_program=<main>) -> update_source (main + includes) -> syntax_check
  -> activate.

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
                responsible: str,
                master_program: str | None = None) -> str:
    container_ref = ""
    if master_program:
        mp = master_program.upper()
        container_ref = (
            f'<include:containerRef adtcore:name="{escape(mp)}"'
            ' adtcore:type="PROG/P"'
            f' adtcore:uri="/sap/bc/adt/programs/programs/{escape(mp.lower())}"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<include:abapInclude'
        ' xmlns:include="http://www.sap.com/adt/programs/includes"'
        ' xmlns:adtcore="http://www.sap.com/adt/core"'
        f' adtcore:description="{escape(description)}"'
        f' adtcore:name="{escape(name)}"'
        ' adtcore:type="PROG/I"'
        ' adtcore:language="EN"'
        ' adtcore:masterLanguage="EN"'
        f' adtcore:responsible="{escape(responsible)}">'
        f'<adtcore:packageRef adtcore:name="{escape(devclass)}"/>'
        f'{container_ref}'
        '</include:abapInclude>'
    )


def _create_include_impl(name: str, devclass: str, description: str,
                         transport: str | None = None,
                         master_program: str | None = None) -> dict:
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
        body = _build_body(name_u, description, devclass_u, responsible,
                           master_program=master_program)
        params = {"corrNr": transport} if transport else None
        with ADTClient() as c:
            c.post(
                "/sap/bc/adt/programs/includes",
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
    def create_include(name: str, devclass: str, description: str,
                       transport: str | None = None,
                       master_program: str | None = None) -> dict:
        """Create a new ABAP include via ADT.

        Creates the object header only; source is empty and inactive. Upload
        source via `update_source` (kind='include') and then call `activate`.

        ALWAYS confirm with the user before calling: show (name, devclass,
        transport, description, master_program) and only proceed on explicit
        approval.

        Args:
            name: Include name (upper-cased; max 30 chars; Y/Z prefix for
                customer namespace, or <main>_<suffix> convention).
            devclass: Development class / package. Use '$TMP' for local
                (no transport required).
            description: Short text shown in SE80 (<= 70 chars typical).
            transport: TRKORR that will carry the creation. Required unless
                devclass='$TMP'.
            master_program: Name of the main report this include belongs to.
                STRONGLY RECOMMENDED for program-specific includes — without
                it, SAP refuses to activate ("Select a master program for
                include ... in the properties view"). Omit only for shared
                includes referenced by multiple programs.

        Returns:
            {status: 'ok', name, devclass, transport, description}
            or {error: 'ADTNotAvailable' | 'ADTError' | 'TransportRequired' |
                      'NoAuthor' | ..., ...}.
        """
        return _create_include_impl(name, devclass, description, transport,
                                    master_program=master_program)
