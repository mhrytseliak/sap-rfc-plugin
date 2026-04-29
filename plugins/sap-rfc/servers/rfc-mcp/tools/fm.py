from connection import get_connection
from cache import write_source
from timeout import with_timeout, RFCTimeout


def _parse_params(result, table_key):
    out = []
    for p in result.get(table_key, []):
        entry = {
            "name": p.get("PARAMETER", ""),
            "type": p.get("DBFIELD", "") or p.get("TYP", "") or p.get("EXID", ""),
        }
        if p.get("OPTIONAL", "") == "X":
            entry["optional"] = True
        default = p.get("DEFAULT", "").strip()
        if default:
            entry["default"] = default
        desc = p.get("STEXT", "").strip()
        if desc:
            entry["description"] = desc
        out.append(entry)
    return out


def _get_fm_interface_impl(name: str, with_source: bool) -> dict:
    conn = get_connection()
    try:
        # RPY_FUNCTIONMODULE_READ_NEW is the modern reader: NEW_SOURCE
        # returns full-width source lines (the old SOURCE table caps at
        # 72 chars and raises msg 180 on many current FMs like
        # RPY_TEXTELEMENTS_INSERT). NEW_SOURCE is declared CHANGING so
        # pyrfc requires it passed in as [].
        call_kwargs = {"FUNCTIONNAME": name.upper()}
        if with_source:
            call_kwargs["NEW_SOURCE"] = []
        result = conn.call("RPY_FUNCTIONMODULE_READ_NEW", **call_kwargs)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    params = {
        "import": _parse_params(result, "IMPORT_PARAMETER"),
        "export": _parse_params(result, "EXPORT_PARAMETER"),
        "changing": _parse_params(result, "CHANGING_PARAMETER"),
        "tables": _parse_params(result, "TABLES_PARAMETER"),
        "exception": [
            {"name": e.get("EXCEPTION", ""), "description": e.get("STEXT", "")}
            for e in result.get("EXCEPTION_LIST", [])
        ],
    }
    out = {
        "function_module": name.upper(),
        "function_pool": result.get("FUNCTION_POOL", "").strip(),
        "short_text": result.get("SHORT_TEXT", "").strip(),
        "rfc_enabled": result.get("REMOTE_CALL", "") == "R",
        "parameters": params,
    }
    if with_source:
        source_lines = result.get("NEW_SOURCE", []) or []
        out.update(write_source(name.upper(), "\n".join(source_lines)))
    return out


def register(mcp):
    @mcp.tool()
    def get_function_module_interface(name: str, with_source: bool = False) -> dict:
        """Get a function module's signature: parameters, exceptions, RFC-enabled flag.

        Use BEFORE writing a CALL FUNCTION (or `conn.call(...)`) to confirm
        param names / types / optionality. Cheaper than reading source.

        Set `with_source=True` only when you need the implementation logic —
        the source is dumped to a `.abap` cache file (open with Read tool).

        Returns: {function_module, function_pool, short_text, rfc_enabled,
        parameters: {import, export, changing, tables, exception},
        source_file?, line_count?}.
        """
        from pyrfc import ABAPApplicationError
        try:
            return with_timeout(_get_fm_interface_impl, name, with_source)
        except RFCTimeout as e:
            return {"error": "Timeout", "detail": str(e)}
        except ABAPApplicationError as e:
            return {"error": f"FM '{name}' not found", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
