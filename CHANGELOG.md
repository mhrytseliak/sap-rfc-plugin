# Changelog

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
