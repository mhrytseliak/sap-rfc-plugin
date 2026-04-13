---
name: sap-change-connection
description: Switch to a different SAP system — removes current credentials from keyring, then runs the sap-connect flow.
user_invocable: true
---

## Steps

1. Clear credentials from OS keyring:
   ```bash
   python -c "
   import keyring
   for key in ('ashost', 'sysnr', 'client', 'user', 'passwd', 'lang', 'saprouter'):
       try: keyring.delete_password('sap-rfc', key)
       except keyring.errors.PasswordDeleteError: pass
   "
   ```
2. Follow the exact same flow as the `sap-connect` skill (ask connection method, parse landscape or manual entry, ask credentials, store in keyring).
