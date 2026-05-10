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

import keyring

from connection import get_connection, SERVICE_NAME
from timeout import with_timeout, RFCTimeout
from where_clause import chunk_where

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


class NoOpenTransport(Exception):
    """No modifiable Workbench/Customizing TR found for the user."""


def _resolve_transport(conn, user: str) -> str:
    """Return the most recent open TR (Workbench/Customizing) for `user`.

    Raises NoOpenTransport if none exists.
    """
    user = user.upper()
    where = (
        "STATUS IN ('D','L') AND "
        f"AS4USER EQ '{user}' AND "
        "TRFUNCTION IN ('K','S')"
    )
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="E070",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "TRKORR"},
            {"FIELDNAME": "AS4DATE"},
            {"FIELDNAME": "AS4TIME"},
        ],
        OPTIONS=[{"TEXT": c} for c in chunk_where(where)],
        ROWCOUNT=200,
    )
    rows = []
    for line in result.get("DATA", []):
        parts = [p.strip() for p in line["WA"].split("|")]
        if len(parts) >= 3 and parts[0]:
            rows.append((parts[0], parts[1], parts[2]))
    if not rows:
        raise NoOpenTransport(
            f"No modifiable workbench/customizing transport found for user {user}. "
            "Create one in SE09 or pass 'transport' explicitly."
        )
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return rows[0][0]


def _post_syntax_check(name: str, kind: str) -> dict:
    """Indirection so tests can monkeypatch without crossing into syntax module."""
    from tools.syntax import _syntax_check_impl
    return _syntax_check_impl(name, kind)


def _read_title(conn, name: str) -> str:
    """Return the existing report title from TRDIRT for the connection's logon language.

    Falls back to any non-empty title row, then to empty string. RPY_INCLUDE_UPDATE
    requires TITLE_STRING to be passed; we re-supply the existing title so an
    update doesn't blank it.
    """
    lang = (keyring.get_password(SERVICE_NAME, "lang") or "EN").upper()[:1]
    where = f"NAME EQ '{name}'"
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="TRDIRT",
        DELIMITER="|",
        FIELDS=[{"FIELDNAME": "TEXT"}, {"FIELDNAME": "SPRSL"}],
        OPTIONS=[{"TEXT": where}],
        ROWCOUNT=20,
    )
    rows = []
    for line in result.get("DATA", []):
        parts = [p.strip() for p in line["WA"].split("|")]
        if len(parts) >= 1 and parts[0]:
            rows.append((parts[0], parts[1] if len(parts) > 1 else ""))
    # Prefer the row matching the connection language.
    for text, sprsl in rows:
        if sprsl == lang:
            return text
    return rows[0][0] if rows else ""


_SUBC_TO_KIND = {
    "1": "program",
    "I": "include",
    "M": "modulepool",
    "S": "subroutine_pool",
    "J": "interface_pool",
    "K": "class_pool",
    "F": "function_group",
}


def _upload_program_impl(
    name: str,
    source_file: str,
    transport: str | None,
    devclass: str | None,
    description: str | None,
    program_type: str,
) -> dict:
    name = name.upper()
    program_type = (program_type or "1").upper()

    # 1. Read + validate source.
    with open(source_file, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    bad = _validate_lines(lines)
    if bad:
        return {
            "error": "LineTooLong",
            "detail": f"Source lines exceed {ABAP_LINE_MAX} chars at line(s): "
            + ", ".join(str(b) for b in bad),
        }

    conn = get_connection()
    try:
        # 2. Probe + branch.
        action, info = _decide_action(conn, name, program_type)

        # 3. Validate create-only args.
        if action in ("create_program", "create_include"):
            if not devclass:
                return {
                    "error": "MissingArgument",
                    "detail": "devclass is required when creating a new object",
                }
            if not description:
                return {
                    "error": "MissingArgument",
                    "detail": "description is required when creating a new object",
                }

        # 4. Resolve transport unless $TMP / unless caller passed one.
        is_tmp = (devclass or "").upper() == "$TMP"
        if transport is None and not is_tmp:
            user = keyring.get_password(SERVICE_NAME, "user") or ""
            transport = _resolve_transport(conn, user)
        elif transport is None and is_tmp:
            transport = ""

        src_rows = _to_source_extended(lines)

        # 5. Call the right write FM.
        if action == "create_program":
            conn.call(
                "RPY_PROGRAM_INSERT",
                PROGRAM_NAME=name,
                PROGRAM_TYPE=program_type,
                TITLE_STRING=description,
                DEVELOPMENT_CLASS=(devclass or "").upper(),
                TRANSPORT_NUMBER=transport,
                SUPPRESS_DIALOG="X",
                SOURCE_EXTENDED=src_rows,
            )
            kind_out = _SUBC_TO_KIND.get(program_type, "program")
        elif action == "create_include":
            conn.call(
                "RPY_INCLUDE_INSERT",
                INCLUDE_NAME=name,
                TITLE_STRING=description,
                DEVELOPMENT_CLASS=(devclass or "").upper(),
                TRANSPORT_NUMBER=transport,
                SOURCE_EXTENDED=src_rows,
            )
            kind_out = "include"
        else:  # update
            existing_title = _read_title(conn, name)
            conn.call(
                "RPY_INCLUDE_UPDATE",
                INCLUDE_NAME=name,
                TITLE_STRING=existing_title,
                TRANSPORT_NUMBER=transport,
                SOURCE_EXTENDED=src_rows,
            )
            kind_out = _SUBC_TO_KIND.get(info.get("program_type", "1"), "program")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    syntax = _post_syntax_check(name, kind_out)
    return {
        "action": "created" if action.startswith("create") else "updated",
        "name": name,
        "kind": kind_out,
        "transport": transport or "",
        "devclass": (devclass or "").upper(),
        "lines_uploaded": len(lines),
        "syntax": syntax,
    }


def register(mcp):
    @mcp.tool()
    def upload_program(
        name: str,
        source_file: str,
        transport: str | None = None,
        devclass: str | None = None,
        description: str | None = None,
        program_type: str = "1",
    ) -> dict:
        """Upload an ABAP program or include via RFC, auto-activating it.

        Routes through:
          - RPY_PROGRAM_INSERT   for new executable / module pool / class pool / etc.
          - RPY_INCLUDE_INSERT   for new includes (program_type='I')
          - RPY_INCLUDE_UPDATE   for existing objects (programs and includes alike)

        WHY RPY_INCLUDE_UPDATE for both: RPY_PROGRAM_UPDATE is NOT RFC-enabled
        on current S/4 releases, but RPY_INCLUDE_UPDATE operates on TRDIR by
        name and writes via INSERT REPORT … STATE 'A' regardless of SUBC. So
        it covers programs too. Verified by reading the FM source on DS4.

        After the upload completes, runs `syntax_check_rfc` automatically and
        returns the result so the caller sees breakage in the same response.

        IMPORTANT: write tool — Claude must summarize parameters and wait for
        explicit user approval before calling.

        Args:
            name: Program or include name.
            source_file: Local path to the .abap source file (UTF-8).
            transport: Existing TR. If omitted, the most recent open
                       Workbench/Customizing TR for the connection user is
                       resolved from E070. Ignored when devclass='$TMP'.
            devclass: Required when creating. Use '$TMP' for local objects.
            description: Title — required when creating. Re-supplied
                         automatically on updates from the existing TRDIR title.
            program_type: SAP TRDIR-SUBC. '1'=executable (default), 'I'=include,
                          'M'=module pool, 'S'=subroutine pool, 'J'=interface
                          pool, 'K'=class pool, 'F'=function group. Used only
                          when creating.

        Returns:
            {action, name, kind, transport, devclass, lines_uploaded, syntax}
            on success, or {error, detail} on failure.
        """
        from pyrfc import LogonError, CommunicationError, ABAPApplicationError
        try:
            return with_timeout(
                _upload_program_impl,
                name, source_file, transport, devclass, description, program_type,
            )
        except RFCTimeout as e:
            return {"error": "Timeout", "detail": str(e)}
        except NoOpenTransport as e:
            return {"error": "NoOpenTransport", "detail": str(e)}
        except LogonError as e:
            return {"error": "LogonError", "detail": str(e)}
        except CommunicationError as e:
            return {"error": "CommunicationError", "detail": str(e)}
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except FileNotFoundError as e:
            return {"error": "FileNotFound", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
