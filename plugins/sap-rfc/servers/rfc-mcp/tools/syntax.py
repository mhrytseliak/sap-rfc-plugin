"""Syntax check via RS_ABAP_SYNTAX_CHECK_E.

Returns three message tables (errors / warnings / infos) as RSLINMSGS, each
row a structured RSLINLMSG. We normalize them into a uniform dict shape.

Why not SIW_RFC_SYNTAX_CHECK: it returns a single error string with no
include name and no line position. Useless for surfacing more than one
finding.
"""

import keyring

from connection import get_connection, SERVICE_NAME
from timeout import with_timeout, RFCTimeout


def _parse_messages(rows: list[dict]) -> list[dict]:
    """Normalize an RSLINMSGS table into a list of dicts."""
    out = []
    for r in rows:
        out.append(
            {
                "include": (r.get("INCNAME") or "").strip(),
                "line": int(r.get("LINE") or 0),
                "col": int(r.get("COL") or 0),
                "keyword": (r.get("KEYWORD") or "").strip(),
                "msg_no": (r.get("MSGNUMBER") or "").strip(),
                "message": (r.get("MESSAGE") or "").strip(),
                "kind": (r.get("KIND") or "").strip(),
            }
        )
    return out


def _syntax_check_impl(name: str, kind: str) -> dict:
    name = name.upper()
    lang = (keyring.get_password(SERVICE_NAME, "lang") or "EN").upper()[:1]
    conn = get_connection()
    try:
        result = conn.call(
            "RS_ABAP_SYNTAX_CHECK_E",
            P_PROGRAM=name,
            P_LANGU=lang,
            P_NO_PACKAGE_CHECK="",
            P_INTERPRET="",
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
    errors = _parse_messages(result.get("P_ERRORS", []))
    warnings = _parse_messages(result.get("P_WARNINGS", []))
    infos = _parse_messages(result.get("P_INFOS", []))
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "subrc": int(result.get("P_SUBRC") or 0),
    }


def register(mcp):
    @mcp.tool()
    def syntax_check_rfc(name: str, kind: str = "program") -> dict:
        """Run a full ABAP syntax check on an existing program/include via RFC.

        Uses RS_ABAP_SYNTAX_CHECK_E (RFC-enabled). Returns errors, warnings, and
        infos as structured rows with include name, line, column, keyword, and
        message text.

        IMPORTANT: this checks the **uploaded** version of the object, not a
        local file. To check edited source, upload it first via `upload_program`
        and then call this tool.

        Args:
            name: Program or include name (auto-uppercased).
            kind: 'program' (default) or 'include'. Informational; the FM
                  accepts any TRDIR entry by name.

        Returns:
            {ok, errors, warnings, infos, subrc} on success.
            {error, detail} on failure.
        """
        from pyrfc import LogonError, CommunicationError, ABAPApplicationError
        try:
            return with_timeout(_syntax_check_impl, name, kind)
        except RFCTimeout as e:
            return {"error": "Timeout", "detail": str(e)}
        except LogonError as e:
            return {"error": "LogonError", "detail": str(e)}
        except CommunicationError as e:
            return {"error": "CommunicationError", "detail": str(e)}
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
