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

3. **If manual entry:** Use AskUserQuestion to ask for:
   - SAP application server host (IP or hostname)
   - System number (00, 01, etc.)

4. Use AskUserQuestion to ask for SAP **client number** (offer common options: 100, 200, 300, or Other).

5. Use AskUserQuestion to ask for SAP **username** — do NOT pre-fill guesses. Offer only two generic options like "Type username below" and "Skip". The user types their actual username in the "Other" field.

6. **Collect password securely via GUI dialog** — do NOT use AskUserQuestion for passwords (values appear in plain text in chat history). Claude Code's Bash and `!` prefix both run non-interactively, so `read -s`, `getpass`, and `input()` do not work.

   Instead, launch the tkinter password dialog that lives next to this skill file. Find its path and run:
   ```bash
   python -c "
   import subprocess, keyring, sys, glob
   scripts = glob.glob(r'C:/Users/*/.claude/plugins/**/sap-connect/sap_password_dialog.py', recursive=True)
   if not scripts:
       scripts = glob.glob(r'/Users/*/.claude/plugins/**/sap-connect/sap_password_dialog.py', recursive=True)
   dialog = scripts[0]
   result = subprocess.run([sys.executable, dialog, '<USER>'], capture_output=True, text=True)
   pwd = result.stdout.strip()
   if result.returncode == 0 and pwd:
       keyring.set_password('sap-rfc', 'passwd', pwd)
       print('Password stored in keyring.')
   else:
       print('Password entry cancelled.')
   "
   ```
   Replace `<USER>` with the actual username from step 5. The password is entered in a masked GUI popup (cross-platform tkinter) and stored directly to the encrypted keyring — it never appears in the conversation.

7. **Store remaining credentials in OS keyring** (password was already stored in step 6):
   ```bash
   python -c "
   import keyring
   keyring.set_password('sap-rfc', 'ashost', '<host>')
   keyring.set_password('sap-rfc', 'sysnr', '<sysnr>')
   keyring.set_password('sap-rfc', 'client', '<client>')
   keyring.set_password('sap-rfc', 'user', '<user>')
   keyring.set_password('sap-rfc', 'lang', 'EN')
   "
   ```
   This stores credentials in Windows Credential Manager (encrypted, tied to the current user).

8. Find the plugin's server.py path. It lives inside the installed plugin cache at:
   `~/.claude/plugins/cache/sap-rfc-marketplace/sap-rfc/<version>/server/server.py`
   Use `glob ~/.claude/plugins/cache/sap-rfc-marketplace/sap-rfc/*/server/server.py` to find the exact path.

9. Register the MCP server:
   ```bash
   claude mcp add sap-rfc --scope user -- python "<resolved-server-path>"
   ```

10. Tell the user: "SAP connection configured for **<Name> (<SID>)**. Credentials stored in Windows Credential Manager. Restart Claude Code or run `/mcp` to activate. Then use `sap_ping` to test."
