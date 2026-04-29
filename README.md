# sap-rfc-plugin

Claude Code plugin for SAP systems. Provides two MCP servers and three connection-management skills:

- **`rfc-mcp`** — 8 read-only tools over RFC (`pyrfc`).
- **`adt-mcp`** — 10 write + check tools over ADT (HTTP). Auto-discovers the ADT base URL via `ICM_GET_INFO`.

## Prerequisites

- Python 3.10+ available as `python` on PATH (see Windows note below)
- [SAP NW RFC SDK](https://support.sap.com/en/product/connectors/nwrfcsdk.html) installed and on PATH
- `pip install -r plugins/sap-rfc/requirements.txt`
  (for running the test suite: `pip install -r plugins/sap-rfc/requirements-dev.txt`)

> **Windows note:** If `python` on your PATH resolves to the Microsoft Store stub (`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`), the MCP servers will fail to start. Either disable the App Execution Alias (Settings → Apps → Advanced app settings → App execution aliases) or prepend your real Python install dir to PATH so `where python` points at it first.

## Install

```bash
claude plugin marketplace add mhrytseliak/sap-rfc-plugin
claude plugin install sap-rfc@sap-rfc-marketplace
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

## MCP Tools

### `rfc-mcp` — read-only (RFC)

| Tool | Description |
|------|-------------|
| `ping` | Test connection, return system info (SID, release, host) |
| `get_table_structure(table)` | Field definitions for a DDIC table |
| `read_table(table, fields?, where?, max_rows?)` | Read up to 20 rows via RFC_READ_TABLE |
| `read_source(name, type, method?)` | Read ABAP source — program, include, or class method; writes `.abap` file, returns path + line count. Uses `READ_LATEST_VERSION='X'` so the source matches what ADT checks. |
| `search_objects(name_pattern, object_types?, devclass?, max_rows?)` | Search TADIR with SAP LIKE patterns |
| `get_function_module_interface(name, with_source?)` | FM interface (params/exceptions); optional source dump |
| `read_text_pool(name, language?)` | Report title / text symbols / selection texts. Language auto-resolved from TRDIR.RLOAD → logon fallback |
| `update_text_pool(name, entries, transport, language?)` | Read-merge-write text pool via `RPY_TEXTELEMENTS_INSERT`. Auto re-applies 8-space prefix for selection texts. Devclass resolved from TADIR. Transport required |

All source-returning tools write `.abap` files to a persistent cache dir and return `{source_file, line_count}` — open the file with the Read tool when you need the content. This keeps tool responses compact.

### `adt-mcp` — write + check (ADT over HTTP)

| Tool | Description |
|------|-------------|
| `ping` | Verify ADT reachability; returns resolved base URL |
| `syntax_check(name, kind, group?)` | ADT check-run (no 72-char truncation); returns errors + warnings with `{line, col, severity, message}` |
| `transport_of_object(name, kind, group?, operation?, devclass?)` | Find the open transport that locks an object. POSTs to `/cts/transportchecks` and parses `LOCKS/LOCK_HOLDER/REQ_HEADER` |
| `transport_create(name, kind, devclass, text, group?, operation?, transport_layer?)` | Create a CTS workbench request for an object (ADT requires object + package context; bare empty TRs must be created in SE09). POSTs to `/cts/transports` with `dataname=com.sap.adt.CreateCorrectionRequest` |
| `create_program(name, devclass, description, transport?)` | POST a new executable REPORT header to `/programs/programs?corrNr=<TR>`; source uploaded separately via `update_source`. `transport` required unless devclass=`$TMP` |
| `create_include(name, devclass, description, transport?, master_program?)` | POST a new include to `/programs/includes?corrNr=<TR>`. Pass `master_program` to bind the include to its report — required for activation of report-specific includes |
| `create_class(name, devclass, description, transport?)` | POST a new global class shell to `/oo/classes?corrNr=<TR>`. Full class body (DEFINITION + IMPLEMENTATION, all sections/methods) is uploaded in one PUT via `update_source(kind=class)` |
| `update_source(name, kind, source_file, transport, group?)` | Lock → PUT → unlock. Flips session to stateful (`X-sap-adt-sessiontype: stateful`) for the write window — without it SAP returns HTTP 423 |
| `activate(objects)` | ADT activation endpoint — reports inactive/invalid objects. Include URIs auto-resolve `?context=<master_uri>` to avoid the "select a master program" error |
| `code_inspector(name, kind, variant?, group?, max_verdicts?)` | ATC findings via the three-step worklist flow: `POST /atc/worklists?checkVariant=…` → `POST /atc/runs?worklistId=…` → `GET /atc/worklists/<id>`. Existence probe first; non-existent object → `ObjectNotFound` (prevents silent pass on typos) |

Discovery order for the ADT base URL: cached `adt_url` → `ICM_GET_INFO` probe → HTTP check against `/sap/bc/adt/core/discovery`. If no candidate answers (e.g. off-VPN), every tool returns `{error: "ADTNotAvailable", tried: [...]}` so the caller can fall back to manual steps in SAP GUI.

Typical create → edit → activate flow:
```
transport_create(name=ZMY_PROG, kind=program, devclass=ZPKG, text="…") → TR
create_program(name=ZMY_PROG, devclass=ZPKG, description="…", transport=TR)
update_source(name=ZMY_PROG, kind=program, source_file=…, transport=TR)
syntax_check(name=ZMY_PROG)
activate(objects=[{name: "ZMY_PROG", kind: "program"}])
```

## Credentials

Stored in the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service). No plaintext files — credentials are encrypted and tied to your OS user account.

Keys stored: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter` (optional), `workspace`, and (populated by `adt-mcp` discovery) `adt_url`, `adt_verify_tls`, `adt_timeout`.

## Cross-platform

- **Windows:** dark title bar, precise multi-monitor positioning, Consolas font
- **Mac:** cursor-relative positioning, Menlo font
- **Linux:** cursor-relative positioning, Consolas font (fallback by tkinter)
