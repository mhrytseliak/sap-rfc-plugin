---
name: sap-connect
description: Use when the user asks to connect to SAP, configure a SAP system, or invokes /sap-connect
user_invocable: true
---

## Hard rules

1. **NEVER ask for the password in chat.** The tkinter dialog launched by `connect.py` is the ONLY channel for credentials. If it fails to launch, fix the launch — do not fall back to chat input.
2. **Parse landscape XML by `serviceid`, not by index.** The order of `<Service>` entries is not stable.
3. **Always finish by calling the `ping` MCP tool.** If it returns an error, report it to the user and stop — do NOT claim success.
4. **No placeholder values.** Every argument passed to `connect.py` must be a real value resolved earlier in this flow.

## Steps

### 1. Ask for connection method

Use `AskUserQuestion`:
- "SAP Logon landscape XML file" — user provides a path (default: `%APPDATA%/SAP/Common/SAPUILandscape.xml` on Windows, `~/Library/SAP/SAPUILandscape.xml` on macOS)
- "Manual entry" — user types host, system number, client

### 2a. Landscape XML path

1. Read the XML file.
2. Iterate every `<Service type="SAPGUI">` element. For each, capture:
   - `name` — human-readable system name
   - `systemid` — SID (3 letters, e.g. `PRD`)
   - `serviceid` — stable UUID, used as the primary key
   - `server` — `host:port`, e.g. `10.1.2.3:3200`
   - `routerid` — optional UUID pointing at a `<Router>` element
3. Present the list to the user via `AskUserQuestion`. Format each option as `Name (SID) [host:port]`. If more than ~6 systems, group by obvious prefix/category first, then drill down.
4. Resolve the pick **by `serviceid`**, not by the label the user clicked.
5. From the resolved Service extract:
   - `ashost` — substring before `:` in `server`
   - `sysnr` — last 2 digits of the port (`3200` → `00`, `3272` → `72`)
6. If `routerid` is present, find the `<Router uuid="<routerid>">` element and take its `router` attribute (e.g. `/H/91.202.7.52/S/3299/W/xxxxx`). Store as `saprouter`. If no `routerid`, `saprouter` is empty.

### 2b. Manual entry path

Use `AskUserQuestion` to collect:
- application server host (IP or hostname)
- system number (`00`, `01`, ...)
- SAP Router string (optional — only if connecting through a router)

Set `name` to whatever label the user wants for the dialog title (e.g. "Manual").

### 3. Launch the logon dialog + store credentials

Tell the user verbatim: **"An SAP Logon dialog will open on your screen — enter your credentials there. The password never appears in the conversation."**

Locate `connect.py` under the plugin cache and run it with the resolved values. The script launches the dialog, reads credentials from stdout, and writes them to the OS keyring. Password never touches the shell command line.

```bash
python - <<'PY'
import glob, os, subprocess, sys
p = glob.glob(os.path.expanduser("~/.claude/plugins/**/sap-connect/connect.py"), recursive=True)
if not p:
    sys.exit("connect.py not found under ~/.claude/plugins — reinstall the plugin")
r = subprocess.run([sys.executable, p[0],
    "--name",      "<NAME (SID)>",
    "--host",      "<ashost>",
    "--sysnr",     "<sysnr>",
    "--saprouter", "<router or empty>",
])
sys.exit(r.returncode)
PY
```

Substitute the four resolved values directly — no leftover `<...>` placeholders.

### 4. Test the connection — MANDATORY

Call the `ping` MCP tool (no arguments). On failure: report the error, suggest re-running `/sap-connect`, and **do not** claim success.

### 5. Confirm to the user

On success, say:
> SAP connection configured for **<Name> (<SID>)**. Credentials stored securely. Tools are available immediately — no restart needed.

## Worked example (landscape XML)

User says "connect to sap". Landscape has a Service:
`name="Production ERP"`, `systemid="PRD"`, `serviceid="a1b2..."`, `server="10.1.2.3:3200"`, `routerid="c3d4..."`.
Matching `<Router uuid="c3d4...">` has `router="/H/91.202.7.52/S/3299/W/secret"`.

Resolved args for `connect.py`:
- `--name "Production ERP (PRD)"`
- `--host "10.1.2.3"`
- `--sysnr "00"`
- `--saprouter "/H/91.202.7.52/S/3299/W/secret"`

Run it, then call the `ping` MCP tool to verify.
