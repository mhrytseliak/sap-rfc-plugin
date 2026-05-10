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
