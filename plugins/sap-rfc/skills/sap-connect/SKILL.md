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
   a. Read the XML file at the path the user provided (default: `%APPDATA%/SAP/Common/SAPUILandscape.xml` on Windows, `~/Library/SAP/SAPUILandscape.xml` on Mac).
   b. Parse all `<Service type="SAPGUI">` entries. Extract: `name`, `systemid`, `server` (host:port), `routerid` (optional).
   c. Use AskUserQuestion to present systems. If more than 4 systems, group by logical categories first, then let user pick the specific system. Format: `Name (SID) [host:port]`.
   d. After user picks a system, extract:
      - `ashost` — IP/hostname before the colon
      - `sysnr` — last 2 digits of port (e.g. port 3200 → 00, port 3272 → 72)
   e. **SAP Router:** if the Service has a `routerid` attribute, find the matching `<Router uuid="...">` element and extract its `router` attribute (e.g. `/H/91.202.7.52/W/xxxxx`).

3. **If manual entry:** Use AskUserQuestion to ask for:
   - SAP application server host (IP or hostname)
   - System number (00, 01, etc.)
   - SAP Router string (optional — only if connecting through a router)

4. **Collect credentials via SAP Logon dialog.** Tell the user: **"An SAP Logon dialog will open on your screen — enter your credentials there. Password never appears in the conversation."**

   Launch the tkinter logon dialog (dark terminal style, centered on cursor's monitor):
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
   Placeholders:
   - `<SYSTEM_NAME>` — system name from step 2/3 (shown in dialog title)
   - `<host>`, `<sysnr>` — from step 2d or 3
   - `<saprouter_or_empty>` — router string from step 2e, or `''` if none

   The dialog returns `client|user|password|lang` on stdout. Password goes straight to the encrypted OS keyring — never in the conversation.

5. **Register MCP server** (if not already registered). Find server.py path:
   ```bash
   glob ~/.claude/plugins/cache/sap-rfc-marketplace/sap-rfc/*/server/server.py
   ```
   Then register:
   ```bash
   claude mcp add sap-rfc --scope user -- python "<resolved-server-path>"
   ```

6. Tell the user: "SAP connection configured for **<Name> (<SID>)**. Credentials stored securely. Restart Claude Code or run `/mcp` to activate. Then use `sap_ping` to test."
