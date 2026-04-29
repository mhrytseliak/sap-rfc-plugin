---
name: sap-change-connection
description: Use when the user asks to switch SAP systems, change the current connection, or invokes /sap-change-connection
user_invocable: true
---

## Steps

1. Run the shared disconnect script to clear current credentials:

   ```bash
   python - <<'PY'
   import glob, os, subprocess, sys
   p = glob.glob(os.path.expanduser("~/.claude/plugins/**/sap-disconnect/disconnect.py"), recursive=True)
   if not p:
       sys.exit("disconnect.py not found under ~/.claude/plugins — reinstall the plugin")
   sys.exit(subprocess.run([sys.executable, p[0]]).returncode)
   PY
   ```

2. Follow the full `sap-connect` flow from step 1 onward (ask method → resolve landscape or manual → launch dialog → store → ping).
