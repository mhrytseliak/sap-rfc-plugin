"""Syntax check via RS_ABAP_SYNTAX_CHECK_E.

Returns three message tables (errors / warnings / infos) as RSLINMSGS, each
row a structured RSLINLMSG. We normalize them into a uniform dict shape.

Why not SIW_RFC_SYNTAX_CHECK: it returns a single error string with no
include name and no line position. Useless for surfacing more than one
finding.
"""


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
