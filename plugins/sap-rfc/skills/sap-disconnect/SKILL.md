---
name: sap-disconnect
description: Disconnect from SAP — removes credentials from OS keyring.
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
2. Tell the user: "SAP connection removed. Credentials deleted from Windows Credential Manager."
