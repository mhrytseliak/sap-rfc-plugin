# Changelog

All notable changes to this plugin are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-05-10

### Added

- **`syntax_check_rfc`** (rfc-mcp). Full ABAP syntax check via
  `RS_ABAP_SYNTAX_CHECK_E`. Returns errors / warnings / infos as structured
  rows with include name, line, column, keyword, msg-no, message text. Replaces
  reliance on `SIW_RFC_SYNTAX_CHECK` (one error, no include name).
- **`upload_program`** (rfc-mcp). Create or update an ABAP program / include
  via RFC. Auto-routes through `RPY_PROGRAM_INSERT` / `RPY_INCLUDE_INSERT` /
  `RPY_INCLUDE_UPDATE` based on existence (the seemingly natural
  `RPY_PROGRAM_UPDATE` is NOT RFC-enabled on modern S/4 — `RPY_INCLUDE_UPDATE`
  works for programs too because it operates on TRDIR by name). Auto-resolves
  the most recent open Workbench/Customizing TR from E070 when caller omits
  `transport`. Auto-activates. Runs `syntax_check_rfc` post-upload and folds
  the result into the response.
- **`test_run`** (rfc-mcp). Submits a report as a one-step XBP background job
  (`BAPI_XMI_LOGON` → `BAPI_XBP_JOB_OPEN/ADD_ABAP_STEP/CLOSE/START_ASAP`),
  polls `BAPI_XBP_JOB_STATUS_GET` until done / aborted / cancelled / timeout,
  and returns the joblog plus a structured `dump` dict on abort. Selection
  screen passes through `params` (PARAMETERS) and `select_options`
  (SELECT-OPTIONS) or a saved `variant`.
- **Three-tier dump correlation** for `test_run` aborts: SNAP via
  `RFC_READ_TABLE` (TLV-parsed FLIST tags FC/AP/AI/AL/TD — gives runtime-error
  name, TID, program, include, source line) → SM21 via `RSLG_READ_FILE` →
  joblog text scrape. SNAP is readable on modern S/4 releases despite older
  docs claiming it's unreadable via RFC.
- **Auto-cleanup** for `test_run`. Jobs that reach a terminal state
  (finished / aborted / cancelled) are deleted via `BAPI_XBP_JOB_DELETE`
  after dump correlation. Timeout jobs are left in TBTCO so the caller can
  still poll them via SM37. SNAP rows + ST22 dumps are NOT deleted (audit
  trail preserved).

### Changed

- **rfc-mcp is no longer read-only.** The server now offers four write tools:
  `update_text_pool` (existing), `upload_program`, `syntax_check_rfc` (probe-
  style), `test_run`. `adt-mcp` remains the HTTP path; the two are
  alternatives — choose RFC when ADT isn't reachable.

## [0.2.0] — 2026-04-29

### Added

- **rfc-mcp wall-clock timeouts.** Every RFC tool now runs under a configurable
  timeout (default 60s, `ping` overrides to 10s) so a hung `pyrfc` call cannot
  block a tool indefinitely. Configurable via the `rfc_timeout` keyring key.
  Returns `{error: "Timeout", detail: "..."}` on hit.
- **Per-server READMEs** (`servers/rfc-mcp/README.md`, `servers/adt-mcp/README.md`)
  ship with the plugin. End users installing from GitHub now get protocol
  landmarks, hard rules, and per-tool rules without needing the project's
  `CLAUDE.md`.
- **Skill hardening for `/sap-connect`.** Added "Red flags" section (7
  rationalizations) and "Common mistakes" table (6 rows) catching chat-input
  fallbacks under tkinter / time-pressure scenarios. Test-driven: pressure
  scenarios were run RED → updated skill → GREEN.

### Changed

- **Tool outputs trimmed across both servers** (breaking change for callers
  parsing responses). Rule applied: don't echo inputs, don't repeat data,
  return only what the caller couldn't compute. Token savings 20-80% per call.
  - `ping` (rfc): dropped `status`, `database`, `s4_hana`.
  - `read_text_pool`: dropped per-entry `length`.
  - `search_objects`: dropped `count` (use `len(results)`).
  - `syntax_check`: dropped `object` echo, dropped per-finding `uri`.
  - `transport_of_object`: dropped `obj_name`, `kind` echo.
  - `activate`: dropped `activated[]` tautology, dropped redundant `errors[]`
    (caller filters from `messages` by `severity == "E"`).
  - `code_inspector`: dropped `object` echo, `worklist_id`, per-finding
    `object_name`/`object_type`/`uri`.
  - All adt-mcp errors: dropped `tried[]` from `ADTNotAvailable` (URLs already
    in `detail`).
- TLS-verify default in `adt_client.py` aligned with `discovery.py` and docs
  (permissive when `adt_verify_tls` is unset; strict only when `="1"`).
- `transport_create` Content-Type fixed in `adt-mcp/README.md` to match
  implementation (`application/vnd.sap.as+xml; ...`).

### Fixed

- `/sap-connect` now invalidates `adt_url`, `adt_verify_tls`, `adt_timeout`
  before storing new credentials. Previously, switching SAP systems left a
  stale ADT URL from the previous system, producing misleading 401s.
- Reverted `userConfig.python_path` (introduced briefly in 0.1.1 polish) — it
  broke MCP server spawn for already-installed plugins because `userConfig`
  values are only collected on initial enable. Restored bare `"python"`.
- `update_source` docstring no longer claims object creation is "deferred";
  `create_program` / `create_include` / `create_class` exist now.
- Skill frontmatter: removed wrong `user_invocable` field (spec uses
  `user-invocable`; default `true` was already correct).
- Marketplace manifest: dropped unrecognized `metadata.last_updated` /
  `total_plugins` fields, dropped duplicated `description` on plugin entry to
  prevent drift against `plugin.json`.
- Root `README.md`: rfc-mcp tool count `8 → 9`, added missing `read_form` row,
  noted `update_text_pool` as the lone non-read-only tool.

### Notes

Trimmed tool outputs are technically a breaking change for any consumer
parsing the responses. If you scripted against the previous shape, update
your code; the docstrings and per-server READMEs document the new shapes.

## [0.1.1] — 2026-04-28

Initial public release.

- `rfc-mcp` server: 9 read-only RFC tools (`ping`, `search_objects`,
  `get_table_structure`, `read_table`, `read_source`,
  `get_function_module_interface`, `read_text_pool`, `update_text_pool`,
  `read_form`).
- `adt-mcp` server: 10 ADT write/check tools (`ping`, `syntax_check`,
  `transport_of_object`, `transport_create`, `create_program`,
  `create_include`, `create_class`, `update_source`, `activate`,
  `code_inspector`).
- Skills: `/sap-connect`, `/sap-disconnect`, `/sap-change-connection`.
  Credentials stored in OS keyring; password never enters chat.
