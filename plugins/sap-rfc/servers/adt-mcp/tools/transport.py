"""adt-mcp: transport_of_object - find open TRs holding an object.

The old /sap/bc/adt/cts/transports/searchobject endpoint returns an empty
body on modern SAP releases. The working protocol is a POST to
/sap/bc/adt/cts/transportchecks with an asx:abap body carrying URI + OPERATION.

The response's LOCKS/CTS_OBJECT_LOCK/LOCK_HOLDER/REQ_HEADER block identifies
the transport currently locking the object (and its task). REQUESTS carries
suggested new requests when the object is not yet locked.

Reference: abap-adt-api/src/api/transports.ts::transportInfo.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable


def _build_body(obj_uri: str, operation: str, devclass: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">'
        '<asx:values><DATA>'
        f'<DEVCLASS>{escape(devclass)}</DEVCLASS>'
        f'<OPERATION>{escape(operation)}</OPERATION>'
        f'<URI>{escape(obj_uri)}</URI>'
        '</DATA></asx:values></asx:abap>'
    )


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _parse_transports(xml_text: str) -> list[dict]:
    out: list[dict] = []
    if not xml_text.strip():
        return out
    root = ET.fromstring(xml_text)
    seen: set[str] = set()

    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "REQ_HEADER":
            continue
        trkorr = _text(el, "TRKORR")
        if not trkorr or trkorr in seen:
            continue
        seen.add(trkorr)
        out.append({
            "trkorr": trkorr,
            "owner": _text(el, "AS4USER"),
            "status": _text(el, "TRSTATUS"),
            "type": _text(el, "TRFUNCTION"),
            "text": _text(el, "AS4TEXT"),
        })
    return out


def _transport_of_object_impl(name: str, kind: str,
                              group: str | None = None,
                              operation: str = "I",
                              devclass: str = "") -> dict:
    try:
        obj_uri = OBJECT_URI(name, kind, group=group)
        body = _build_body(obj_uri, operation.upper(), devclass.upper())
        with ADTClient() as c:
            r = c.post(
                "/sap/bc/adt/cts/transportchecks",
                data=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/vnd.sap.as+xml; charset=UTF-8;",
                    "Accept": "application/vnd.sap.as+xml",
                },
            )
        transports = [t for t in _parse_transports(r.text) if t["status"] != "R"]
        return {
            "in_transport": bool(transports),
            "transports": transports,
        }
    except ADTNotAvailable as e:
        return {"error": "ADTNotAvailable", "detail": str(e)}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except ValueError as e:
        return {"error": "InvalidKind", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def transport_of_object(name: str, kind: str = "program",
                            group: str | None = None,
                            operation: str = "I",
                            devclass: str = "") -> dict:
        """Find OPEN transports that contain (lock) the given ABAP object.

        POSTs to /sap/bc/adt/cts/transportchecks and parses the LOCKS block
        for the holding transport + task (and any suggested requests).

        Args:
            name: Object name (case-insensitive).
            kind: 'program', 'include', 'class', 'interface', 'fm'.
            group: Required when kind='fm'.
            operation: CTS operation; default 'I' (insert/modify).
            devclass: Optional devclass hint (empty string is fine).

        Returns:
            {in_transport: bool, transports: [
                {trkorr, owner, status, type, text}
            ]}
            'status' is raw CTS status (D=modifiable, L=locked, R=released);
            released transports are filtered from the result. 'type' is the
            CTS TRFUNCTION (K=workbench, W=customizing, S=task, ...).
        """
        return _transport_of_object_impl(name, kind, group, operation, devclass)
