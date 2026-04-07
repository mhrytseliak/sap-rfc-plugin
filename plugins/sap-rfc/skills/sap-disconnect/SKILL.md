---
name: sap-disconnect
description: Disconnect from SAP — removes MCP server registration and credentials from OS keyring.
user_invocable: true
---

## Steps

1. Run `claude mcp remove sap-rfc` to unregister the MCP server.
2. Clear credentials from OS keyring:
   ```bash
   python -c "
   import keyring
   for key in ('ashost', 'sysnr', 'client', 'user', 'passwd', 'lang', 'saprouter'):
       try: keyring.delete_password('sap-rfc', key)
       except keyring.errors.PasswordDeleteError: pass
   "
   ```
3. Tell the user: "SAP connection removed. MCP server unregistered and credentials deleted from Windows Credential Manager."
