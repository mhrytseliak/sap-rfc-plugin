from connection import get_connection


_SEL_PREFIX = " " * 8


def _logon_language(conn) -> str:
    # RESPTEXT layout: "... Logon_Data: <client>/<user>/<langu>"
    r = conn.call("STFC_CONNECTION", REQUTEXT="")
    resp = r.get("RESPTEXT", "")
    token = resp.rsplit("/", 1)[-1].strip() if "/" in resp else ""
    return token[:1] or "E"


def _resolve_language(conn, program: str, override: str | None) -> str:
    if override:
        return override.upper()[:1]
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="TRDIR",
        DELIMITER="|",
        FIELDS=[{"FIELDNAME": "RLOAD"}],
        OPTIONS=[{"TEXT": f"NAME EQ '{program}'"}],
        ROWCOUNT=1,
    )
    for line in result.get("DATA", []):
        rload = line["WA"].strip()
        if rload:
            return rload
    return _logon_language(conn)


def _lookup_devclass(conn, program: str) -> str:
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="TADIR",
        DELIMITER="|",
        FIELDS=[{"FIELDNAME": "DEVCLASS"}],
        OPTIONS=[{"TEXT": f"PGMID EQ 'R3TR' AND OBJECT EQ 'PROG' AND OBJ_NAME EQ '{program}'"}],
        ROWCOUNT=1,
    )
    for line in result.get("DATA", []):
        dc = line["WA"].strip()
        if dc:
            return dc
    return ""


def _read_pool(conn, program: str, language: str) -> list[dict]:
    result = conn.call("RPY_PROGRAM_READ", PROGRAM_NAME=program, LANGUAGE=language)
    return result.get("TEXTELEMENTS", []) or []


def _to_external(entries: list[dict]) -> list[dict]:
    out = []
    for row in entries:
        entry = row.get("ENTRY", "")
        if row.get("ID") == "S" and entry.startswith(_SEL_PREFIX):
            entry = entry[len(_SEL_PREFIX):]
        out.append({
            "id": row.get("ID", ""),
            "key": row.get("KEY", "").rstrip(),
            "entry": entry,
            "length": row.get("LENGTH", 0),
        })
    return out


def _to_textpool(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        eid = (e.get("id") or "").upper()
        key = (e.get("key") or "").upper()
        text = e.get("entry") or ""
        if eid == "S":
            text = _SEL_PREFIX + text
        out.append({
            "ID": eid,
            "KEY": key,
            "ENTRY": text,
            "LENGTH": len(text),
        })
    return out


def _merge(current: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    by_key: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for row in current:
        k = (row["ID"], row["KEY"])
        by_key[k] = row
        order.append(k)
    added = replaced = 0
    for row in incoming:
        k = (row["ID"], row["KEY"])
        if k in by_key:
            replaced += 1
        else:
            added += 1
            order.append(k)
        by_key[k] = row
    return [by_key[k] for k in order], added, replaced


def register(mcp):
    @mcp.tool()
    def read_text_pool(name: str, language: str | None = None) -> dict:
        """Read an ABAP program's text pool (title, text symbols, selection texts).

        Uses RFC `RPY_PROGRAM_READ`. Language is auto-detected from the program's
        master language (TRDIR.RLOAD) when not given; falls back to logon language.

        Entry shape — flat list with ID legend:
          * `R` = report title. `key` empty.
          * `I` = text symbol (TEXT-001). `key` is a 3-char id like `001`.
          * `S` = selection text. `key` is the SELECT-OPTIONS / PARAMETERS name
            (e.g. `P_BUKRS`). The 8-space alignment prefix used internally by
            SAP is stripped — `entry` is the raw displayable text.

        Args:
            name: Program name (upper-cased automatically).
            language: Single-char SY-LANGU override (`E`, `D`, `U`, ...). When
                      omitted, resolved from TRDIR.RLOAD, then logon language.

        Returns: {program, language, count, entries: [{id, key, entry, length}]}.
        """
        from pyrfc import ABAPApplicationError
        try:
            conn = get_connection()
            program = name.upper()
            lang = _resolve_language(conn, program, language)
            raw = _read_pool(conn, program, lang)
            conn.close()
            entries = _to_external(raw)
            return {
                "program": program,
                "language": lang,
                "count": len(entries),
                "entries": entries,
            }
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}

    @mcp.tool()
    def update_text_pool(
        name: str,
        entries: list[dict],
        transport: str,
        language: str | None = None,
    ) -> dict:
        """Write / merge an ABAP program's text pool via RFC `RPY_TEXTELEMENTS_INSERT`.

        Read-merge-write semantics: existing entries are preserved, incoming
        entries are overlaid by (id, key). To delete an entry, read the pool,
        strip it client-side, pass the full remaining list — or use a separate
        cleanup path (not implemented yet).

        Selection-text 8-space prefix is re-applied automatically.
        Language defaults to TRDIR.RLOAD (program master language), then logon.
        Devclass is looked up from TADIR.

        Args:
            name: Program name.
            entries: List of `{id, key, entry}`. `id` must be `R` (title — key
                empty), `I` (text symbol — key is 3-char id), or `S` (sel-text —
                key is parameter name). `entry` is raw text without SAP's
                alignment padding.
            transport: Transport request / task number (required, same as
                `update_source`).
            language: SY-LANGU override. Usually omit.

        Returns: {ok, program, language, rows_written, added, replaced}.
        """
        from pyrfc import ABAPApplicationError
        try:
            conn = get_connection()
            program = name.upper()
            lang = _resolve_language(conn, program, language)
            devclass = _lookup_devclass(conn, program)
            if not devclass:
                conn.close()
                return {"error": "ProgramNotFound", "detail": f"{program} not in TADIR"}

            current = _read_pool(conn, program, lang)
            incoming = _to_textpool(entries)
            merged, added, replaced = _merge(current, incoming)

            # All mandatory IMPORT params must be passed explicitly — pyrfc
            # does not fall back to ABAP DEFAULTs declared on the FM, and an
            # empty LANGUAGE silently causes `INSERT TEXTPOOL ... LANGUAGE ''`
            # to write nothing (no exception raised).
            conn.call(
                "RPY_TEXTELEMENTS_INSERT",
                PROGRAM_NAME=program,
                LANGUAGE=lang,
                R2_FLAG=" ",
                TEMPORARY=" ",
                DEVELOPMENT_CLASS=devclass,
                TRANSPORT_NUMBER=transport.upper(),
                SUPPRESS_DIALOG="X",
                SOURCE=merged,
            )
            conn.close()
            return {
                "ok": True,
                "program": program,
                "language": lang,
                "rows_written": len(merged),
                "added": added,
                "replaced": replaced,
            }
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
