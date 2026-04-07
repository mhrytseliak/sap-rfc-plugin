# sap-rfc-plugin

Claude Code plugin for SAP systems via RFC. Provides an MCP server with read-only SAP tools and connection management skills.

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
Walks you through selecting a system (from SAP Logon landscape XML or manual entry), entering credentials, and registering the MCP server.

### Switch system
```
/sap-change-connection
```

### Disconnect
```
/sap-disconnect
```

## MCP Tools

Once connected, these tools are available:

| Tool | Description |
|------|-------------|
| `sap_ping` | Test connection, get system info |
| `sap_get_fields` | Table field definitions (supports `fields` filter, `keys_only`) |
| `sap_read_table` | Read up to 20 rows from any table |
| `sap_read_program` | Read ABAP report source + includes + text elements |
| `sap_read_fm_interface` | FM interface + optional source code |
| `sap_read_class` | List class methods or read method source |

## Credentials

Stored in the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service). No plaintext files — credentials are encrypted and tied to your OS user account.
