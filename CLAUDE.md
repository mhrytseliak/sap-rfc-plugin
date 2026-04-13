# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin (`sap-rfc`) that provides CLI tools for SAP RFC connectivity and three skills for connection management. Credentials are stored in the OS keyring (Windows Credential Manager); the CLI is a Python script using `pyrfc` invoked via Bash.

## Architecture

- **`bin/sap-rfc`** — Python CLI script with 7 subcommands: `ping`, `get-fields`, `read-table`, `read-program`, `read-fm`, `read-class`, `update-program`. Each command opens a fresh `pyrfc.Connection` from keyring credentials, calls the RFC, outputs JSON to stdout, and closes the connection. The plugin `bin/` directory is added to PATH automatically.
- **`skills/sap-connect/`** — Skill to connect to SAP (landscape XML or manual). Launches a tkinter dialog (`sap_logon_dialog.py`) for credential entry so passwords never appear in conversation. Stores credentials via `keyring.set_password('sap-rfc', key, value)`.
- **`skills/sap-disconnect/`** — Removes keyring credentials.
- **`skills/sap-change-connection/`** — Disconnect + reconnect flow.
- **`.claude-plugin/plugin.json`** — Plugin metadata (name, version, author).

## CLI Usage

```bash
sap-rfc ping
sap-rfc get-fields <TABLE> [--fields F1,F2] [--keys-only]
sap-rfc read-table <TABLE> [--fields F1,F2] [--where "CLAUSE"] [--max-rows N]
sap-rfc read-program <PROGRAM> [--no-includes]
sap-rfc read-fm <FM_NAME> [--with-source]
sap-rfc read-class <CLASS> [--method METHOD]
sap-rfc update-program <PROGRAM> [--source-file PATH] [--source TEXT] [--title TEXT] [--activate]
```

All output is JSON to stdout. Exit code 0 on success, 1 on error.

## Key Design Decisions

- **File-based source output**: Commands that return ABAP source (`read-program`, `read-fm --with-source`, `read-class --method`) write to `.abap` files in a temp cache dir and return `source_file` path + `line_count` instead of inline source. This saves tokens — Claude reads files via Read tool only when needed. Cache is cleaned up on process exit.
- **File-based source input**: `update-program` accepts `--source-file` (path) as alternative to `--source` (string). Using `--source-file` prevents the full program text from appearing in the Bash tool call.
- **Connection per call**: No persistent connection pool. `get_connection()` creates a new `pyrfc.Connection` each time from keyring values.
- **Hard row limit**: `read-table` caps at 20 rows (`MAX_ROWS = 20`), enforced in the script.
- **WHERE clause chunking**: Long WHERE strings are split into 72-char chunks (SAP RFC_READ_TABLE limit).
- **Class method reading**: Uses TMDIR table to find method index, then constructs the include name (`CLASS====...CM###`) and reads via `RPY_PROGRAM_READ`.
- **Save inactive by default**: `update-program` saves as inactive (`SAVE_INACTIVE = "I"`) to prevent runtime dumps. Use `--activate` to activate immediately.
- **Keyring keys**: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter` — all under service name `sap-rfc`.

## Running the CLI

```bash
pip install pyrfc keyring
sap-rfc ping
```

`pyrfc` requires the SAP NW RFC SDK to be installed and on PATH/LD_LIBRARY_PATH.
