"""adt-mcp: transport_create - create CTS workbench request via ADT.

ADT endpoint: POST /sap/bc/adt/cts/transports (NOT /transportrequests - that
path exists but only serves the transport-organizer UI and returns 'user
action is not supported' for create).

Body is the SAP asx:abap flat wrapper with DEVCLASS/REQUEST_TEXT/REF/OPERATION.
Content-Type must carry the dataname=com.sap.adt.CreateCorrectionRequest
marker. Response is plain text - the trkorr is the last path segment of the
returned URL.

The API requires an object context (REF + DEVCLASS). There is no ADT endpoint
for bare empty requests; that flow stays in SE09/SE10 or BAPI_CTREQUEST_CREATE.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable


def _build_body(devclass: str, text: str, ref: str, operation: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">'
        '<asx:values><DATA>'
        f'<DEVCLASS>{escape(devclass)}</DEVCLASS>'
        f'<REQUEST_TEXT>{escape(text)}</REQUEST_TEXT>'
        f'<REF>{escape(ref)}</REF>'
        f'<OPERATION>{escape(operation)}</OPERATION>'
        '</DATA></asx:values></asx:abap>'
    )


def _parse_trkorr(body: str) -> str:
    s = (body or "").strip().strip("/")
    return s.rsplit("/", 1)[-1] if s else ""


def _transport_create_impl(name: str, kind: str, devclass: str,
                           text: str, group: str | None = None,
                           operation: str = "I",
                           transport_layer: str = "") -> dict:
    try:
        ref = OBJECT_URI(name, kind, group=group)
        body = _build_body(devclass.upper(), text, ref, operation.upper())
        params = {"transportLayer": transport_layer} if transport_layer else None
        with ADTClient() as c:
            r = c.post(
                "/sap/bc/adt/cts/transports",
                params=params,
                data=body.encode("utf-8"),
                headers={
                    "Accept": "text/plain",
                    "Content-Type": ("application/vnd.sap.as+xml; charset=UTF-8;"
                                     " dataname=com.sap.adt.CreateCorrectionRequest"),
                },
            )
        trkorr = _parse_trkorr(r.text)
        if not trkorr:
            return {
                "error": "EmptyTRKORR",
                "detail": f"ADT returned no transport number. Body: {r.text!r}",
            }
        return {
            "status": "ok",
            "trkorr": trkorr,
            "devclass": devclass.upper(),
            "ref": ref,
            "text": text,
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
    def transport_create(name: str, kind: str, devclass: str, text: str,
                         group: str | None = None,
                         operation: str = "I",
                         transport_layer: str = "") -> dict:
        """Create a CTS workbench request via ADT for a given object.

        ADT requires an object context. The request is created in the object's
        development class; SAP auto-creates the task owned by the caller. The
        ref object does NOT need to exist yet — the TR is bound to the package.

        Bare empty TRs (no object/package context) cannot be created via ADT.
        For those, fall back to SE09/SE10 or BAPI_CTREQUEST_CREATE.

        ALWAYS confirm with the user before calling: show (name, kind,
        devclass, text) and only proceed on explicit approval.

        Args:
            name: Object name (upper-cased internally).
            kind: 'program' | 'include' | 'class' | 'interface' | 'fm'.
            devclass: Development class / package (e.g. 'ZPKG_FOO').
            text: Short description (<= 60 chars), shown in SE01.
            group: Required when kind='fm' (function group).
            operation: CTS operation code. Default 'I' (insert/modify).
            transport_layer: Optional transport layer override.

        Returns:
            {status: 'ok'|'error', trkorr, devclass, ref, text}
            or {error: 'ADTNotAvailable'|'ADTError'|'InvalidKind', ...}.
        """
        return _transport_create_impl(name, kind, devclass, text, group,
                                      operation, transport_layer)
