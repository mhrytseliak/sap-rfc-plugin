"""Upload an ABAP program or include via RFC.

Path used:
- New executable program ('1'/'M'/'S'/...): RPY_PROGRAM_INSERT
- New include ('I'): RPY_INCLUDE_INSERT
- Existing object (any kind): RPY_INCLUDE_UPDATE — works for executable
  programs too because it operates on TRDIR by name and writes via
  INSERT REPORT … STATE 'A'. RPY_PROGRAM_UPDATE is NOT RFC-enabled on
  current S/4 releases (FMODE='' in TFDIR).

All write FMs auto-activate.
"""
from __future__ import annotations

ABAP_LINE_MAX = 255


def _validate_lines(lines: list[str]) -> list[int] | None:
    """Return 1-based line numbers that exceed ABAP_LINE_MAX, or None if all ok."""
    bad = [i + 1 for i, l in enumerate(lines) if len(l) > ABAP_LINE_MAX]
    return bad or None


def _to_source_extended(lines: list[str]) -> list[dict]:
    """Wrap each line into the ABAPTXT255 row shape pyrfc expects."""
    return [{"LINE": l} for l in lines]


def _probe(conn, name: str) -> dict | None:
    """Return PROG_INF if the program/include exists, else None.

    RPY_PROGRAM_READ raises ABAPApplicationError with key 'NOT_FOUND' on
    missing objects. We translate that to None for clean caller branching.
    Use ONLY_SOURCE='X' to keep the probe payload tiny — we only need
    PROG_INF for existence + program type.
    """
    from pyrfc import ABAPApplicationError

    try:
        result = conn.call(
            "RPY_PROGRAM_READ",
            PROGRAM_NAME=name,
            WITH_INCLUDELIST="",
            WITH_LOWERCASE="X",
            ONLY_SOURCE="X",
            READ_LATEST_VERSION="X",
        )
    except ABAPApplicationError as e:
        if "NOT_FOUND" in str(e).upper():
            return None
        raise
    return result.get("PROG_INF") or {}


def _decide_action(conn, name: str, program_type: str) -> tuple[str, dict]:
    """Decide create_program / create_include / update based on existence.

    Returns (action, info) where info carries fields needed by the caller:
        create_program: {"program_type": "1"|"M"|"S"|"J"|"K"|"F"}
        create_include: {}
        update:         {"program_type": <existing PROG_TYPE>}
    The title for UPDATE is fetched by `_read_title` (see Task 8) — it lives
    in TRDIRT, not in RPY_PROG.
    """
    existing = _probe(conn, name)
    if existing is None:
        if program_type.upper() == "I":
            return ("create_include", {})
        return ("create_program", {"program_type": program_type.upper()})
    return (
        "update",
        {"program_type": (existing.get("PROG_TYPE") or "").strip()},
    )
