"""adt-mcp: update_source - lock, PUT, unlock (always)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from adt_client import ADTClient, OBJECT_URI
from errors import ADTError, ADTNotAvailable

# Same cache dir rfc-mcp writes to (read_source / get_function_module_interface).
# Restricting reads to this tree means a confused tool call cannot exfiltrate
# arbitrary files (e.g. ~/.ssh/id_rsa) by uploading them to SAP as source.
_SAFE_ROOT = (Path(tempfile.gettempdir()) / "sap-rfc-cache").resolve()


def _is_inside_cache(p: Path) -> bool:
    try:
        p.resolve().relative_to(_SAFE_ROOT)
        return True
    except ValueError:
        return False


def _update_source_impl(name: str, kind: str, source_file: str,
                        transport: str, group: str | None = None,
                        title: str = "", devclass: str = "") -> dict:
    try:
        obj_uri = OBJECT_URI(name, kind, group=group)
        sf = Path(source_file)
        if not _is_inside_cache(sf):
            return {"error": "SourceFileOutsideCache",
                    "detail": f"source_file must live under {_SAFE_ROOT} "
                              "(write it via rfc-mcp.read_source or "
                              "get_function_module_interface first)"}
        try:
            raw = sf.read_bytes()
        except Exception as e:
            return {"error": "SourceFileRead",
                    "detail": f"{type(e).__name__}: {e}"}
        line_count = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)

        with ADTClient() as c:
            handle = c.lock(obj_uri)
            try:
                params = {"lockHandle": handle, "corrNr": transport}
                c.put(
                    obj_uri + "/source/main",
                    params=params,
                    data=raw,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
            finally:
                try:
                    c.unlock(obj_uri, handle)
                except Exception:
                    pass

        return {
            "status": "ok",
            "name": name.upper(),
            "kind": kind,
            "action": "updated",   # v1 handles existing-object updates only
            "transport": transport,
            "line_count": line_count,
        }
    except ADTNotAvailable as e:
        return {"error": "ADTNotAvailable", "detail": str(e)}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except ValueError as e:
        return {"error": "InvalidKind", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def update_source(name: str, kind: str, source_file: str,
                      transport: str, group: str | None = None,
                      title: str = "", devclass: str = "") -> dict:
        """Write ABAP source via ADT (stage 3/5).

        Three-step flow: LOCK (?accessMode=MODIFY) -> PUT source/main -> UNLOCK.
        Unlock always runs, even if PUT fails. Source stays INACTIVE - call
        `activate` afterwards to make it usable.

        ALWAYS confirm with the user before calling: show name, kind,
        transport, line count; only proceed on explicit approval.

        Object must already exist. Use `create_program` / `create_include` /
        `create_class` to create the empty header before uploading source.

        Args:
            name: Object name (upper-cased).
            kind: 'program', 'include', 'class', 'interface', 'fm'.
            source_file: Absolute path to .abap file with the new source.
            transport: Transport request (TRKORR) to carry the change.
            group: Required when kind='fm'.
            title / devclass: Accepted for forward compat; unused on update.

        Returns:
            {status, name, kind, action: 'updated', transport, line_count}
            or {error: 'ADTNotAvailable'|'ADTError'|'SourceFileRead'|
                      'InvalidKind', ...}.
        """
        return _update_source_impl(name, kind, source_file, transport,
                                   group, title, devclass)
