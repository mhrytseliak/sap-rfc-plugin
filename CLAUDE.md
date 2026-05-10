# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Claude Code plugin (`sap-rfc`) that provides two MCP servers for SAP connectivity and three skills for connection management. Credentials are stored in the OS keyring (Windows Credential Manager). `rfc-mcp` uses `pyrfc` for RFC calls (read + write); `adt-mcp` uses HTTP/ADT for write + check flows. Both can write — choose RFC when ADT isn't reachable.

## Architecture

Plugin layout follows a monorepo under `plugins/sap-rfc/servers/<name>-mcp/`. Two servers: `rfc-mcp` (read + write) and `adt-mcp` (write + check).

- **`plugins/sap-rfc/servers/rfc-mcp/`** — FastMCP server (stdio). Read-only SAP RFC tools: `ping`, `read_source`, `read_table`, `get_table_structure`, `get_function_module_interface`, `search_objects`. Each call opens a fresh `pyrfc.Connection` from OS-keyring credentials and closes it.
  - `tools/` — one module per tool group: `system.py` (ping), `source.py` (read_source), `ddic.py` (search_objects, get_table_structure, read_table), `fm.py` (get_function_module_interface).
  - `connection.py` — keyring → `pyrfc.Connection` factory.
  - `cache.py` — persistent `.abap` file cache (`sap-rfc-cache` under system temp).
  - `where_clause.py` — splits long WHERE strings into 72-char chunks.
  - `tests/` — pytest suite for `cache` and `where_clause` (no live SAP needed).
- **`plugins/sap-rfc/servers/adt-mcp/`** — FastMCP server (stdio). ADT (HTTP) tools for write + check flows: `ping`, `syntax_check`, `transport_of_object`, `transport_create`, `create_program`, `create_include`, `create_class`, `update_source`, `activate`, `code_inspector`. Discovery: cached `adt_url` → RFC `ICM_GET_INFO` → HTTP probe → keyring cache. If no candidate is reachable (e.g. user off corp VPN), tools return `{error: "ADTNotAvailable"}` and the caller falls back to manual stage 7 in SAP GUI.
  - `tools/` — one module per tool: `ping.py`, `syntax.py`, `transport.py`, `transport_create.py`, `create_program.py`, `create_include.py`, `create_class.py`, `source_write.py`, `activate.py`, `code_inspector.py`.
  - `adt_client.py` — `requests.Session` wrapper: basic auth, `sap-client` header, CSRF, lock/unlock (toggles stateful session), `OBJECT_URI(name, kind, group?)` helper.
  - `discovery.py` — resolve ADT base URL via `ICM_GET_INFO` + TCP/HTTP probe.
  - `errors.py` — `ADTNotAvailable`, `ADTError` (SAP exc: XML parser).
  - `tests/` — offline pytest suite using `responses` (no live SAP needed).
- **`plugins/sap-rfc/skills/sap-connect/`** — Skill to connect to SAP (landscape XML or manual). Launches a tkinter dialog (`sap_logon_dialog.py`) for credential entry so passwords never appear in conversation. Stores credentials via `keyring.set_password('sap-rfc', key, value)`.
- **`plugins/sap-rfc/skills/sap-disconnect/`** — Removes keyring credentials.
- **`plugins/sap-rfc/skills/sap-change-connection/`** — Disconnect + reconnect flow.
- **`plugins/sap-rfc/.claude-plugin/plugin.json`** — Plugin metadata (name, version, mcpServers registration).

### rfc-mcp Tools

| Tool | RFC | Notes |
|------|-----|-------|
| `ping` | `STFC_CONNECTION`, `RFC_SYSTEM_INFO` | Returns system info on success |
| `read_source(name, type, method?)` | `RPY_PROGRAM_READ` | type: `program`\|`include`\|`class`; for class+method, TMDIR lookup → constructed include `CLASS====...CM###` |
| `search_objects(name_pattern, object_types?, devclass?, max_rows?)` | `RFC_READ_TABLE` → TADIR | SAP LIKE patterns supported |
| `get_table_structure(table)` | `DDIF_FIELDINFO_GET` | Returns field list with key/type/length |
| `read_table(table, fields?, where?, max_rows?)` | `RFC_READ_TABLE` | Capped at 20 rows; WHERE chunked to 72-char lines |
| `get_function_module_interface(name, with_source?)` | `RPY_FUNCTIONMODULE_READ_NEW` | with_source=True reads `NEW_SOURCE` (full-width lines) and dumps to a file. Old `RPY_FUNCTIONMODULE_READ` caps at 72 chars and raises SAP msg 180 on many modern FMs. |
| `read_text_pool(name, language?)` | `RPY_PROGRAM_READ` (TEXTELEMENTS) | Reads report title / text symbols / selection texts. Language auto-resolved from TRDIR.RLOAD → logon fallback. 8-space sel-text prefix is stripped. |
| `update_text_pool(name, entries, transport, language?)` | `RPY_TEXTELEMENTS_INSERT` | Read-merge-write by (id,key). Auto re-applies 8-space prefix for S entries. Devclass resolved from TADIR. Transport required. |
| `syntax_check_rfc(name, kind?)` | `RS_ABAP_SYNTAX_CHECK_E` | Returns errors/warnings/infos as structured rows with include, line, col, keyword, msg-no, message. Replaces SIW_RFC_SYNTAX_CHECK (one-error / no include). |
| `upload_program(name, source_file, transport?, devclass?, description?, program_type?)` | `RPY_PROGRAM_INSERT` / `RPY_INCLUDE_INSERT` / `RPY_INCLUDE_UPDATE` | Auto-detects create vs update via RPY_PROGRAM_READ. Updates routed through RPY_INCLUDE_UPDATE because RPY_PROGRAM_UPDATE is not RFC-enabled. Auto-resolves open TR from E070. Auto-activates. Runs syntax_check_rfc post-upload. |
| `test_run(name, params?, select_options?, variant?, max_wait_sec?)` | `BAPI_XMI_LOGON` + `BAPI_XBP_JOB_*` + `RSLG_READ_FILE` + `BAPI_XMI_LOGOFF` | Submits report as XBP job, polls until done/aborted/timeout. On abort, correlates SM21 syslog by user/time/msg-class AB0-AB2 to extract runtime-error name + TID. Joblog returned always; dump info structured. |
| `read_form(file_path, render?, render_html?)` | — (offline) | Parses a dialect-B SAPscript form export (`RSTXSCRP` output). Produces a text outline, optional wireframe PNG (Pillow), and optional interactive HTML preview (browser). No SAP connection required. Dialect A, writes, and live SAP reads are out of scope for v1. |

Source-returning tools (`read_source`, `get_function_module_interface` with `with_source=True`) write `.abap` files to a persistent cache dir (`sap-rfc-cache` under the system temp dir) and return `{source_file, line_count}` — Claude reads the file via the Read tool only when needed. This avoids embedding large ABAP listings in the tool response.

## `read_form` Tool Rules

Apply when calling `mcp__plugin_sap-rfc_rfc-mcp__read_form`.

**Offline, file-based.** v1 does NOT read from SAP. The user must first run `RSTXSCRP` (mode `EXPORT`, object `FORM`, `FSECURE=L`) to produce a `.FOR` file. Live reads via `READ_FORM`/`READ_FORM_LINES` are not RFC-enabled; a Z-wrapper FM is a future addition.

**Four artefacts, one call.** The tool writes to the sap-rfc cache dir: `<name>.FOR` (source copy), `<name>.outline.txt` (text outline — Read this to answer questions about windows / paragraphs / elements; each element lists its ITF body with paragraph tags plus a `fields:` summary of `&SYMBOL&` references, truncated with an ellipsis pointer at 200 lines per element), `<name>.wireframe.png` (first-page wireframe — suggest the user opens this to see the form physically), `<name>.preview.html` (interactive HTML preview at near-print scale, with clickable windows, field-symbol tooltips, and grid/border toggles — open in a browser).

**Dialect B only.** Files starting with `SFORM` are accepted. `SSTYL` / `SDOKU` are rejected (different object kinds — not yet supported). Dialect-A files (standard texts / plain ITF) are rejected with `UnsupportedDialect`.

**No writes / edits.** This is a read-only tool. Editing / re-importing a SAPscript form is a later tool.

## RFC Write Tools (syntax_check_rfc / upload_program / test_run)

Apply when calling these three tools.

**`syntax_check_rfc` checks the uploaded version, not local files.** To check edited source, upload first via `upload_program`, then call `syntax_check_rfc`. The `kind` parameter is informational; the underlying FM accepts any TRDIR entry.

**`upload_program` is a write tool — confirm before calling.** Per CLAUDE.md confirmation rules, summarize parameters (name, kind, transport, devclass, lines) and wait for explicit user approval before invoking.
- Updates always go through `RPY_INCLUDE_UPDATE` (works for programs and includes alike). The seemingly natural `RPY_PROGRAM_UPDATE` is NOT RFC-enabled on current S/4 releases.
- Source goes via `SOURCE_EXTENDED` (255-char rows). Lines longer than 255 chars are rejected with `LineTooLong` listing the offending line numbers.
- Transport: pass explicitly, or omit and the tool picks the most recent open Workbench/Customizing TR for the connection user from E070. `$TMP` skips TR resolution entirely.
- Title: re-supplied automatically on updates from the existing TRDIRT row in the connection language — do not need to pass `description` on update.
- A clean post-upload `syntax_check_rfc` is folded into the response under `syntax`.

**`test_run` is async-via-XBP.** Reports are submitted as background jobs (XBP), so this is **not** synchronous SUBMIT — it polls until the job ends or the wall clock exceeds `max_wait_sec`.
- Selection screen: pass values via `params` (PARAMETERS) and `select_options` (SELECT-OPTIONS ranges) OR a saved `variant`. Mixing variant with the others returns `MutuallyExclusive`.
- On `status='aborted'`, the tool reads SNAP via `RFC_READ_TABLE` (header row SEQNO='000', TLV-parsed FLIST tags `FC`/`AP`/`AI`/`AL`/`TD`) to extract the runtime-error name, TID, program, include, and source line. SM21 (`RSLG_READ_FILE`) and joblog parsing are fallbacks if SNAP is empty/unreachable.
- On `status='timeout'`, the job is **not** cancelled — caller can poll via SM37 using the returned `jobname/jobcount`.
- **Auto-cleanup**: jobs in terminal states (`finished`/`aborted`/`cancelled`) are deleted via `BAPI_XBP_JOB_DELETE` after dump correlation. Timeout jobs are left in TBTCO so the caller can monitor them. SNAP rows + ST22 dumps are NOT deleted (audit trail preserved).
- v1 supports executable programs only (TRDIR-SUBC='1'). Class methods, FMs, and module pools are out of scope.

## Tool Usage Rules

Apply these whenever calling `mcp__plugin_sap-rfc_rfc-mcp__*` tools (the namespace Claude assigns when the plugin is installed from a marketplace).

**Connect first.** No tool works until `/sap-connect` has stored credentials in the keyring. If a tool returns `LogonError` or "credentials not found", run `/sap-connect`. If you're unsure which system is connected, call `ping` — it returns SID and release.

**Read-before-execute on the SAP side.** All `rfc-mcp` tools are read-only. Writes and checks (`update_source`, `activate`, `syntax_check`, `transport_create`, `transport_of_object`, `create_program`, `create_include`, `code_inspector`) live on `adt-mcp` and require ADT to be reachable. Never claim you wrote / activated anything from `rfc-mcp`.

**Discover → schema → data.** When investigating a topic:
1. `search_objects` to find the object name (don't guess Z-program names).
2. `get_table_structure` (for tables) or `get_function_module_interface` (for FMs) to learn the shape.
3. `read_table` / `read_source` only after you know what you're asking for.

**`read_table` rules.**
- ALWAYS pass `fields` — selecting all columns risks the 512-char row buffer overflow.
- HARD CAP: 20 rows. The tool truncates silently above that. For volume, write a custom RFC FM, don't loop.
- Pooled / cluster tables (e.g., BSEG, KOCLU) are NOT readable via RFC_READ_TABLE — use a transparent counterpart (BSEG → BSAS/BSIS/BSAK/BSIK) or a CDS view.
- `where` is ABAP/Open-SQL syntax with single-quoted literals: `MANDT EQ '100' AND BUKRS LIKE 'Z%'`. Long clauses auto-chunk to 72-char lines.

**`read_source` rules.**
- Output is a `.abap` file path + line count. Open it with the Read tool ONLY when the source is actually needed for the answer — don't read it eagerly.
- Classes are two-step: first call without `method` to list methods, then call again with `method='NAME'` for the source.
- For function modules, prefer `get_function_module_interface(name, with_source=true)` over `read_source` — it returns interface + source in one call.

**`search_objects` rules.**
- Patterns are upper-case SAP LIKE (`%` wildcard). `'Z%'` good. `'%'` bad (scans all of TADIR, results truncated).
- Filter by `object_types` whenever you can — common codes: `PROG`, `CLAS`, `INTF`, `FUGR`, `TABL`, `STRU`, `DTEL`, `DOMA`, `TRAN`, `MSAG`, `DEVC`.
- Filter by `devclass` (package) for narrow searches.

**Token discipline.**
- `get_function_module_interface(with_source=false)` (default) is small. Set `with_source=true` only when you need the implementation.
- `read_source` is small (file path only). The size cost happens when you Read the file — only do that when the answer requires the actual code.

**Errors.** All tools return `{error: ..., detail: ...}` instead of raising. Treat the error string as ground truth — don't retry blindly. Common patterns: `ABAPApplicationError` (object missing or no auth), `CommunicationError` (network/router), `LogonError` (bad credentials → re-run `/sap-connect`).

## adt-mcp Tool Usage Rules

Apply these whenever calling `mcp__plugin_sap-rfc_adt-mcp__*` tools.

**Existence first.** Every tool that operates on a specific object validates against a non-existent name — SAP's ADT silently returns empty/clean results on missing objects, which would masquerade as success. `code_inspector` pre-probes via GET on the object URI and returns `ObjectNotFound` on 404. Other tools return `ADTError` 404 directly. Never interpret "no findings / no errors" as success without confirming the object actually exists.

**Stateful lock window.** `update_source` lock → PUT → unlock requires `X-sap-adt-sessiontype: stateful` on every request inside the window. `ADTClient.lock()` sets it automatically; `unlock()` clears it in a finally block. If you see HTTP 423 "resource not locked", the stateful header is missing.

**Create order for new objects.** An object must exist before a TR can reference it *and* before `update_source` can write to it. The working order is:
1. `transport_create(name, kind, devclass, text)` → returns TR (the REF does NOT need to point at an existing object; SAP creates the TR bound to the package).
2. `create_program(name, devclass, description, transport=TR)` → creates the empty REPORT header.
3. For each include: `create_include(name, devclass, description, transport=TR, master_program=<main>)` → creates the empty include header. **ALWAYS pass `master_program`** when the include belongs to a specific report; without it SAP refuses to activate ("Select a master program for include ... in the properties view"). Omit `master_program` only for truly shared includes referenced by multiple programs.
4. `update_source(name, kind, source_file, transport=TR)` for each file (main first, then includes) → uploads the source.
5. `syntax_check(name, kind)` / `activate(objects=[…])` — include main program + every include in a single `activate` call.

Bare empty TRs (no object context) cannot be created via ADT — fall back to SE09/SE10 or `BAPI_CTREQUEST_CREATE`.

**Protocol landmarks** (live-verified 2026-04-18 on S/4 HANA DEV):
- `transport_create` → `POST /sap/bc/adt/cts/transports` with `asx:abap` body + `dataname=com.sap.adt.CreateCorrectionRequest` content-type. (The old `/transportrequests` endpoint returns "user action is not supported".)
- `create_program` → `POST /sap/bc/adt/programs/programs?corrNr=<TR>` with `program:abapProgram` XML (adtcore:type=`PROG/P`) + content-type `application/*`.
- `create_include` → `POST /sap/bc/adt/programs/includes?corrNr=<TR>` with `include:abapInclude` XML (adtcore:type=`PROG/I`) + content-type `application/*`. When `master_program` is passed, an `<include:containerRef adtcore:name=<MAIN> adtcore:type="PROG/P" adtcore:uri="/sap/bc/adt/programs/programs/<main_lower>"/>` child is emitted so the include is bound to its report and can be activated.
- `create_class` → `POST /sap/bc/adt/oo/classes?corrNr=<TR>` with `class:abapClass` XML (adtcore:type=`CLAS/OC`) + content-type `application/*`. Creates an empty shell; the full class body (DEFINITION + IMPLEMENTATION, all sections/methods/events/aliases/interfaces/friends) is uploaded in one PUT via `update_source(kind='class')` → `/sap/bc/adt/oo/classes/<NAME>/source/main`. There is NO per-method/per-section ADT write endpoint for regular classes — `source/main` takes the complete class pool text and SAP parses it. Activation via `activate(objects=[{name, kind:'class'}])` works with no `context=` quirk (only includes need that).
- `code_inspector` → three-step worklist: `POST /atc/worklists?checkVariant=<V>` → `POST /atc/runs?worklistId=<id>` → `GET /atc/worklists/<id>` (Accept `application/atc.worklist.v1+xml`). The older `/checkruns?reporters=atcChecker` path returns 200 with empty body on modern releases.
- `transport_of_object` → `POST /sap/bc/adt/cts/transportchecks` with asx body; parse `LOCKS/CTS_OBJECT_LOCK/LOCK_HOLDER/REQ_HEADER` for the locking TR (request) — task sub-records are filtered out.
- `activate` → `POST /sap/bc/adt/activation?method=activate&preauditRequested=true` with `<adtcore:objectReferences>`. For each include child, the URI MUST carry `?context=<master_program_uri>` (e.g. `/sap/bc/adt/programs/includes/ZFOO_F01?context=/sap/bc/adt/programs/programs/ZFOO`); without it SAP returns HTTP 500 "Select a master program for include ... in the properties view" even when the include's stored `contextRef` points at the right report. The tool auto-resolves the context by GETting the include and reading its `contextRef/@adtcore:uri` when `master_program` is not supplied on the objectReference. Error responses use `<msg><shortText><txt>...</txt></shortText></msg>` (nested) on modern releases, not the old `shortText=""` attribute — parser must read both.

**Confirm before write.** `transport_create`, `create_program`, `create_include`, `update_source`, `activate` modify the system. ALWAYS summarize the exact parameters back to the user and wait for explicit approval before calling.

**Text elements are NOT in adt-mcp.** Probed 2026-04-19 on S/4 HANA DEV: `/sap/bc/adt/textelements/programs/<name>/source/symbols` (the URL documented in abap-adt-api / vscode_abap_remote_fs) returns 404 on this release — the ADT handler isn't registered. The program's own `/sap/bc/adt/programs/programs/<name>` response advertises the textelements link as `type="application/vnd.sap.sapgui"` (SAP GUI launch fallback), not a REST resource. Use the `read_text_pool` / `update_text_pool` tools in `rfc-mcp` instead — they go through `RPY_PROGRAM_READ` + `RPY_TEXTELEMENTS_INSERT`.

## Text Pool Tool Rules

Apply when using `read_text_pool` / `update_text_pool`.

**Write flow is read-merge-write.** `update_text_pool` reads the current pool, overlays incoming `(id, key)` entries, and writes the full union. Callers pass only the rows they want to add or change — untouched entries are preserved automatically. To *delete* an entry, fetch the pool, drop the row client-side, and pass the full remaining list (delete-by-omission only works when you send the whole pool; otherwise the old row stays).

**Language resolution.** Both tools accept an optional `language` (1-char SAP SY-LANGU like `E`, `D`, `U`, `8` for Ukrainian). When omitted, they resolve from `TRDIR.RLOAD` (the program's master language); if RLOAD is blank, they fall back to the RFC logon language. Do NOT pass ISO codes like `UK` or `RU` — SAP uses single-char internal codes.

**Selection-text 8-space prefix.** SAP stores `ID='S'` entries with 8 leading spaces for field-label alignment. `read_text_pool` strips the prefix before returning; `update_text_pool` re-adds it before writing. Callers work with raw text in both directions.

**Entry ID legend.**
- `R` — report title. `key` must be empty.
- `I` — text symbol (TEXT-xxx). `key` is a 3-char id like `001`.
- `S` — selection text. `key` is the SELECT-OPTIONS / PARAMETERS name (max 8 chars, upper-cased).

**Transport required.** `update_text_pool` must be given an existing TR/task number. Devclass is resolved from TADIR automatically (no caller input).

## Key Design Decisions

- **File-based source output**: Tools that return ABAP source write to `.abap` files in a persistent cache dir and return `source_file` path + `line_count` instead of inline source. This saves tokens — Claude reads files via Read tool only when needed.
- **Connection per call**: No persistent connection pool. `get_connection()` creates a new `pyrfc.Connection` each time from keyring values.
- **Hard row limit**: `read_table` caps at 20 rows (`MAX_ROWS = 20`), enforced in the tool.
- **WHERE clause chunking**: Long WHERE strings are split into 72-char chunks (SAP RFC_READ_TABLE limit).
- **Class method reading**: Uses TMDIR table to find method index, then constructs the include name (`CLASS====...CM###`) and reads via `RPY_PROGRAM_READ`.
- **Stateful ADT session**: `adt-mcp` flips `X-sap-adt-sessiontype: stateful` on during `lock()` and clears it on `unlock()`. SAP's ADT locks are bound to the stateful work process; stateless calls get a fresh process each request and the lock evaporates before the PUT.
- **Keyring keys**: `ashost`, `sysnr`, `client`, `user`, `passwd`, `lang`, `saprouter`, `workspace`, `adt_url`, `adt_verify_tls`, `adt_timeout` — all under service name `sap-rfc`. Single source of truth: `plugins/sap-rfc/skills/_keyring_shared.py` (imported by `connect.py` and `disconnect.py`). `adt_url` is auto-populated by `adt-mcp` discovery; `adt_verify_tls='1'` enables strict TLS (default off for self-signed dev systems); `adt_timeout` is per-call seconds (default 30).

## Development

**Python deps** (for local `pyrfc` + tests):
```bash
pip install -r plugins/sap-rfc/requirements.txt          # runtime
pip install -r plugins/sap-rfc/requirements-dev.txt      # adds pytest + responses
```
`pyrfc` requires the SAP NW RFC SDK on PATH/LD_LIBRARY_PATH.

**Local development install** (point Claude Code at the working tree, not GitHub):
```bash
claude plugin marketplace add /absolute/path/to/sap-rfc
claude plugin install sap-rfc@sap-rfc-marketplace
```
End users install from GitHub instead — see the README. After editing skills or `server.py`, restart Claude Code to pick up changes.

**Run offline tests** (no SAP needed):
```bash
cd plugins/sap-rfc/servers/rfc-mcp && pytest
```

## User Commands

The plugin exposes three slash commands (all routed through the tkinter dialog — password never enters chat):
- `/sap-connect` — parse SAPUILandscape.xml or manual entry, store creds in OS keyring, call `ping` to verify.
- `/sap-disconnect` — remove credentials from keyring.
- `/sap-change-connection` — disconnect + reconnect.
