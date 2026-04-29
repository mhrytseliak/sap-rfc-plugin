"""Shared OS keyring key list for sap-rfc skills.

Single source of truth — imported by connect.py and disconnect.py.
Add/remove keys here, not in individual skills.
"""

SERVICE = "sap-rfc"

ALL_KEYS = (
    "ashost",
    "sysnr",
    "client",
    "user",
    "passwd",
    "lang",
    "saprouter",
    "workspace",
    "adt_url",
    "adt_verify_tls",
    "adt_timeout",
)
