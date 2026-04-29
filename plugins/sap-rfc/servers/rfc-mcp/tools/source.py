from connection import get_connection
from cache import write_source
from where_clause import chunk_where


def _read_program_lines(conn, name: str) -> list[str]:
    result = conn.call(
        "RPY_PROGRAM_READ",
        PROGRAM_NAME=name,
        WITH_INCLUDELIST="",
        WITH_LOWERCASE="X",
        READ_LATEST_VERSION="X",
    )
    return [l.get("LINE", "") for l in result.get("SOURCE_EXTENDED", result.get("SOURCE", []))]


def _read_class_method(conn, cls: str, method: str) -> dict:
    cls = cls.upper()
    method = method.upper()
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="TMDIR",
        DELIMITER="|",
        FIELDS=[{"FIELDNAME": "METHODNAME"}, {"FIELDNAME": "METHODINDX"}],
        OPTIONS=[{"TEXT": f"CLASSNAME EQ '{cls}'"}],
        ROWCOUNT=200,
    )
    methods = {}
    for line in result["DATA"]:
        values = [v.strip() for v in line["WA"].split("|")]
        if values[0]:
            methods[values[0]] = values[1]
    if not methods:
        return {"error": f"Class '{cls}' has no methods or not found"}
    if method not in methods:
        return {
            "error": f"Method '{method}' not found in class '{cls}'",
            "available_methods": sorted(methods.keys()),
        }
    include = f"{cls.ljust(30, '=')}CM{int(methods[method]):03d}"
    lines = _read_program_lines(conn, include)
    return {
        "class": cls,
        "method": method,
        "include": include,
        **write_source(f"{cls}.{method}", "\n".join(lines)),
    }


def register(mcp):
    @mcp.tool()
    def read_source(name: str, type: str = "program", method: str | None = None) -> dict:
        """Read ABAP source code (program, include, or class method).

        The source is written to a `.abap` file and the path is returned — open
        it with the Read tool when you need the content. This keeps tool
        responses compact even for large programs.

        Workflow for classes:
            1. Call with `type='class'` and no `method` → returns the method list.
            2. Call again with `method='METHOD_NAME'` → returns the source file.

        Args:
            name: Program / include / class name.
            type: 'program' (default — also use for reports and includes if you
                  know the name), 'include' (alias for program), 'class'.
            method: Required when type='class' AND you want method source. Omit
                    to list methods first.

        Returns:
            program/include: {name, type, source_file, line_count}
            class (no method): {class, methods: [...]}
            class (with method): {class, method, include, source_file, line_count}
        """
        from pyrfc import ABAPApplicationError
        try:
            conn = get_connection()
            t = type.lower()
            if t == "class":
                if not method:
                    result = conn.call(
                        "RFC_READ_TABLE",
                        QUERY_TABLE="TMDIR",
                        DELIMITER="|",
                        FIELDS=[{"FIELDNAME": "METHODNAME"}],
                        OPTIONS=[{"TEXT": f"CLASSNAME EQ '{name.upper()}'"}],
                        ROWCOUNT=200,
                    )
                    conn.close()
                    methods = sorted({line["WA"].strip() for line in result["DATA"] if line["WA"].strip()})
                    if not methods:
                        return {"error": f"Class '{name}' not found or has no methods"}
                    return {"class": name.upper(), "methods": methods}
                out = _read_class_method(conn, name, method)
                conn.close()
                return out
            lines = _read_program_lines(conn, name.upper())
            conn.close()
            return {
                "name": name.upper(),
                "type": t,
                **write_source(name.upper(), "\n".join(lines)),
            }
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}

    @mcp.tool()
    def search_objects(
        name_pattern: str,
        object_types: list[str] | None = None,
        devclass: str | None = None,
        max_rows: int = 100,
    ) -> dict:
        """Search the TADIR repository directory for ABAP objects.

        Use to discover what exists before drilling in with `read_source` —
        e.g. "find all Z reports in package ZSD" or "what classes start with
        CL_GUI_". Faster than guessing names.

        Args:
            name_pattern: SAP LIKE pattern with `%` wildcards. ALWAYS use upper
                          case (e.g. 'Z%REPORT%', 'CL_GUI_%'). Avoid bare '%' —
                          it scans the whole TADIR (slow + truncated at max_rows).
            object_types: TADIR OBJECT codes — common ones: 'PROG' (programs/
                          reports), 'CLAS' (classes), 'INTF' (interfaces),
                          'FUGR' (function groups), 'TABL' (tables), 'STRU'
                          (structures), 'DTEL' (data elements), 'DOMA' (domains),
                          'TRAN' (transactions), 'MSAG' (message classes), 'DEVC'
                          (packages). Pass a list to filter (default: all types).
            devclass: SAP package name (e.g. 'ZSD', '$TMP' for local objects).
            max_rows: Default 100. Increase only when you know the result fits.

        Returns: {count, results: [{OBJECT, OBJ_NAME, DEVCLASS, AUTHOR}]}.
        """
        from pyrfc import ABAPApplicationError
        try:
            conn = get_connection()
            clauses = [f"OBJ_NAME LIKE '{name_pattern.upper()}'"]
            if object_types:
                quoted = ",".join(f"'{t.upper()}'" for t in object_types)
                clauses.append(f"AND OBJECT IN ({quoted})")
            if devclass:
                clauses.append(f"AND DEVCLASS EQ '{devclass.upper()}'")
            where = " ".join(clauses)
            result = conn.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="TADIR",
                DELIMITER="|",
                FIELDS=[
                    {"FIELDNAME": "OBJECT"},
                    {"FIELDNAME": "OBJ_NAME"},
                    {"FIELDNAME": "DEVCLASS"},
                    {"FIELDNAME": "AUTHOR"},
                ],
                OPTIONS=[{"TEXT": c} for c in chunk_where(where)],
                ROWCOUNT=max_rows,
            )
            conn.close()
            field_names = [f["FIELDNAME"] for f in result["FIELDS"]]
            rows = [
                dict(zip(field_names, [v.strip() for v in line["WA"].split("|")]))
                for line in result["DATA"]
            ]
            return {"count": len(rows), "results": rows}
        except ABAPApplicationError as e:
            return {"error": "ABAPApplicationError", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
