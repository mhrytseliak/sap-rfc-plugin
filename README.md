# sap-rfc-plugin

Claude Code plugin for SAP systems via RFC. Provides an MCP server with read/write SAP tools and connection management skills.

## Prerequisites

- Python 3.10+
- [SAP NW RFC SDK](https://support.sap.com/en/product/connectors/nwrfcsdk.html) installed and on PATH
- `pip install fastmcp pyrfc keyring`

## Install

```bash
claude plugin marketplace add mhrytseliak/sap-rfc-plugin
claude plugin install sap-rfc
```

Restart Claude Code after install.

## Usage

### Connect to SAP
```
/sap-connect
```
1. Select a system — from SAP Logon landscape XML (auto-parses all systems) or manual entry
2. An SAP GUI-style logon dialog opens with Client, User, Password, and Language fields
3. Credentials go straight to the encrypted OS keyring — password never appears in the conversation

Supports SAP Router — systems that require a router connection are detected automatically from the landscape XML.

> **Multi-monitor:** On Windows, the dialog centers on the monitor where your cursor is. On Mac/Linux, it appears near the cursor.

### Switch system
```
/sap-change-connection
```
Removes current credentials and MCP registration, then runs the connect flow for a new system.

### Disconnect
```
/sap-disconnect
```
Removes MCP server registration and all credentials from the OS keyring.

## MCP Tools

Once connected, these tools are available:

| Tool | Description |
|------|-------------|
| `sap_ping` | Test connection, get system info |
| `sap_get_fields` | Table field definitions (supports `fields` filter, `keys_only`) |
| `sap_read_table` | Read up to 20 rows from any table |
| `sap_read_program` | Read ABAP report source + includes + text elements |
| `sap_read_fm_interface` | FM interface + optional source code (`with_source=True`) |
| `sap_read_class` | List class methods or read method source |
| `sap_update_program` | Update ABAP program/include source code (saves inactive by default) |

### `sap_update_program`

Updates ABAP program or include source code in SAP via `RPY_INCLUDE_UPDATE`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `program_name` | str | required | Program or include name |
| `source` | str | required | Full source code |
| `title` | str | None | Program title (auto-detected if omitted) |
| `save_inactive` | bool | True | Save as inactive version |

**Write operation:** Always confirm with the user before calling this tool. On error — show the error and wait for instructions, don't auto-retry.

**Inactive by default:** To prevent runtime dumps from syntax errors, the tool saves programs as inactive. Activate manually in SE38 or pass `save_inactive=False`.

**Transport requirement:** The program must already be in an open transport. If not, you'll get `DYNPRO_SEND_IN_BACKGROUND`. Fix: add the program to a transport in SE01/SE09, then retry.

## Credentials

Stored in the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service). No plaintext files — credentials are encrypted and tied to your OS user account.

Keys stored: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter` (optional).

## Cross-platform

- **Windows:** dark title bar, precise multi-monitor positioning, Consolas font
- **Mac:** cursor-relative positioning, Menlo font
- **Linux:** cursor-relative positioning, Consolas font (fallback by tkinter)
