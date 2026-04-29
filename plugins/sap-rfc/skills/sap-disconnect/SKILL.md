---
name: sap-disconnect
description: Use when the user asks to disconnect from SAP, clear credentials, or invokes /sap-disconnect
user_invocable: true
---

## Steps

1. Clear all sap-rfc credentials from the OS keyring:

   ```bash
   python - <<'PY'
   import glob, os, subprocess, sys
   p = glob.glob(os.path.expanduser("~/.claude/plugins/**/sap-disconnect/disconnect.py"), recursive=True)
   if not p:
       sys.exit("disconnect.py not found under ~/.claude/plugins — reinstall the plugin")
   sys.exit(subprocess.run([sys.executable, p[0]]).returncode)
   PY
   ```

2. Tell the user: "SAP connection removed. Credentials deleted from the OS keyring."
