# adt-mcp

ADT (Abap Development Tools) MCP server. Write + check flows over HTTP — `update_source`, `activate`, `transport_create`, `create_program`, `create_include`, `create_class`, `syntax_check`, `code_inspector`, `transport_of_object`, `ping`.

Connection setup: `/sap-connect` (see plugin root). ADT base URL is auto-discovered from `ICM_GET_INFO` and cached in the OS keyring as `adt_url`.

## Tool overview

| Tool | What it does |
|------|--------------|
| `ping` | Reach the ADT base URL; returns the resolved URL on success or `ADTNotAvailable` if no candidate is reachable. |
| `syntax_check` | Compile-check a single object (`program`, `include`, `class`). Returns severity + messages. |
| `transport_of_object` | Find the locking TR for an object, if any. |
| `transport_create` | Create a new transport bound to a package + ref object. |
| `create_program` | Create an empty `REPORT` shell. Source is uploaded separately. |
| `create_include` | Create an empty include shell. Pass `master_program` so the include can be activated. |
| `create_class` | Create an empty class shell (`CLAS/OC`). Full class body is uploaded via `update_source`. |
| `update_source` | Lock → PUT source → unlock. Stateful session window. |
| `activate` | Activate one or many objects in a single call. Includes need a context URI. |
| `code_inspector` | Run an ATC variant via the 3-step worklist API. |

## Hard rules

### 1. ADT must be reachable

Every tool first probes the cached `adt_url`. If it's stale and discovery cannot resolve a fresh one (e.g., user is off corp VPN), tools return `{error: "ADTNotAvailable"}`. The expected fallback is **manual activation in SAP GUI** — do not retry blindly, and do not pretend a write succeeded when ADT is down.

### 2. Existence first

ADT silently returns empty / clean results on missing objects, which masquerades as success:

- `code_inspector` pre-probes via GET on the object URI and returns `ObjectNotFound` on 404.
- The other write/check tools return `ADTError 404` directly.

**Never interpret "no findings / no errors" as success without confirming the object actually exists.**

### 3. Stateful lock window

`update_source` is a three-step flow: `lock(?accessMode=MODIFY)` → `PUT source/main` → `unlock`. SAP requires `X-sap-adt-sessiontype: stateful` on every request inside that window — without it the work process changes between requests and the lock evaporates, returning HTTP 423 *resource not locked* on the PUT.

The `ADTClient` toggles the header automatically on `lock()` and clears it on `unlock()` (in a `finally` block). Do not call `update_source` from outside the client — the manual stateful header dance is easy to get wrong.

### 4. Create order for new objects

An object must exist before a TR can reference it AND before `update_source` can write to it. The working order:

1. `transport_create(name, kind, devclass, text)` → returns TR. The ref does NOT need to point at an existing object; SAP creates the TR bound to the package.
2. `create_program(...)` / `create_include(..., master_program=<main>)` / `create_class(...)` → empty header.
3. `update_source(name, kind, source_file, transport=TR)` → upload source. Main first, then includes.
4. `activate(objects=[main + every include])` → in a **single call**.

**Always pass `master_program` on `create_include`** when the include belongs to a specific report. Without it SAP refuses to activate ("Select a master program for include … in the properties view"). Omit `master_program` only for shared includes referenced by multiple programs.

Bare empty TRs (no object context) cannot be created via ADT — fall back to SE09/SE10 or `BAPI_CTREQUEST_CREATE`.

### 5. Confirm before write

`transport_create`, `create_program`, `create_include`, `create_class`, `update_source`, `activate` modify the system. Always summarize the exact parameters back to the user and wait for explicit approval before calling.

## Protocol landmarks

Live-verified against S/4 HANA. Public documentation and third-party libraries (abap-adt-api, vscode_abap_remote_fs) lag the ABAP platform; what's listed here is what works on current releases.

### `transport_create`

- `POST /sap/bc/adt/cts/transports`
- Body: `asx:abap` envelope with the create-correction-request payload.
- Content-Type: `application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.CreateCorrectionRequest`.
- The older `/transportrequests` endpoint returns *user action is not supported*.

### `create_program`

- `POST /sap/bc/adt/programs/programs?corrNr=<TR>`
- Body: `program:abapProgram` XML with `adtcore:type="PROG/P"`.
- Content-Type: `application/*`.

### `create_include`

- `POST /sap/bc/adt/programs/includes?corrNr=<TR>`
- Body: `include:abapInclude` XML with `adtcore:type="PROG/I"`.
- When `master_program` is passed, an `<include:containerRef adtcore:name="<MAIN>" adtcore:type="PROG/P" adtcore:uri="/sap/bc/adt/programs/programs/<main_lower>"/>` child is emitted so the include is bound to its report and can be activated.

### `create_class`

- `POST /sap/bc/adt/oo/classes?corrNr=<TR>`
- Body: `class:abapClass` XML with `adtcore:type="CLAS/OC"`.
- Creates an empty shell.
- The full class body (DEFINITION + IMPLEMENTATION, all sections / methods / events / aliases / interfaces / friends) is uploaded in **one** PUT via `update_source(kind='class')` → `/sap/bc/adt/oo/classes/<NAME>/source/main`. There is no per-method or per-section ADT write endpoint for regular classes — `source/main` takes the complete class pool text and SAP parses it.
- Activate via `activate(objects=[{name, kind:'class'}])` — no `context=` quirk (only includes need that).

### `code_inspector`

Three-step worklist API:

1. `POST /atc/worklists?checkVariant=<V>` → returns worklist id.
2. `POST /atc/runs?worklistId=<id>` → triggers the run.
3. `GET /atc/worklists/<id>` (Accept `application/atc.worklist.v1+xml`) → fetch findings.

The older `/checkruns?reporters=atcChecker` path returns 200 with empty body on modern releases.

### `transport_of_object`

- `POST /sap/bc/adt/cts/transportchecks` (NOT `GET searchobject`) with `asx:abap` body.
- Parse `LOCKS/CTS_OBJECT_LOCK/LOCK_HOLDER/REQ_HEADER` for the locking TR (request) — task sub-records are filtered out.

### `activate`

- `POST /sap/bc/adt/activation?method=activate&preauditRequested=true` with `<adtcore:objectReferences>`.
- For each include child, the URI MUST carry `?context=<master_program_uri>` (e.g. `/sap/bc/adt/programs/includes/ZFOO_F01?context=/sap/bc/adt/programs/programs/zfoo`). Without it SAP returns HTTP 500 *Select a master program for include … in the properties view* even when the include's stored `contextRef` points at the right report.
- The tool auto-resolves the context by GETting the include and reading its `contextRef/@adtcore:uri` when `master_program` is not supplied on the objectReference.
- Error responses use `<msg><shortText><txt>...</txt></shortText></msg>` (nested) on modern releases, not the old `shortText=""` attribute. The parser must read both.

## Text elements are NOT in adt-mcp

`/sap/bc/adt/textelements/programs/<name>/source/symbols` (the URL documented in abap-adt-api / vscode_abap_remote_fs) returns 404 on current releases — the ADT handler isn't registered. The program's own `/sap/bc/adt/programs/programs/<name>` response advertises the textelements link as `type="application/vnd.sap.sapgui"` (SAP GUI launch fallback), not a REST resource.

Use `read_text_pool` / `update_text_pool` from rfc-mcp instead — they go through `RPY_PROGRAM_READ` + `RPY_TEXTELEMENTS_INSERT`.

## Errors

All tools return `{error, detail}` instead of raising. Common patterns:

| `error` | Cause |
|---------|-------|
| `ADTNotAvailable` | No reachable ADT endpoint. Off VPN, ICM disabled, or the cached `adt_url` is stale and rediscovery failed. Fall back to SAP GUI for this stage. |
| `ADTError` 401 | Bad keyring credentials. Run `/sap-disconnect` and `/sap-connect`. |
| `ADTError` 403 | Authorization missing for the object/operation. |
| `ADTError` 404 | Object does not exist. For writes/checks, check the name; for reads, the object may have been deleted. |
| `ADTError` 423 | Resource not locked (stateful header missing or lost) or already locked by another user. |
| `ADTError` 500 | Server-side error. The detail usually contains a SAP exception message — read it. |

## Keyring keys (set by `/sap-connect`)

| Key | Default | Purpose |
|-----|---------|---------|
| `adt_url` | (auto-discovered) | Cached base URL, e.g. `https://my-host:44300/sap/bc/adt`. |
| `adt_verify_tls` | `0` | `1` for strict TLS; `0` accepts self-signed (dev systems). |
| `adt_timeout` | `30` | Per-call seconds. |

## Offline tests

```bash
cd plugins/sap-rfc/servers/adt-mcp
pytest
```

Uses the `responses` library — no live SAP needed.
