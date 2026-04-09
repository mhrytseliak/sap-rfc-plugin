# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin (`sap-rfc`) that provides an MCP server for SAP RFC connectivity and three skills for connection management. Credentials are stored in the OS keyring (Windows Credential Manager); the MCP server is a Python FastMCP app using `pyrfc`.

## Architecture

- **`server/server.py`** — FastMCP server exposing 7 MCP tools: `sap_ping`, `sap_get_fields`, `sap_read_table`, `sap_read_program`, `sap_read_fm_interface`, `sap_read_class`, `sap_update_program`. Each tool opens a fresh `pyrfc.Connection` from keyring credentials, calls the RFC, and closes the connection.
- **`skills/sap-connect/`** — Skill to connect to SAP (landscape XML or manual). Launches a tkinter dialog (`sap_logon_dialog.py`) for credential entry so passwords never appear in conversation. Stores credentials via `keyring.set_password('sap-rfc', key, value)`.
- **`skills/sap-disconnect/`** — Removes MCP registration and keyring credentials.
- **`skills/sap-change-connection/`** — Disconnect + reconnect flow.
- **`.claude-plugin/plugin.json`** — Plugin metadata (name, version, author).

## Key Design Decisions

- **File-based source output**: Tools that return ABAP source (`sap_read_program`, `sap_read_fm_interface`, `sap_read_class`) write to `.abap` files in a temp cache dir and return `source_file` path + `line_count` instead of inline source. This saves tokens — Claude reads files via Read tool only when needed. Cache is cleaned up on server shutdown.
- **File-based source input**: `sap_update_program` accepts `source_file` (path) as alternative to `source` (string). Using `source_file` prevents the full program text from appearing in the MCP tool call, avoiding token waste on timeouts.
- **Connection per call**: No persistent connection pool. `get_connection()` creates a new `pyrfc.Connection` each time from keyring values.
- **Hard row limit**: `sap_read_table` caps at 20 rows (`MAX_ROWS = 20`), enforced server-side.
- **WHERE clause chunking**: Long WHERE strings are split into 72-char chunks (SAP RFC_READ_TABLE limit).
- **Class method reading**: Uses TMDIR table to find method index, then constructs the include name (`CLASS====...CM###`) and reads via `RPY_PROGRAM_READ`.
- **Save inactive by default**: `sap_update_program` saves as inactive (`SAVE_INACTIVE = "I"`) to prevent runtime dumps.
- **Keyring keys**: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter` — all under service name `sap-rfc`.

## Running the Server

```bash
pip install fastmcp pyrfc keyring
python server/server.py
```

`pyrfc` requires the SAP NW RFC SDK to be installed and on PATH/LD_LIBRARY_PATH.
