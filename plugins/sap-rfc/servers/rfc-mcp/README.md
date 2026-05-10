# rfc-mcp

SAP RFC MCP server. Read + write over `pyrfc`. Source / table / DDIC / FM / text pool reads, SAPscript form parser, plus a write path that doesn't need ADT: source upload, syntax check, and dump-detecting test execution. Designed for systems where ADT is not reachable.

Connection setup: `/sap-connect` (see plugin root). Each tool call opens a fresh `pyrfc.Connection` from OS-keyring credentials and closes it.

## Tool overview

| Tool | RFC backing | What it does |
|------|-------------|--------------|
| `ping` | `RFC_PING`, `RFC_SYSTEM_INFO` | Sanity check + system info (SID, release, host, workspace label). |
| `search_objects` | `RFC_READ_TABLE` → TADIR | Discover object names by pattern + type + devclass. |
| `get_table_structure` | `DDIF_FIELDINFO_GET` | DDIC fields (field, type, length, key, description). |
| `read_table` | `RFC_READ_TABLE` | Read up to 20 rows. WHERE auto-chunked. |
| `read_source` | `RPY_PROGRAM_READ` | Program / include / class method source → `.abap` file. |
| `get_function_module_interface` | `RPY_FUNCTIONMODULE_READ_NEW` | FM signature (+ optional source). |
| `read_text_pool` | `RPY_PROGRAM_READ` (TEXTELEMENTS) | Report title / text symbols / sel-texts. |
| `update_text_pool` | `RPY_TEXTELEMENTS_INSERT` | Read-merge-write text pool. Transport-bound. |
| `syntax_check_rfc` | `RS_ABAP_SYNTAX_CHECK_E` | Full SLIN-style syntax check on the uploaded version. Returns errors / warnings / infos with include + line + col + msg-no. |
| `upload_program` | `RPY_PROGRAM_INSERT` / `RPY_INCLUDE_INSERT` / `RPY_INCLUDE_UPDATE` | Create or update programs and includes. Auto-resolves open TR from E070, auto-activates, runs syntax check post-upload. |
| `test_run` | `BAPI_XMI_LOGON` + `BAPI_XBP_JOB_*` + `RFC_READ_TABLE` (SNAP) + `RSLG_READ_FILE` | Submit report as XBP job, poll until done / aborted / timeout. On abort, returns structured dump info (runtime error, TID, program, include, line) parsed from SNAP. Auto-deletes terminal jobs. |
| `read_form` | (offline) | Parse a SAPscript form export (`.FOR`) into outline + PNG + HTML. No SAP needed. |

## Hard rules

### 1. Connect first

No tool works until `/sap-connect` has stored credentials in the keyring. `LogonError` / *credentials not found* → run `/sap-connect`. If unsure which system is connected, call `ping` — it returns SID and release.

### 2. Two write paths — choose the one that fits

**rfc-mcp** writes via standard SAP RFC FMs: `update_text_pool`, `upload_program`, `test_run`. No ADT needed. **adt-mcp** writes via HTTP/ADT: `update_source`, `activate`, `syntax_check`, `transport_create`, `transport_of_object`, `create_program`, `create_include`, `create_class`, `code_inspector`. Use rfc-mcp when ADT isn't reachable; use adt-mcp when you need ADT-only flows (class shells, separate activate step, code inspector). The two are alternatives — don't mix tools for one logical write.

### 3. Discover → schema → data

When investigating a topic, always go in this order:

1. `search_objects` to find the object name (don't guess Z-program names).
2. `get_table_structure` (for tables) or `get_function_module_interface` (for FMs) to learn the shape.
3. `read_table` / `read_source` only after you know what you're asking for.

## Per-tool rules

### `read_table`

- **Always pass `fields`.** Without it, RFC_READ_TABLE returns all columns concatenated and may overflow the 512-char row buffer.
- **Hard cap: 20 rows.** The tool truncates silently above that. For volume, write a custom RFC FM — don't loop.
- **Pooled / cluster tables are NOT readable.** BSEG, KOCLU, etc. fail under RFC_READ_TABLE. Use a transparent counterpart (BSEG → BSAS / BSIS / BSAK / BSIK) or a CDS view.
- **`where` syntax is ABAP / Open-SQL** with single-quoted literals: `MANDT EQ '100' AND BUKRS LIKE 'Z%'`. Long clauses auto-chunk to 72-char lines (the RFC_READ_TABLE limit).

### `read_source`

- Output is a `.abap` file path + line count. Open the file via the Read tool **only when the source is actually needed** for the answer.
- **Classes are two-step**: first call without `method` to list methods, then call again with `method='NAME'` for the source.
- **For function modules**, prefer `get_function_module_interface(name, with_source=true)` over `read_source` — it returns interface + source in one call.

### `search_objects`

- Patterns are upper-case SAP LIKE (`%` wildcard). `'Z%'` good. `'%'` bad — scans all of TADIR, results truncated.
- **Filter by `object_types` whenever you can.** Common codes: `PROG`, `CLAS`, `INTF`, `FUGR`, `TABL`, `STRU`, `DTEL`, `DOMA`, `TRAN`, `MSAG`, `DEVC`.
- **Filter by `devclass`** (package) for narrow searches.

### `get_function_module_interface`

- `with_source=False` (default) is small and cheap.
- Set `with_source=True` only when you need the implementation. It reads `NEW_SOURCE` (full-width lines) and writes the body to a `.abap` file. The old `RPY_FUNCTIONMODULE_READ` caps lines at 72 chars and raises SAP message 180 on many modern FMs — this tool uses `RPY_FUNCTIONMODULE_READ_NEW` to avoid that.

### Text pool tools (`read_text_pool`, `update_text_pool`)

#### Write flow is read-merge-write

`update_text_pool` reads the current pool, overlays incoming `(id, key)` entries, and writes the full union. Pass only the rows you want to add or change — untouched entries are preserved automatically.

To **delete** an entry, fetch the pool, drop the row client-side, and pass the full remaining list. Delete-by-omission only works when you send the whole pool; otherwise the old row stays.

#### Language resolution

Both tools accept an optional `language` (1-char SAP SY-LANGU like `E`, `D`, `U`, `8` for Ukrainian). When omitted, they resolve from `TRDIR.RLOAD` (the program's master language); if RLOAD is blank, they fall back to the RFC logon language. **Do NOT pass ISO codes** like `UK` or `RU` — SAP uses single-char internal codes.

#### Selection-text 8-space prefix

SAP stores `ID='S'` entries with 8 leading spaces for field-label alignment. `read_text_pool` strips the prefix before returning; `update_text_pool` re-adds it before writing. Callers work with raw text in both directions.

#### Entry ID legend

| ID | Meaning | Key |
|----|---------|-----|
| `R` | Report title | empty |
| `I` | Text symbol (TEXT-xxx) | 3-char id like `001` |
| `S` | Selection text | SELECT-OPTIONS / PARAMETERS name (max 8 chars, upper-cased) |

#### Transport required

`update_text_pool` requires an existing TR / task number. Devclass is resolved from TADIR automatically (no caller input).

### `read_form` (SAPscript)

**Offline, file-based.** v1 does NOT read from SAP. The user must first run `RSTXSCRP` (mode `EXPORT`, object `FORM`, `FSECURE=L`) to produce a `.FOR` file. Live reads via `READ_FORM` / `READ_FORM_LINES` are not RFC-enabled — a Z-wrapper FM is a future addition.

**Four artefacts, one call.** The tool writes to the sap-rfc cache dir:

| File | Purpose |
|------|---------|
| `<name>.FOR` | Source copy |
| `<name>.outline.txt` | Text outline — Read this to answer questions about windows / paragraphs / elements. Each element lists its ITF body with paragraph tags plus a `fields:` summary of `&SYMBOL&` references, truncated with an ellipsis pointer at 200 lines per element. |
| `<name>.wireframe.png` | First-page wireframe — suggest the user opens this to see the form physically. |
| `<name>.preview.html` | Interactive HTML preview at near-print scale, with clickable windows, field-symbol tooltips, and grid / border toggles. Open in a browser. |

**Dialect B only.** Files starting with `SFORM` are accepted. `SSTYL` / `SDOKU` are rejected (different object kinds — not yet supported). Dialect-A files (standard texts / plain ITF) are rejected with `UnsupportedDialect`.

**No writes / edits.** This is a read-only tool. Editing / re-importing a SAPscript form is a later tool.

### `syntax_check_rfc`

**Checks the uploaded version, not local files.** To check edited source, upload it first via `upload_program` and then call `syntax_check_rfc`. The `kind` parameter is informational; the underlying FM accepts any TRDIR entry.

### `upload_program`

**Write tool — confirm before calling.** Summarize parameters (name, kind, transport, devclass, lines) and wait for explicit user approval before invoking.

- Updates always go through `RPY_INCLUDE_UPDATE` (works for programs and includes alike). The seemingly natural `RPY_PROGRAM_UPDATE` is NOT RFC-enabled on current S/4 releases.
- Source goes via `SOURCE_EXTENDED` (255-char rows). Lines longer than 255 chars are rejected with `LineTooLong` listing the offending line numbers.
- **Transport.** Pass explicitly, or omit and the tool picks the most recent open Workbench/Customizing TR for the connection user from E070. `$TMP` skips TR resolution entirely.
- **Title.** Re-supplied automatically on updates from the existing TRDIRT row in the connection language — no need to pass `description` on update.
- A clean post-upload `syntax_check_rfc` is folded into the response under `syntax`.

### `test_run`

**Async via XBP, not synchronous SUBMIT.** The report runs as a one-step background job; the tool polls until the job ends or `max_wait_sec` runs out.

- **Selection screen.** Pass values via `params` (PARAMETERS) and `select_options` (SELECT-OPTIONS ranges) OR a saved `variant`. Mixing variant with the others returns `MutuallyExclusive`.
- **Dump correlation on `status='aborted'`.** Three-tier: SNAP via `RFC_READ_TABLE` (header row SEQNO='000', TLV-parsed FLIST tags `FC`/`AP`/`AI`/`AL`/`TD` for runtime-error name + TID + program + include + line) → SM21 via `RSLG_READ_FILE` → joblog scrape. The SNAP path is primary because modern S/4 makes the table readable.
- **`status='timeout'`.** Job is **not** cancelled — caller can poll later via SM37 with the returned `jobname`/`jobcount`.
- **Auto-cleanup.** Terminal jobs (finished / aborted / cancelled) are deleted via `BAPI_XBP_JOB_DELETE` after dump correlation. Timeout jobs are left in TBTCO. SNAP rows + ST22 dumps are NOT deleted (audit trail preserved).
- v1 supports executable programs only (TRDIR-SUBC='1'). Class methods, FMs, and module pools are out of scope.

## Token discipline

- Source-returning tools (`read_source`, `get_function_module_interface(with_source=true)`) write `.abap` files to a persistent cache dir and return `{source_file, line_count}`. The size cost happens when you Read the file — only do that when the answer requires the actual code.
- `read_table` results scale with `max_rows` × column width. Pass narrow `fields` lists, especially when you only need keys.

## Errors

All tools return `{error, detail}` instead of raising.

| `error` | Cause |
|---------|-------|
| `LogonError` | Bad credentials. Re-run `/sap-connect`. |
| `CommunicationError` | Network / router / host unreachable. Often a VPN issue. |
| `ABAPApplicationError` | Object missing or no authorization. |

Treat the error string as ground truth — don't retry blindly.

## Offline tests

```bash
cd plugins/sap-rfc/servers/rfc-mcp
pytest
```

Covers `cache` and `where_clause` modules. No live SAP needed.
