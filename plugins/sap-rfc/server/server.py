import atexit
import shutil
import tempfile
import textwrap
from pathlib import Path

import keyring
from fastmcp import FastMCP

SERVICE_NAME = "sap-rfc"
KEYRING_KEYS = ("ashost", "sysnr", "client", "user", "passwd", "lang", "saprouter")

mcp = FastMCP("sap-rfc")

MAX_ROWS = 20

CACHE_DIR = Path(tempfile.mkdtemp(prefix="sap-rfc-"))
atexit.register(shutil.rmtree, str(CACHE_DIR), True)


def _write_source(name: str, source: str) -> dict:
    """Write source to cache file, return metadata."""
    path = CACHE_DIR / f"{name}.abap"
    path.write_text(source, encoding="utf-8")
    lines = source.count("\n") + 1
    return {"source_file": str(path), "line_count": lines}


def get_connection():
    """Create a new pyrfc connection from OS keyring."""
    from pyrfc import Connection

    def _get(key):
        return keyring.get_password(SERVICE_NAME, key)

    ashost = _get("ashost")
    if not ashost:
        raise RuntimeError(
            "SAP credentials not found in keyring. Run /sap-connect to configure."
        )

    params = {
        "ashost": ashost,
        "sysnr": _get("sysnr") or "00",
        "client": _get("client") or "100",
        "user": _get("user"),
        "passwd": _get("passwd"),
        "lang": _get("lang") or "EN",
    }
    saprouter = _get("saprouter")
    if saprouter:
        params["saprouter"] = saprouter
    return Connection(**params)


@mcp.tool()
def sap_ping() -> dict:
    """Test SAP connection. Returns system info if successful."""
    from pyrfc import LogonError, CommunicationError
    try:
        conn = get_connection()
        conn.call("RFC_PING")
        sys_info = conn.call("RFC_SYSTEM_INFO")
        info = sys_info["RFCSI_EXPORT"]
        conn.close()
        return {
            "status": "ok",
            "system_id": info.get("RFCSYSID", ""),
            "host": info.get("RFCHOST", ""),
            "database": info.get("RFCDBSYS", ""),
            "sap_release": info.get("RFCSAPRL", ""),
            "s4_hana": sys_info.get("S4_HANA", ""),
        }
    except LogonError as e:
        return {"status": "error", "type": "LogonError", "message": str(e)}
    except CommunicationError as e:
        return {"status": "error", "type": "CommunicationError", "message": str(e)}
    except Exception as e:
        return {"status": "error", "type": type(e).__name__, "message": str(e)}


@mcp.tool()
def sap_get_fields(
    table_name: str,
    fields: list[str] | None = None,
    keys_only: bool = False,
) -> list[dict]:
    """Get field definitions for a SAP table. Use fields parameter to filter specific fields. Use keys_only=True for key fields only."""
    from pyrfc import ABAPApplicationError
    try:
        conn = get_connection()
        result = conn.call("DDIF_FIELDINFO_GET", TABNAME=table_name.upper())
        conn.close()

        field_filter = {f.upper() for f in fields} if fields else None
        out = []
        for f in result.get("DFIES_TAB", []):
            if keys_only and f.get("KEYFLAG") != "X":
                continue
            if field_filter and f["FIELDNAME"] not in field_filter:
                continue
            out.append({
                "field": f["FIELDNAME"],
                "type": f["DATATYPE"],
                "length": f["LENG"],
                "decimals": f["DECIMALS"],
                "key": f["KEYFLAG"] == "X",
                "description": f.get("FIELDTEXT", ""),
            })
        return out

    except ABAPApplicationError as e:
        return [{"error": f"Table '{table_name}' not found or no authorization", "detail": str(e)}]
    except Exception as e:
        return [{"error": type(e).__name__, "detail": str(e)}]


@mcp.tool()
def sap_read_table(
    table_name: str,
    fields: list[str] | None = None,
    where: str | None = None,
    max_rows: int = 20,
) -> list[dict]:
    """Read rows from a SAP table. Max 20 rows. Fields: list of field names. Where: ABAP WHERE clause string."""
    from pyrfc import ABAPApplicationError

    # Hard limit
    if max_rows > MAX_ROWS:
        max_rows = MAX_ROWS

    try:
        conn = get_connection()

        params = {
            "QUERY_TABLE": table_name.upper(),
            "DELIMITER": "|",
            "ROWCOUNT": max_rows,
        }

        if fields:
            params["FIELDS"] = [{"FIELDNAME": f.upper()} for f in fields]

        if where:
            # Split long WHERE into 72-char chunks (SAP limit)
            chunks = textwrap.wrap(where, 72)
            params["OPTIONS"] = [{"TEXT": c} for c in chunks]

        result = conn.call("RFC_READ_TABLE", **params)
        conn.close()

        # Parse response
        field_names = [f["FIELDNAME"] for f in result["FIELDS"]]
        rows = []
        for line in result["DATA"]:
            values = [v.strip() for v in line["WA"].split("|")]
            rows.append(dict(zip(field_names, values)))

        return rows

    except ABAPApplicationError as e:
        return [{"error": f"ABAP error on table '{table_name}'", "detail": str(e)}]
    except Exception as e:
        return [{"error": type(e).__name__, "detail": str(e)}]


@mcp.tool()
def sap_read_program(
    program_name: str,
    with_includes: bool = True,
) -> dict:
    """Read ABAP program source code, include list, and text elements."""
    try:
        conn = get_connection()
        result = conn.call(
            "RPY_PROGRAM_READ",
            PROGRAM_NAME=program_name.upper(),
            WITH_INCLUDELIST="X" if with_includes else "",
            WITH_LOWERCASE="X",
        )
        conn.close()

        # SOURCE_EXTENDED (ABAPTXT255): field LINE (CHAR 255)
        source_lines = [line.get("LINE", "") for line in result.get("SOURCE_EXTENDED", result.get("SOURCE", []))]

        # INCLUDE_TAB (RPY_REPO): fields INCLNAME, TITLE
        includes = [
            {"name": inc.get("INCLNAME", "").strip(), "title": inc.get("TITLE", "").strip()}
            for inc in result.get("INCLUDE_TAB", [])
            if inc.get("INCLNAME", "").strip()
        ]

        # TEXTELEMENTS (TEXTPOOL): fields ID, KEY, ENTRY
        # ID: I=text symbol, R=title, S=selection text
        texts = [
            {"id": t.get("ID", ""), "key": t.get("KEY", "").strip(), "entry": t.get("ENTRY", "").strip()}
            for t in result.get("TEXTELEMENTS", [])
        ]

        return {
            "program": program_name.upper(),
            **_write_source(program_name.upper(), "\n".join(source_lines)),
            "includes": includes,
            "text_elements": texts,
        }

    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def sap_read_fm_interface(function_name: str, with_source: bool = False) -> dict:
    """Get function module interface and optionally source code. Uses RPY_FUNCTIONMODULE_READ."""
    from pyrfc import ABAPApplicationError
    try:
        conn = get_connection()
        result = conn.call(
            "RPY_FUNCTIONMODULE_READ",
            FUNCTIONNAME=function_name.upper(),
        )
        conn.close()

        # Parse parameters from IMPORT_PARAMETER, EXPORT_PARAMETER, CHANGING_PARAMETER, TABLES_PARAMETER
        def parse_params(table, direction):
            out = []
            for p in result.get(table, []):
                out.append({
                    "name": p.get("PARAMETER", ""),
                    "type": p.get("DBFIELD", "") or p.get("TYP", "") or p.get("EXID", ""),
                    "optional": p.get("OPTIONAL", "") == "X",
                    "default": p.get("DEFAULT", "").strip(),
                    "description": p.get("STEXT", ""),
                })
            return out

        params = {
            "import": parse_params("IMPORT_PARAMETER", "I"),
            "export": parse_params("EXPORT_PARAMETER", "E"),
            "changing": parse_params("CHANGING_PARAMETER", "C"),
            "tables": parse_params("TABLES_PARAMETER", "T"),
            "exception": [
                {"name": e.get("EXCEPTION", ""), "description": e.get("STEXT", "")}
                for e in result.get("EXCEPTION_LIST", [])
            ],
        }

        out = {
            "function_module": function_name.upper(),
            "function_pool": result.get("FUNCTION_POOL", "").strip(),
            "short_text": result.get("SHORT_TEXT", "").strip(),
            "rfc_enabled": result.get("REMOTE_CALL", "") == "R",
            "parameters": params,
        }

        if with_source:
            source_lines = [line.get("LINE", "") for line in result.get("SOURCE", [])]
            out.update(_write_source(function_name.upper(), "\n".join(source_lines)))

        return out

    except ABAPApplicationError as e:
        return {"error": f"FM '{function_name}' not found", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def sap_read_class(
    class_name: str,
    method_name: str | None = None,
) -> dict:
    """Read ABAP class methods. Without method_name: lists all methods. With method_name: returns method source code."""
    from pyrfc import ABAPApplicationError
    try:
        conn = get_connection()
        cls = class_name.upper()

        # Get method list from TMDIR
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="TMDIR",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "METHODNAME"},
                {"FIELDNAME": "METHODINDX"},
            ],
            OPTIONS=[{"TEXT": f"CLASSNAME EQ '{cls}'"}],
            ROWCOUNT=100,
        )

        methods = {}
        for line in result["DATA"]:
            values = [v.strip() for v in line["WA"].split("|")]
            name, index = values[0], values[1]
            if name:  # skip empty (class constructor pool entry)
                methods[name] = index

        if not methods:
            conn.close()
            return {"error": f"Class '{cls}' not found or has no methods"}

        # List mode: return method names only
        if not method_name:
            conn.close()
            return {
                "class": cls,
                "methods": sorted(methods.keys()),
            }

        # Read mode: get specific method source
        mtd = method_name.upper()
        if mtd not in methods:
            conn.close()
            return {"error": f"Method '{mtd}' not found in class '{cls}'",
                    "available_methods": sorted(methods.keys())}

        # Build include name: class padded to 30 chars with '=' + CM + 3-digit index
        padded = cls.ljust(30, "=")
        idx = str(int(methods[mtd])).zfill(3)
        include = f"{padded}CM{idx}"

        prog_result = conn.call(
            "RPY_PROGRAM_READ",
            PROGRAM_NAME=include,
            WITH_LOWERCASE="X",
        )
        conn.close()

        source_lines = [
            line.get("LINE", "")
            for line in prog_result.get("SOURCE_EXTENDED", prog_result.get("SOURCE", []))
        ]

        source_text = "\n".join(source_lines)
        return {
            "class": cls,
            "method": mtd,
            "include": include,
            **_write_source(f"{cls}.{mtd}", source_text),
        }

    except ABAPApplicationError as e:
        return {"error": "ABAPApplicationError", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


@mcp.tool()
def sap_update_program(
    program_name: str,
    source: str | None = None,
    source_file: str | None = None,
    title: str | None = None,
    save_inactive: bool = True,
) -> dict:
    """Update ABAP program/include source code in SAP.
    Provide source as string OR source_file as path to .abap file.
    Saves as inactive by default to prevent runtime dumps from syntax errors.
    Set save_inactive=False to activate immediately."""
    from pyrfc import ABAPApplicationError

    if source_file:
        source = Path(source_file).read_text(encoding="utf-8")
    if not source:
        return {"status": "error", "error": "ValueError",
                "message": "Provide either source or source_file"}

    try:
        conn = get_connection()
        name = program_name.upper()

        if not title:
            try:
                prog = conn.call("RPY_PROGRAM_READ", PROGRAM_NAME=name)
                title = prog.get("PROG_INF", {}).get("TITLE", name)
            except Exception:
                title = name

        source_lines = [{"LINE": line} for line in source.split("\n")]

        params = {
            "INCLUDE_NAME": name,
            "TITLE_STRING": title,
            "SOURCE_EXTENDED": source_lines,
        }
        if save_inactive:
            params["SAVE_INACTIVE"] = "I"

        conn.call("RPY_INCLUDE_UPDATE", **params)
        conn.close()

        return {"status": "ok", "program": name, "inactive": save_inactive}

    except ABAPApplicationError as e:
        return {"status": "error", "error": e.key, "message": e.message}
    except Exception as e:
        return {"status": "error", "error": type(e).__name__, "message": str(e)}


if __name__ == "__main__":
    mcp.run()
