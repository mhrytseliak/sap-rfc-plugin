"""adt-mcp: syntax_check - ADT check-run (no 72-char truncation)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable

_URI_POS_RE = re.compile(r"#start=(\d+),(\d+)")


def _build_body(obj_uri: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<chkrun:checkObjectList'
        ' xmlns:chkrun="http://www.sap.com/adt/checkrun"'
        ' xmlns:adtcore="http://www.sap.com/adt/core">'
        f'<chkrun:checkObject adtcore:uri="{obj_uri}" adtcore:version="active"/>'
        '</chkrun:checkObjectList>'
    )


def _parse_messages(xml_text: str) -> tuple[list[dict], list[dict]]:
    errors, warnings = [], []
    if not xml_text or not xml_text.strip():
        return errors, warnings
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "checkMessage":
            continue
        # ADT namespaces attributes as chkrun:uri etc. ElementTree keys them
        # as "{ns}name" — strip the namespace for lookup.
        attrs = {k.rsplit("}", 1)[-1]: v for k, v in el.attrib.items()}
        uri = attrs.get("uri", "")
        m = _URI_POS_RE.search(uri)
        line, col = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        sev = attrs.get("type", "").upper()
        msg = {
            "line": line,
            "col": col,
            "severity": sev,
            "message": attrs.get("shortText", "").strip(),
        }
        if sev == "E":
            errors.append(msg)
        elif sev == "W":
            warnings.append(msg)
    return errors, warnings


def _syntax_impl(name: str, kind: str, group: str | None = None) -> dict:
    try:
        obj_uri = OBJECT_URI(name, kind, group=group)
        with ADTClient() as c:
            r = c.post(
                "/sap/bc/adt/checkruns",
                params={"reporters": "abapCheckRun"},
                data=_build_body(obj_uri).encode("utf-8"),
                headers={"Content-Type": "application/vnd.sap.adt.checkobjects+xml"},
            )
        errors, warnings = _parse_messages(r.text)
        return {
            "syntax_ok": not errors,
            "errors": errors,
            "warnings": warnings,
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
    def syntax_check(name: str, kind: str = "program",
                     group: str | None = None) -> dict:
        """ABAP syntax check via ADT.

        No 72-char line truncation (the RFC version truncates). Accepts the
        full line width. Returns errors + warnings with {line, col, severity,
        message}.

        Args:
            name: Object name (case-insensitive).
            kind: 'program' (default), 'include', 'class', 'interface', 'fm'.
            group: Required when kind='fm' (function group name).

        Returns:
            {syntax_ok, errors: [{line, col, severity, message}],
             warnings: [{line, col, severity, message}]}
            On failure: {error: 'ADTNotAvailable' | 'ADTError' | 'InvalidKind', ...}
        """
        return _syntax_impl(name, kind, group)
