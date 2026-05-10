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
