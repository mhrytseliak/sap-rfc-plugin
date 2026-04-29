"""Launch SAP Logon dialog, read credentials from its stdout, write to OS keyring.

Called by the sap-connect skill. All credential handling stays in the dialog
subprocess + keyring writes — never in chat, never in shell command line.
"""
import argparse
import os
import re
import subprocess
import sys

import keyring


_MANGLED_ROUTER_RE = re.compile(r"^([HSWPhswp]):/")


def _normalize_saprouter(value: str) -> str:
    """Undo MSYS/Git-Bash path mangling of SAP Router strings.

    On Windows, bash tools translate a leading '/H/...' argument into 'H:/...'.
    SAP Router strings always start with '/H/', '/S/', '/W/' or '/P/' — if we
    see one of those single letters followed by ':/', we know it was mangled
    and reconstruct the original form.
    """
    if not value:
        return value
    m = _MANGLED_ROUTER_RE.match(value)
    if not m:
        return value
    return "/" + m.group(1).upper() + "/" + value[3:]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _keyring_shared import SERVICE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="System label (e.g. 'Production ERP (PRD)') — shown in dialog title, stored as workspace")
    parser.add_argument("--host", required=True, help="Application server host (IP or hostname)")
    parser.add_argument("--sysnr", required=True, help="System number, 2 digits (e.g. '00')")
    parser.add_argument("--saprouter", default="", help="SAP Router string (optional)")
    args = parser.parse_args()

    args.saprouter = _normalize_saprouter(args.saprouter)

    dialog = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sap_logon_dialog.py")
    if not os.path.isfile(dialog):
        return _err(f"sap_logon_dialog.py not found at {dialog}")

    result = subprocess.run(
        [sys.executable, dialog, args.name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return _err(f"Logon cancelled or dialog failed.\nstderr: {result.stderr}")

    try:
        client, user, passwd, lang = result.stdout.strip().split("|", 3)
    except ValueError:
        return _err("Dialog returned malformed stdout — expected 'client|user|pass|lang'")
    finally:
        # Minimize password lingering in the captured buffer
        result.stdout = ""

    keyring.set_password(SERVICE, "ashost", args.host)
    keyring.set_password(SERVICE, "sysnr", args.sysnr)
    keyring.set_password(SERVICE, "client", client)
    keyring.set_password(SERVICE, "user", user)
    keyring.set_password(SERVICE, "passwd", passwd)
    keyring.set_password(SERVICE, "lang", lang)
    keyring.set_password(SERVICE, "workspace", args.name)
    if args.saprouter:
        keyring.set_password(SERVICE, "saprouter", args.saprouter)
    else:
        try:
            keyring.delete_password(SERVICE, "saprouter")
        except Exception:
            pass

    print(f"Credentials stored for {user} on client {client}.")
    return 0


def _err(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
