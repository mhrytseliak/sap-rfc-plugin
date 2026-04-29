"""adt-mcp: code_inspector - ATC check run via ADT (three-step worklist flow).

The old /sap/bc/adt/checkruns?reporters=atcChecker endpoint does not work on
modern SAP releases (returns HTTP 200 with empty body). The supported flow is:

  1. POST /sap/bc/adt/atc/worklists?checkVariant=<V>        -> worklistId
  2. POST /sap/bc/adt/atc/runs?worklistId=<id>  (atc:run)   -> run infos
  3. GET  /sap/bc/adt/atc/worklists/<id>                     -> findings XML

Reference: abap-adt-api/src/api/atc.ts (createAtcRun + atcCheckVariant +
atcWorklists).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable

_URI_POS_RE = re.compile(r"#start=(\d+),(\d+)")


def _build_run_body(obj_uri: str, max_verdicts: int = 100) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<atc:run maximumVerdicts="{max_verdicts}"'
        ' xmlns:atc="http://www.sap.com/adt/atc">'
        '<objectSets xmlns:adtcore="http://www.sap.com/adt/core">'
        '<objectSet kind="inclusive">'
        '<adtcore:objectReferences>'
        f'<adtcore:objectReference adtcore:uri="{obj_uri}"/>'
        '</adtcore:objectReferences>'
        '</objectSet>'
        '</objectSets>'
        '</atc:run>'
    )


def _parse_worklist(xml_text: str) -> tuple[list[dict], dict]:
    findings: list[dict] = []
    err = warn = info = 0
    if not xml_text.strip():
        return findings, {"error_count": 0, "warning_count": 0, "info_count": 0}
    root = ET.fromstring(xml_text)

    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag != "finding":
            continue
        attrs = {k.rsplit("}", 1)[-1]: v for k, v in el.attrib.items()}
        uri = attrs.get("location", "") or attrs.get("uri", "")
        m = _URI_POS_RE.search(uri)
        line, col = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        prio_raw = attrs.get("priority", "")
        try:
            prio = int(prio_raw)
        except ValueError:
            prio = 0
        # ATC priority 1/2 are errors, 3 warning, 4+ info.
        if prio in (1, 2):
            sev = "E"; err += 1
        elif prio == 3:
            sev = "W"; warn += 1
        else:
            sev = "I"; info += 1
        findings.append({
            "line": line,
            "col": col,
            "severity": sev,
            "priority": prio,
            "category": attrs.get("checkId", "") or attrs.get("category", ""),
            "message": attrs.get("messageTitle", "").strip()
                       or attrs.get("shortText", "").strip(),
        })
    return findings, {"error_count": err, "warning_count": warn, "info_count": info}


def _code_inspector_impl(name: str, kind: str, variant: str = "DEFAULT",
                         group: str | None = None,
                         max_verdicts: int = 100) -> dict:
    try:
        obj_uri = OBJECT_URI(name, kind, group=group)
        with ADTClient() as c:
            # Step 0: object-existence probe. ATC silently returns a clean
            # worklist for missing objects, which would masquerade as "passed".
            try:
                c.get(obj_uri)
            except ADTError as e:
                if e.status == 404:
                    return {"error": "ObjectNotFound",
                            "detail": f"{name.upper()} does not exist",
                            "uri": obj_uri}
                raise
            # Step 1: create a worklist for the variant.
            wl = c.post(
                "/sap/bc/adt/atc/worklists",
                params={"checkVariant": variant},
                headers={"Accept": "text/plain",
                         "Content-Type": "text/plain"},
            )
            worklist_id = wl.text.strip()
            if not worklist_id:
                return {"error": "ATCWorklistEmpty",
                        "detail": ("POST /atc/worklists returned empty body;"
                                   f" variant {variant!r} likely unknown.")}
            # Step 2: run the check for our object into the worklist.
            c.post(
                "/sap/bc/adt/atc/runs",
                params={"worklistId": worklist_id},
                data=_build_run_body(obj_uri, max_verdicts).encode("utf-8"),
                headers={"Content-Type": "application/xml"},
            )
            # Step 3: fetch findings.
            wlr = c.get(
                f"/sap/bc/adt/atc/worklists/{worklist_id}",
                headers={"Accept": "application/atc.worklist.v1+xml"},
            )
        findings, summary = _parse_worklist(wlr.text)
        return {
            "variant": variant,
            "findings": findings,
            "summary": summary,
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
    def code_inspector(name: str, kind: str = "program",
                       variant: str = "DEFAULT",
                       group: str | None = None,
                       max_verdicts: int = 100) -> dict:
        """Run ATC / Code Inspector on an ABAP object via ADT.

        Three-step protocol: create a worklist for the variant, run the
        check against the target object, fetch the findings XML.

        Args:
            name: Object name.
            kind: 'program' | 'include' | 'class' | 'interface' | 'fm'.
            variant: ATC variant name (customer-defined, e.g. 'DEFAULT',
                'Z_QUALITY'). Unknown variant => ATCWorklistEmpty error.
            group: Required when kind='fm'.
            max_verdicts: Cap on findings returned (SAP-side).

        Returns:
            {variant, findings: [{line, col, severity, priority, category,
                                  message}],
             summary: {error_count, warning_count, info_count}}
            or {error: 'ADTNotAvailable'|'ADTError'|'ATCWorklistEmpty'|..., ...}.
        """
        return _code_inspector_impl(name, kind, variant, group, max_verdicts)
