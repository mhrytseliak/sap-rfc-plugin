"""adt-mcp: ping - verify ADT URL + auth."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from adt_client import ADTClient
from errors import ADTError, ADTNotAvailable


def _ping_impl() -> dict:
    try:
        with ADTClient() as c:
            r = c.get("/sap/bc/adt/core/discovery")
            count = 0
            try:
                root = ET.fromstring(r.text)
                for el in root.iter():
                    if el.tag.rsplit("}", 1)[-1] == "collection":
                        count += 1
            except ET.ParseError:
                pass
            return {
                "status": "ok",
                "base_url": c.base,
                "core_discovery_entries": count,
            }
    except ADTNotAvailable as e:
        return {"error": "ADTNotAvailable", "detail": str(e), "tried": e.tried}
    except ADTError as e:
        return {"error": "ADTError", "http_status": e.status,
                "code": e.code, "message": e.message}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}


def register(mcp):
    @mcp.tool()
    def ping() -> dict:
        """Verify ADT connectivity.

        Discovers the ADT base URL (via cache or RFC ICM_GET_INFO), fetches the
        core/discovery document, and confirms auth works. Call this first after
        /sap-connect if you plan to use any other adt-mcp tool.

        Returns: {status: 'ok', base_url, core_discovery_entries} on success,
        {error: 'ADTNotAvailable' | 'ADTError', ...} on failure.
        'ADTNotAvailable' is the signal to fall back to manual stage 7.
        """
        return _ping_impl()
