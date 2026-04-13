# sap-rfc-plugin

Claude Code plugin for SAP systems via RFC. Provides CLI tools for reading/writing SAP objects and connection management skills.

## Prerequisites

- Python 3.10+
- [SAP NW RFC SDK](https://support.sap.com/en/product/connectors/nwrfcsdk.html) installed and on PATH
- `pip install pyrfc keyring`

## Install

```bash
claude plugin marketplace add mhrytseliak/sap-rfc-plugin
claude plugin install sap-rfc
```

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
Removes current credentials, then runs the connect flow for a new system.

### Disconnect
```
/sap-disconnect
```
Removes all credentials from the OS keyring.

## CLI Tools

Once connected, these commands are available via Bash:

| Command | Description |
|---------|-------------|
| `sap-rfc ping` | Test connection, get system info |
| `sap-rfc get-fields <TABLE>` | Table field definitions (`--fields`, `--keys-only`) |
| `sap-rfc read-table <TABLE>` | Read up to 20 rows (`--fields`, `--where`, `--max-rows`) |
| `sap-rfc read-program <PROG>` | Read ABAP report — writes `.abap` file, returns path + line count |
| `sap-rfc read-fm <FM>` | FM interface + optional source (`--with-source`) |
| `sap-rfc read-class <CLASS>` | List methods or read method source (`--method`) |
| `sap-rfc update-program <PROG>` | Update ABAP source (`--source` or `--source-file`) |

All output is JSON. The `bin/` directory is added to PATH automatically by the plugin system.

### `sap-rfc update-program`

Updates ABAP program or include source code in SAP via `RPY_INCLUDE_UPDATE`.

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | None | Full source code string |
| `--source-file` | None | Path to `.abap` file |
| `--title` | auto | Program title (auto-detected if omitted) |
| `--activate` | off | Activate immediately (default: save inactive) |

**Write operation:** Always confirm with the user before calling this command. On error — show the error and wait for instructions, don't auto-retry.

**Inactive by default:** To prevent runtime dumps from syntax errors, the tool saves programs as inactive. Activate manually in SE38 or pass `--activate`.

**Transport requirement:** The program must already be in an open transport. If not, you'll get `DYNPRO_SEND_IN_BACKGROUND`. Fix: add the program to a transport in SE01/SE09, then retry.

## Credentials

Stored in the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service). No plaintext files — credentials are encrypted and tied to your OS user account.

Keys stored: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter` (optional).

## Cross-platform

- **Windows:** dark title bar, precise multi-monitor positioning, Consolas font
- **Mac:** cursor-relative positioning, Menlo font
- **Linux:** cursor-relative positioning, Consolas font (fallback by tkinter)
