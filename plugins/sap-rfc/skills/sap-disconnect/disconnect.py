"""Clear all sap-rfc credentials from OS keyring.

Single source of truth for the key list is `_keyring_shared.ALL_KEYS`.
"""
import os
import sys

import keyring

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _keyring_shared import ALL_KEYS, SERVICE  # noqa: E402


def main() -> int:
    for key in ALL_KEYS:
        try:
            keyring.delete_password(SERVICE, key)
        except Exception:
            pass  # key may not exist; ignore
    print(f"Cleared {len(ALL_KEYS)} sap-rfc keys from OS keyring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
