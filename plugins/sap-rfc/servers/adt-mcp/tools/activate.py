"""adt-mcp: activate - activation of changed objects via ADT."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable


def _resolve_include_context(c: ADTClient, name: str) -> str | None:
    """Fetch include header and return its master program ADT URI, or None."""
    r = c.get(OBJECT_URI(name, "include"))
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return None
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "contextRef":
            continue
        for k, v in el.attrib.items():
            if k.rsplit("}", 1)[-1] == "uri" and v:
                return v
    return None


def _build_body(objects: list[dict], c: ADTClient | None = None) -> str:
    refs = []
    for o in objects:
        name_u = o["name"].upper()
        kind = o["kind"]
        uri = OBJECT_URI(name_u, kind, group=o.get("group"))
        if kind == "include":
            ctx = o.get("master_program")
            if ctx:
                ctx_uri = OBJECT_URI(ctx, "program")
            elif c is not None:
                ctx_uri = _resolve_include_context(c, name_u)
            else:
                ctx_uri = None
            if ctx_uri:
                uri = f"{uri}?context={quote(ctx_uri, safe='/')}"
        refs.append(
            f'<adtcore:objectReference adtcore:uri="{uri}" '
            f'adtcore:name="{name_u}"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">'
        + "".join(refs) +
        '</adtcore:objectReferences>'
    )


def _parse_messages(xml_text: str) -> list[dict]:
    if not xml_text.strip():
        return []
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "msg":
            continue
        attrs = {k.rsplit("}", 1)[-1]: v for k, v in el.attrib.items()}
        message = attrs.get("shortText", "").strip()
        if not message:
            # Newer releases nest the text as <shortText><txt>...</txt></shortText>
            for child in el:
                if child.tag.rsplit("}", 1)[-1] != "shortText":
                    continue
                txt = "".join(child.itertext()).strip()
                if txt:
                    message = txt
                break
        out.append({
            "object": attrs.get("objUri", "") or attrs.get("objDescr", ""),
            "severity": attrs.get("type", "").upper(),
            "message": message,
        })
    return out


def _activate_impl(objects: list[dict]) -> dict:
    try:
        if not objects:
            return {"error": "NoObjects", "detail": "objects list is empty"}
        with ADTClient() as c:
            body = _build_body(objects, c)
            r = c.post(
                "/sap/bc/adt/activation",
                params={"method": "activate", "preauditRequested": "true"},
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/xml"},
            )
        messages = _parse_messages(r.text)
        errors = [m for m in messages if m["severity"] == "E"]
        return {
            "status": "error" if errors else "ok",
            "activated": [o["name"].upper() for o in objects] if not errors else [],
            "errors": errors,
            "messages": messages,
        }
    except ADTNotAvailable as e:
        return {"error": "ADTNotAvailable", "detail": str(e), "tried": e.tried}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except ValueError as e:
        return {"error": "InvalidKind", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def activate(objects: list[dict]) -> dict:
        """Activate one or more ABAP objects via ADT.

        Empty 200 response = success. A chkl:messages response with E-severity
        rows = activation failed; caller must fix and retry.

        Args:
            objects: List of {name, kind, group?, master_program?}.
                'kind' = 'program' | 'include' | 'class' | 'interface' | 'fm'.
                'group' required when kind='fm'. 'master_program' is the main
                report for an include — required by ADT for activation; if
                omitted, auto-resolved via the include's contextRef (GET).

        Returns:
            {status: 'ok'|'error', activated: [names], errors: [...], messages: [...]}
            or {error: 'ADTNotAvailable'|'ADTError'|..., ...}.
        """
        return _activate_impl(objects)
