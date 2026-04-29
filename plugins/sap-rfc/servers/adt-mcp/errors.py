"""Exception hierarchy shared across adt-mcp tools."""
from __future__ import annotations

import xml.etree.ElementTree as ET


class ADTNotAvailable(Exception):
    """ADT base URL could not be discovered or is unreachable.

    Surfaced by tools as {'error': 'ADTNotAvailable', ...}. Signals Claude to
    fall back to asking the user to perform stage 7 in SAP GUI.
    """

    def __init__(self, tried: list[dict]):
        self.tried = tried
        super().__init__(f"ADT not reachable. Tried: {tried}")


class ADTError(Exception):
    """Non-2xx HTTP response from an ADT endpoint."""

    def __init__(self, status: int, code: str, message: str, exc_type: str = ""):
        self.status = status
        self.code = code
        self.message = message
        self.type = exc_type
        super().__init__(f"[{status}] {code}: {message}")

    @classmethod
    def from_response(cls, r) -> "ADTError":
        code, message, exc_type = "", r.text.strip(), ""
        ctype = r.headers.get("Content-Type", "")
        if "xml" in ctype and r.text.lstrip().startswith("<"):
            try:
                root = ET.fromstring(r.text)
                local = lambda e: e.tag.rsplit("}", 1)[-1]
                for child in root.iter():
                    tag = local(child)
                    if tag == "localizedMessage" and child.text:
                        message = child.text.strip()
                    elif tag == "type" and child.text:
                        code = child.text.strip()
                    elif tag == "namespace" and child.text:
                        exc_type = child.text.strip()
            except ET.ParseError:
                pass
        return cls(r.status_code, code, message, exc_type)
