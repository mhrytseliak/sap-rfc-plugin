# Changelog

## 2.0.0 (2026-04-13)

### Changed
- **Breaking:** Replaced MCP server with CLI script (`bin/sap-rfc`). Tools are now invoked via Bash instead of MCP protocol.
- Removed `fastmcp` dependency.
- Skills no longer register/unregister MCP server — just manage keyring credentials.
- Plugin uses `bin/` directory for PATH integration.

### Removed
- `server/server.py` — MCP server
- `server/requirements.txt`

## 1.1.0 (2026-04-09)

### Features
- **File-based source output** — `sap_read_program`, `sap_read_fm_interface`, `sap_read_class` write source to `.abap` files in a temp cache dir and return `source_file` path + `line_count` instead of inline source. Saves thousands of tokens per call.
- **File-based source input** — `sap_update_program` accepts `source_file` (path) as alternative to `source` (string), preventing token waste on timeouts.
- Temp cache auto-cleans on server shutdown.

## 1.0.1 (2026-04-08)

### Features
- **`sap_update_program`** — write tool to update ABAP program/include source code via `RPY_INCLUDE_UPDATE`. Saves as inactive by default to prevent runtime dumps from syntax errors.

## 1.0.0 (2026-04-07)

Initial public release.

### Features
- **MCP Server** with 6 read-only SAP tools: `sap_ping`, `sap_get_fields`, `sap_read_table`, `sap_read_program`, `sap_read_fm_interface`, `sap_read_class`
- **`/sap-connect`** — connect to SAP via landscape XML or manual entry, SAP GUI-style logon dialog (Client, User, Password, Language), SAP Router support
- **`/sap-change-connection`** — switch to a different SAP system
- **`/sap-disconnect`** — remove credentials and MCP registration
- **Secure credentials** — OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service), password never in chat
- **Cross-platform** — Windows (dark title bar, precise multi-monitor), Mac, Linux
