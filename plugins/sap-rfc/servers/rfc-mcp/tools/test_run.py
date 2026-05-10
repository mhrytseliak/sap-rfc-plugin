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
import time

import keyring

from connection import get_connection, SERVICE_NAME
from timeout import JOB_POLL_INTERVAL, with_timeout, RFCTimeout


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


# SNAP TLV format (header row, SEQNO='000'): repeated <2-char tag><3-digit length><payload>.
# Tags we care about — verified live on DS4 / S/4 758:
#   FC = runtime-error name (e.g. MESSAGE_TYPE_X_TEXT)
#   AP = program at dump
#   AI = include at dump
#   AL = source line (numeric, not zero-padded inside the value)
#   TD = transaction ID (32-char hex)
_SNAP_TAG_RE = re.compile(r"([A-Z]{2})(\d{3})")


def _parse_snap_flist(flist: str) -> dict:
    """Parse SNAP.FLIST TLV header into {tag: value, ...}.

    Returns only the tags we know how to interpret; unknown tags are
    skipped silently. Malformed input returns an empty dict.
    """
    out: dict[str, str] = {}
    pos = 0
    while pos < len(flist):
        m = _SNAP_TAG_RE.match(flist, pos)
        if not m:
            break
        tag = m.group(1)
        try:
            length = int(m.group(2))
        except ValueError:
            break
        start = m.end()
        end = start + length
        if end > len(flist):
            break
        out[tag] = flist[start:end]
        pos = end
    return out


def _read_dump_from_snap(conn, user: str, t0: time.struct_time) -> dict | None:
    """Look up the most recent dump for `user` since `t0` in SNAP and parse it.

    SNAP is keyed by (DATUM, UZEIT, AHOST, UNAME, MANDT, MODNO, SEQNO). Header
    row is SEQNO='000' and carries the TLV with FC/AP/AI/AL/TD. Returns None if
    no matching dump found.
    """
    user = user.upper()
    today = time.strftime("%Y%m%d", t0)
    t0_time = time.strftime("%H%M%S", t0)
    where = f"UNAME EQ '{user}' AND DATUM EQ '{today}' AND SEQNO EQ '000'"
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="SNAP",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "DATUM"},
            {"FIELDNAME": "UZEIT"},
            {"FIELDNAME": "FLIST"},
        ],
        OPTIONS=[{"TEXT": where}],
        ROWCOUNT=20,
    )
    rows = []
    for line in result.get("DATA", []):
        parts = [p.strip() for p in line["WA"].split("|", 2)]
        if len(parts) >= 3 and parts[1] >= t0_time:
            rows.append((parts[0], parts[1], parts[2]))
    if not rows:
        return None
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    flist = rows[0][2]
    parsed = _parse_snap_flist(flist)
    if not parsed.get("FC"):
        return None
    runtime_error = parsed["FC"]
    if runtime_error.endswith("_TEXT"):
        runtime_error = runtime_error[:-5]
    line_str = parsed.get("AL", "").strip()
    try:
        line_no = int(line_str) if line_str else None
    except ValueError:
        line_no = None
    return {
        "runtime_error": runtime_error,
        "tid": parsed.get("TD") or None,
        "program": parsed.get("AP") or None,
        "include": parsed.get("AI") or None,
        "line": line_no,
        "short_text": parsed.get("FC", ""),
    }


_DONE_STATUSES = {"F", "A", "X"}
_STATUS_TO_OUT = {"F": "finished", "A": "aborted", "X": "cancelled"}


class XBPCallFailed(Exception):
    """An XBP BAPI returned RETURN.TYPE='E'/'A' instead of succeeding."""


def _raise_if_error(result: dict, fm_name: str) -> None:
    """Surface BAPIRET2 errors as exceptions so callers don't silently see a stuck job."""
    ret = (result or {}).get("RETURN") or {}
    if ret.get("TYPE") in ("E", "A"):
        raise XBPCallFailed(
            f"{fm_name}: {ret.get('ID', '')} {ret.get('NUMBER', '')} {ret.get('MESSAGE', '')}"
        )


def _xmi_logon(conn) -> None:
    conn.call(
        "BAPI_XMI_LOGON",
        EXTCOMPANY="sap-rfc",
        EXTPRODUCT="test_run",
        INTERFACE="XBP",
        VERSION="3.0",
    )


def _xmi_logoff(conn) -> None:
    try:
        conn.call("BAPI_XMI_LOGOFF", INTERFACE="XBP")
    except Exception:
        pass


def _read_syslog(conn, user: str, t0: time.struct_time, t1: time.struct_time) -> list[dict]:
    sel = {
        "DATE": time.strftime("%Y%m%d", t0),
        "TIME": time.strftime("%H%M%S", t0),
        "EDATE": time.strftime("%Y%m%d", t1),
        "ETIME": time.strftime("%H%M%S", t1),
        "USER": user.upper(),
        "MSGINC": "X",
        "MSGLST": "AB0,AB1,AB2",
    }
    result = conn.call("RSLG_READ_FILE", SELECTION=sel)
    return result.get("SYSLOG_IN_TABLE", []) or []


def _test_run_impl(
    name: str,
    params: dict | None,
    select_options: list[dict] | None,
    variant: str | None,
    max_wait_sec: int,
) -> dict:
    if variant and (params or select_options):
        return {
            "error": "MutuallyExclusive",
            "detail": "Pass either `variant` OR (params/select_options), not both.",
        }
    name = name.upper()
    user = (keyring.get_password(SERVICE_NAME, "user") or "").upper()

    free_selinfo = _build_free_selinfo(params, select_options) if not variant else []

    conn = get_connection()
    started = time.monotonic()
    t0 = time.gmtime()
    jobname = f"ZRFCMCP_{name}_{int(time.time())}"[:32]
    jobcount = ""
    status_out = "timeout"
    joblog: list[dict] = []
    dump: dict | None = None
    runtime_sec = 0

    try:
        _xmi_logon(conn)

        open_res = conn.call("BAPI_XBP_JOB_OPEN", JOBNAME=jobname, EXTERNAL_USER_NAME=user)
        jobcount = open_res.get("JOBCOUNT", "")

        step_kwargs = dict(
            JOBNAME=jobname,
            JOBCOUNT=jobcount,
            EXTERNAL_USER_NAME=user,
            ABAP_PROGRAM_NAME=name,
            SAP_USER_NAME=user,
        )
        if variant:
            step_kwargs["ABAP_VARIANT_NAME"] = variant
        else:
            step_kwargs["FREE_SELINFO"] = free_selinfo
        conn.call("BAPI_XBP_JOB_ADD_ABAP_STEP", **step_kwargs)

        close_res = conn.call(
            "BAPI_XBP_JOB_CLOSE",
            JOBNAME=jobname,
            JOBCOUNT=jobcount,
            EXTERNAL_USER_NAME=user,
        )
        _raise_if_error(close_res, "BAPI_XBP_JOB_CLOSE")
        start_res = conn.call(
            "BAPI_XBP_JOB_START_ASAP",
            JOBNAME=jobname,
            JOBCOUNT=jobcount,
            EXTERNAL_USER_NAME=user,
            TARGET_SERVER="",
        )
        _raise_if_error(start_res, "BAPI_XBP_JOB_START_ASAP")

        # Poll.
        elapsed = 0.0
        while True:
            elapsed = time.monotonic() - started
            if elapsed > max_wait_sec:
                status_out = "timeout"
                break
            res = conn.call(
                "BAPI_XBP_JOB_STATUS_GET",
                JOBNAME=jobname,
                JOBCOUNT=jobcount,
                EXTERNAL_USER_NAME=user,
            )
            st = (res.get("STATUS") or "").strip()
            if st in _DONE_STATUSES:
                status_out = _STATUS_TO_OUT[st]
                break
            time.sleep(JOB_POLL_INTERVAL)

        runtime_sec = int(elapsed)

        # Joblog (always).
        log_res = conn.call(
            "BAPI_XBP_JOB_JOBLOG_READ",
            JOBNAME=jobname,
            JOBCOUNT=jobcount,
            EXTERNAL_USER_NAME=user,
        )
        joblog = _parse_joblog(log_res.get("JOB_PROTOCOL_NEW", []) or [])

        if status_out == "aborted":
            try:
                dump = _read_dump_from_snap(conn, user, t0)
            except Exception:
                dump = None
            if dump is None:
                t1 = time.gmtime()
                try:
                    syslog_rows = _read_syslog(conn, user, t0, t1)
                    dump = _parse_syslog_for_dump(syslog_rows)
                except Exception:
                    dump = None
            if dump is None:
                dump = _detect_dump_in_joblog(joblog)

        # Auto-delete terminal jobs (F/A/X) — leave timeout jobs alone so the
        # caller can poll/inspect later via SM37.
        if status_out in _STATUS_TO_OUT.values() and jobcount:
            try:
                conn.call(
                    "BAPI_XBP_JOB_DELETE",
                    JOBNAME=jobname,
                    JOBCOUNT=jobcount,
                    EXTERNAL_USER_NAME=user,
                )
            except Exception:
                pass  # Cleanup is best-effort; never fail the whole call.
    finally:
        _xmi_logoff(conn)
        try:
            conn.close()
        except Exception:
            pass

    return {
        "status": status_out,
        "jobname": jobname,
        "jobcount": jobcount,
        "runtime_sec": runtime_sec,
        "joblog": joblog,
        "dump": dump,
    }


def register(mcp):
    @mcp.tool()
    def test_run(
        name: str,
        params: dict | None = None,
        select_options: list[dict] | None = None,
        variant: str | None = None,
        max_wait_sec: int = 120,
    ) -> dict:
        """Run an ABAP report via XBP and detect runtime dumps.

        Submits `name` as a one-step background job through the XBP / XMI
        interface, waits for completion, and reports back the joblog plus a
        structured `dump` dict if the job aborted with a short dump (ST22).
        Dump info is correlated from SM21 (RSLG_READ_FILE) by user + time
        window; a joblog-only fallback is used if syslog yields nothing.

        IMPORTANT: write tool — Claude must summarize parameters and wait for
        explicit user approval before calling.

        Args:
            name: Executable program name (TRDIR-SUBC='1').
            params: Selection-screen PARAMETERS values, e.g. `{'P_DATE': '20260510'}`.
            select_options: Selection-screen SELECT-OPTIONS as a list of
                {name, sign('I'|'E'), option('EQ'|'BT'|'CP'|...), low, high}
                rows. Multiple rows per option name are allowed.
            variant: Caller-supplied saved variant. Mutually exclusive with
                `params`/`select_options`.
            max_wait_sec: Wall-clock budget for the poll loop. Default 120.
                On timeout the job keeps running; caller can poll later via
                SM37 with the returned `jobname`/`jobcount`.

        Returns:
            {status, jobname, jobcount, runtime_sec, joblog, dump} on success.
            {error, detail} on failure.

        `status` ∈ {'finished','aborted','cancelled','timeout'}.
        `dump` is None unless the job aborted with a short dump.
        """
        from pyrfc import LogonError, CommunicationError, ABAPApplicationError
        try:
            return with_timeout(
                _test_run_impl,
                name, params, select_options, variant, max_wait_sec,
                seconds=max(max_wait_sec + 30, 60),
            )
        except RFCTimeout as e:
            return {"error": "Timeout", "detail": str(e)}
        except XBPCallFailed as e:
            return {"error": "XBPCallFailed", "detail": str(e)}
        except LogonError as e:
            return {"error": "LogonError", "detail": str(e)}
        except CommunicationError as e:
            return {"error": "CommunicationError", "detail": str(e)}
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
