---
name: sap-connect
description: Connect to a SAP system — parse landscape XML or enter details manually, store credentials in OS keyring, register MCP server.
user_invocable: true
---

## Steps

1. **Ask for connection method.** Use AskUserQuestion:
   - "SAP Logon landscape XML file" — user provides path to `landscape_snapshot.xml`
   - "Manual entry" — user provides host, system number, client directly

2. **If landscape XML:**
   a. Read the XML file at the path the user provided.
   b. Parse all `<Service type="SAPGUI">` entries. For each, extract: `name`, `systemid`, `server` (host:port). Group by parent `<Workspace>` and `<Node>` names.
   c. Use AskUserQuestion to present the systems grouped by workspace. Format each option as: `Workspace > Node > Name (SID) [host:port]`
   d. After user picks a system, extract `ashost` (IP/hostname before the colon) and `sysnr` (from port: last 2 digits of port number, e.g. port 3200 → sysnr 00, port 3272 → sysnr 72).
   e. If the Service has a `routerid` attribute, find the matching `<Router uuid="...">` element and extract its `router` attribute (the SAP router string, e.g. `/H/91.202.7.52/W/xxxxx`). Store it as `saprouter` in keyring.

3. **If manual entry:** Use AskUserQuestion to ask for:
   - SAP application server host (IP or hostname)
   - System number (00, 01, etc.)

4. **Collect credentials via SAP Logon dialog.** Tell the user: **"An SAP Logon dialog will open on your screen — enter your credentials there. Password never appears in the conversation."**

   Then launch the logon dialog. Find its path via `glob` and run:
   ```bash
   python -c "
   import subprocess, keyring, sys, os, glob
   paths = glob.glob(os.path.expanduser('~/.claude/plugins/**/sap-connect/sap_logon_dialog.py'), recursive=True)
   dialog = paths[0]
   result = subprocess.run([sys.executable, dialog, '<SYSTEM_NAME>'], capture_output=True, text=True)
   if result.returncode == 0 and result.stdout.strip():
       client, user, passwd, lang = result.stdout.strip().split('|', 3)
       keyring.set_password('sap-rfc', 'ashost', '<host>')
       keyring.set_password('sap-rfc', 'sysnr', '<sysnr>')
       keyring.set_password('sap-rfc', 'client', client)
       keyring.set_password('sap-rfc', 'user', user)
       keyring.set_password('sap-rfc', 'passwd', passwd)
       keyring.set_password('sap-rfc', 'lang', lang)
       # SAP router (if extracted in step 2e, otherwise clear it)
       saprouter = '<saprouter_or_empty>'
       if saprouter:
           keyring.set_password('sap-rfc', 'saprouter', saprouter)
       else:
           try: keyring.delete_password('sap-rfc', 'saprouter')
           except: pass
       print(f'Credentials stored for {user} on client {client}.')
   else:
       print('Logon cancelled.')
   "
   ```
   Replace `<SYSTEM_NAME>` with the system name from step 2/3 (e.g. "DW DEV"). Replace `<host>` and `<sysnr>` with values from step 2d/3. Replace `<saprouter_or_empty>` with the router string from step 2e (or empty string `''` if no router). The dialog collects client, user, password (masked), and language in one window. Credentials go straight to the encrypted OS keyring.

5. Find the plugin's server.py path. It lives inside the installed plugin cache at:
   `~/.claude/plugins/cache/sap-rfc-marketplace/sap-rfc/<version>/server/server.py`
   Use `glob ~/.claude/plugins/cache/sap-rfc-marketplace/sap-rfc/*/server/server.py` to find the exact path.

6. Register the MCP server:
   ```bash
   claude mcp add sap-rfc --scope user -- python "<resolved-server-path>"
   ```

7. Tell the user: "SAP connection configured for **<Name> (<SID>)**. Credentials stored securely. Restart Claude Code or run `/mcp` to activate. Then use `sap_ping` to test."
