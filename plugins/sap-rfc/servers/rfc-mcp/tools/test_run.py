"""Run an ABAP report via XBP and report short-dump info if it aborts.

Flow:
  BAPI_XMI_LOGON
    -> BAPI_XBP_JOB_OPEN
    -> BAPI_XBP_JOB_ADD_ABAP_STEP (FREE_SELINFO carries selection-screen values)
    -> BAPI_XBP_JOB_CLOSE
    -> BAPI_XBP_JOB_START_ASAP
    -> poll BAPI_XBP_JOB_STATUS_GET until F/A/X or timeout
    -> BAPI_XBP_JOB_JOBLOG_READ
    -> if aborted: RSLG_READ_FILE filtered by user/time/msg-class to extract dump
  BAPI_XMI_LOGOFF (always)
"""
from __future__ import annotations

import re


def _build_free_selinfo(
    params: dict | None,
    select_options: list[dict] | None,
) -> list[dict]:
    """Build the RSPARAMSL-shaped table consumed by BAPI_XBP_JOB_ADD_ABAP_STEP.

    PARAMETERS → single row, KIND='P', SIGN='I', OPTION='EQ'.
    SELECT-OPTIONS → one row per range entry, KIND='S'.
    """
    rows: list[dict] = []
    for k, v in (params or {}).items():
        rows.append(
            {
                "SELNAME": k.upper(),
                "KIND": "P",
                "SIGN": "I",
                "OPTION": "EQ",
                "LOW": str(v),
                "HIGH": "",
            }
        )
    for so in select_options or []:
        rows.append(
            {
                "SELNAME": so["name"].upper(),
                "KIND": "S",
                "SIGN": (so.get("sign") or "I").upper(),
                "OPTION": (so.get("option") or "EQ").upper(),
                "LOW": str(so.get("low", "")),
                "HIGH": str(so.get("high", "")),
            }
        )
    return rows


def _parse_joblog(rows: list[dict]) -> list[dict]:
    """Normalize BTCXPGLOG rows into compact dicts."""
    out = []
    for r in rows:
        out.append(
            {
                "timestamp": (r.get("LOG_DATE") or "") + (r.get("LOG_TIME") or ""),
                "msg_class": (r.get("MESSAGE_ID") or "").strip(),
                "msg_no": (r.get("MESSAGE_NUMBER") or "").strip(),
                "msg_type": (r.get("MESSAGE_TYPE") or "").strip(),
                "text": (r.get("MESSAGE") or "").strip(),
            }
        )
    return out


# Joblog dump line pattern. SAP localizes the prefix but the runtime-error
# token is always upper-case and trails the phrase.
_JOBLOG_RUNTIME_ERROR_RE = re.compile(
    r"(?:system exception|ABAP/4 processor:)\s+([A-Z][A-Z0-9_]+)"
)


def _detect_dump_in_joblog(rows: list[dict]) -> dict | None:
    """Return a partial dump dict if the joblog shows a runtime error, else None."""
    for r in rows:
        if r.get("msg_class") != "00" or r.get("msg_no") not in ("671", "672"):
            continue
        m = _JOBLOG_RUNTIME_ERROR_RE.search(r.get("text", ""))
        if m:
            return {
                "runtime_error": m.group(1),
                "tid": None,
                "program": None,
                "line": None,
                "short_text": r.get("text", ""),
            }
    return None


# Syslog dump line — message numbers AB0/AB1/AB2 are the "runtime error"
# class. Text format on modern SAP: "Run-time error <NAME> has occurred"
# and elsewhere a TID like "008__08...0001".
_SYSLOG_RUNTIME_ERROR_RE = re.compile(r"Run-time error\s+([A-Z][A-Z0-9_]+)")
_SYSLOG_TID_RE = re.compile(r"\bTID\s+([A-Za-z0-9_.]+)")


def _parse_syslog_for_dump(rows: list[dict]) -> dict | None:
    """Return the first runtime-error match in a SM21 row list."""
    for r in rows:
        text = (r.get("TEXT") or "")
        m = _SYSLOG_RUNTIME_ERROR_RE.search(text)
        if not m:
            continue
        tid_m = _SYSLOG_TID_RE.search(text)
        return {
            "runtime_error": m.group(1),
            "tid": tid_m.group(1) if tid_m else None,
            "program": None,
            "line": None,
            "short_text": text.strip(),
        }
    return None
