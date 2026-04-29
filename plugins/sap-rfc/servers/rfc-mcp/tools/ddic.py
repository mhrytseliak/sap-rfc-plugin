from connection import get_connection
from where_clause import chunk_where

MAX_ROWS = 20


def register(mcp):
    @mcp.tool()
    def get_table_structure(table: str) -> dict:
        """Get field definitions (schema) of a SAP DDIC table or structure.

        Use BEFORE `read_table` when you don't know the field names, or when you
        need to know which fields are keys / data types / lengths. Cheaper and
        more informative than guessing fields and reading data.

        Args:
            table: DDIC table or structure name (e.g. 'T000', 'MARA', 'BSEG').

        Returns: {table, fields: [{field, type, length, decimals, key, description}]}.
        """
        from pyrfc import ABAPApplicationError

        try:
            conn = get_connection()
            result = conn.call("DDIF_FIELDINFO_GET", TABNAME=table.upper())
            conn.close()
            fields = []
            for f in result.get("DFIES_TAB", []):
                entry = {
                    "field": f["FIELDNAME"],
                    "type": f["DATATYPE"],
                    "length": int(f["LENG"]),
                }
                dec = int(f["DECIMALS"])
                if dec:
                    entry["decimals"] = dec
                if f["KEYFLAG"] == "X":
                    entry["key"] = True
                desc = f.get("FIELDTEXT", "").strip()
                if desc:
                    entry["description"] = desc
                fields.append(entry)
            return {"table": table.upper(), "fields": fields}
        except ABAPApplicationError as e:
            return {
                "error": f"Table '{table}' not found or no authorization",
                "detail": str(e),
            }
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}

    @mcp.tool()
    def read_table(
        table: str,
        fields: list[str] | None = None,
        where: str | None = None,
        max_rows: int = MAX_ROWS,
    ) -> dict:
        """Read rows from a SAP DDIC table via RFC_READ_TABLE. HARD CAP: 20 rows.

        Always pass `fields` — without it RFC_READ_TABLE returns ALL columns
        concatenated and may overflow the 512-char row buffer. If you don't know
        the fields, call `get_table_structure` first.

        `where` uses ABAP/Open-SQL syntax (single-quoted literals, AND/OR), e.g.
        `MANDT EQ '100' AND BUKRS LIKE 'Z%'`. Long clauses are auto-chunked to
        72-char lines (RFC_READ_TABLE limit).

        Not for high-volume extraction — this is exploration. For bulk reads,
        write a custom RFC FM. Pooled/cluster tables (BSEG, KOCLU, etc.) are NOT
        supported by RFC_READ_TABLE; use a transparent table or a CDS view.

        Returns: {table, fields, rows: [{...}]}.
        """
        from pyrfc import ABAPApplicationError

        max_rows = min(max_rows, MAX_ROWS)
        try:
            conn = get_connection()
            params = {
                "QUERY_TABLE": table.upper(),
                "DELIMITER": "|",
                "ROWCOUNT": max_rows,
            }
            if fields:
                params["FIELDS"] = [{"FIELDNAME": f.upper()} for f in fields]
            if where:
                params["OPTIONS"] = [{"TEXT": c} for c in chunk_where(where)]
            result = conn.call("RFC_READ_TABLE", **params)
            conn.close()
            field_names = [f["FIELDNAME"] for f in result["FIELDS"]]
            rows = [
                dict(
                    zip(
                        field_names,
                        [v.strip() for v in line["WA"].split("|")],
                    )
                )
                for line in result["DATA"]
            ]
            return {"table": table.upper(), "rows": rows}
        except ABAPApplicationError as e:
            return {"error": f"ABAP error on table '{table}'", "detail": str(e)}
        except Exception as e:
            return {"error": type(e).__name__, "detail": str(e)}
