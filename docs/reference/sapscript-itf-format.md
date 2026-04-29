# SAPscript ITF Format — RSTXSCRP export/import

Reference for the file format produced by report `RSTXSCRP` when exporting SAPscript forms, styles, and standard texts to a local file. Captured 2026-04-21 while figuring out the round-trip workflow (export → edit locally → re-import).

## Why this matters for sap-rfc

The `sap-rfc` plugin currently has **no tool for SAPscript objects** — `rfc-mcp` covers programs/classes/FMs/DDIC via source RFCs, but SAPscript forms live in `STXH`/`STXL` (header + compressed line cluster) and are only accessible via dedicated FMs (`READ_FORM`, `SAVE_FORM`, `READ_TEXT`, `SAVE_TEXT`) or the `RSTXSCRP` report.

Until a proper SAPscript tool is added to the plugin, the practical workflow is:
1. User runs `RSTXSCRP` in SAP GUI (mode `EXPORT`) to dump a form to a local file.
2. Claude edits the file locally, following the rules below.
3. User runs `RSTXSCRP` (mode `IMPORT`) to load it back.

## Storage model

- **STXH** — header table. One row per text object: form header, paragraph/char format defs, window def, page def, text element. Keyed by `TDOBJECT` + `TDNAME` + `TDID` + `TDSPRAS`.
- **STXL** — line cluster. Contains the actual text lines in **compressed ITF** (TEXTPOOL-like packed format). Never read STXL directly — go through `READ_TEXT` or `RSTXSCRP`.
- **Runtime ITF** — what you get after `READ_TEXT`: an itab of `tline` structures, each `{TDFORMAT (CHAR 2), TDLINE (CHAR 132)}`.

The **2-character tag in `TDFORMAT`** is what RSTXSCRP preserves as the classic "columns 1–2" ITF marker.

## Two file-format dialects

RSTXSCRP can produce two different on-disk layouts depending on mode:

### Dialect A — "Classic ITF" (paragraph formats, single text)

Simple flat file. Each line is:
```
XX<content>
```
where `XX` is the 2-char `TDFORMAT` and the rest is the line text. Max 132 chars of content per line.

This is what you get when you export a **single standard text** (mode EXPORT, object `TEXT`) or use `DOWNLOAD_TEXT` / `UPLOAD_TEXT`.

### Dialect B — "Full form export" (what J_2GLP_D.FOR looks like)

Wrapped structure with metadata framing. Record tag is in **columns 1–5**, not 1–2. Confirmed from a real export:

```
SFORM<form_name_padded>              ← Start of form
HFORM<form_name_padded>              ← Header of form
 OLANG                               ← Original language marker
 HEAD<packed_metadata_with_checksum_size_author_timestamp>
 LINE<classic_ITF_line>              ← Body: 2-char TDFORMAT begins at col 6
 LINE<classic_ITF_line>
 ...
 END                                 ← End of sub-object
 HEADFORM<...>TXT<lang>...            ← Next sub-object: translations in language X
 LINE<...>
 END
```

Each sub-object (form definition, text translations per language, paragraph format descriptions, etc.) is framed by its own `HEAD`...`END` pair.

**Record tag layout.** The first 5 bytes hold the record tag. Leading-space convention is inconsistent:
- No leading space: `SFORM<name>`, `HFORM<name>`.
- One leading space: ` LINE<tf><content>`, ` HEAD<meta>`, ` END`, ` OLANG`, ` ACTV` (trailer).

Inside a ` LINE` record, cols 6-7 are the 2-char `TDFORMAT`; cols 8+ are the line content. Element / window markers have NO space between the tag and the name — they're glued directly:
- ` LINE/:FORM CPI 12;` — `/:` control statement
- ` LINE/*DO NOT SHOW` — `/*` comment
- ` LINE/EITEM_LINE` — `/E` element marker (name glued to tag)
- ` LINE/WMAIN` — `/W` window marker (name glued to tag)
- ` LINEIT<B>Text</>` — `IT` paragraph format
- ` LINEL &FIELD&` — `L ` paragraph format (left-justified)
- ` LINE= continuation` — `= ` continuation of previous line

### Identifying which dialect you have

| First line starts with | Dialect |
|---|---|
| `SFORM` or `SSTYL` or `SDOKU` | B (full export) |
| 2 chars that look like a tag (`/:`, `L `, `* `, etc.) | A (classic) |

The J_2GLP_D.FOR example is dialect B.

## HEAD record anatomy (dialect B)

Observed example (line wrapped for readability; in the file it's one physical line):
```
 HEADFORM      J_2GLP_DASD     SAP    [spaces]    DEF G
 For printing DA(SD)    [spaces]
 J_2GLP_DASD    [spaces]
 00000C5000334    22E
 19970602132525CCC00419    756
 2025062511370113200059 G0    [spaces]    200
```

Fields observed:
- `FORM` / `STYL` / `TEXT` — object type
- Object name (padded to fixed width, ~30 chars)
- Author / origin (`SAP`, or user)
- `DEF G` or `TXT E` — record kind (definition vs text translation) + language
- Description
- Object name (repeated)
- **`00000C5000334`** — looks like a size/checksum (hex digits + decimal count). Second number (`000334`) likely = byte count of the block between this HEAD and the next END.
- Create timestamp (`19970602132525` = 1997-06-02 13:25:25), create user (`CCC00419`)
- Last-change timestamp, last-change user
- `G0` — DEVCLASS or similar
- `200` — client or release code

**This matters for editing:** the `00000C5000334`-style number is a length token. If you add or remove bytes between HEAD and END, re-import may reject the block. Same-byte-count edits are safe; line insertions/deletions are NOT.

## Common ITF tags (TDFORMAT values, classic dialect)

| Tag | Meaning |
|-----|---------|
| `/:` | Control statement (`/:INCLUDE`, `/:IF`, `/:ENDIF`, `/:ELSE`, `/:PROTECT`, `/:ENDPROTECT`, `/:DEFINE`, `/:NEW-PAGE`, `/:NEW-WINDOW`, `/:ADDRESS`/`/:ENDADDRESS`, `/:TOP`/`/:ENDTOP`, `/:BOTTOM`/`/:ENDBOTTOM`) |
| `/*` | Comment (not printed) |
| `/E` | Text element marker — `/E <ELEMENT_NAME>` splits elements inside a window |
| `/W` | Window marker (in dialect B contexts) — `/W <WINDOW_NAME>` |
| `/ ` | Line break without paragraph change |
| `= ` | Continuation of the previous line (when wrapped at 132 chars) |
| `* ` | Default paragraph (whatever the form's default paragraph format is) |
| `P1`/`P2`/... | Numbered paragraph format — must exist in the form's style |
| Any 2-letter code matching a paragraph format name (e.g. `L `, `R `, `CN`, `IT`, `VS`, `VT`) | That named paragraph format |
| `C1`/`C2`/... or named char format | Inline character format (rarely appears as TDFORMAT; usually embedded as `<B>...</>` strings) |

## Inline character-format markup (inside TDLINE)

Character formats appear as XML-like tags **inside the line content**, not as TDFORMAT tags:

```
<B>Bold text</>
<UB>Underlined and bold</>
<C1>Char format 1 text</>
```

The `</>` ends whatever the most recent opening tag was. These are defined under the form's style (SE72) — `B`, `UB`, `BC` in J_2GLP_D.FOR.

## Field symbols

Syntax: `&FIELD&` or `&STRUCT-FIELD&` or `&FIELD(format_options)&`.

Format options observed:
- `&FIELD(10)&` — truncate/pad to 10 chars
- `&FIELD(I11)&` — initialize with 11 chars, right-align (numeric)
- `&FIELD(I8.3)&` — 8 chars total, 3 decimals
- `&FIELD(C)&` — convert leading zeros (compress)
- `&FIELD(Z)&` — suppress leading zeros
- `&'prefix: 'FIELD&` — prepend literal "prefix: " if field non-empty

**Don't reformat these.** Stripping parens, spaces inside `&...&`, or the `'...'` literals breaks the symbol.

## Encoding

- File encoding: **UTF-8** in modern Unicode systems (observed in J_2GLP_D.FOR with Greek content: `Στοιχεία Εταιρίας`).
- Line endings: CRLF on Windows exports, LF on Unix — both tolerated by RSTXSCRP import as long as they're consistent.
- No BOM.

## Editing rules (safe round-trip)

When Claude edits an exported ITF file:

1. **Preserve the record tag structure.**
   - Dialect A: 2-char tag in columns 1–2, never stripped, never padded.
   - Dialect B: ` LINE` / ` HEAD` / ` END` / `SFORM` / `HFORM` / ` OLANG` prefixes intact.
2. **Don't change byte count of HEAD-framed blocks in dialect B.** The HEAD record contains a length/checksum token (the `000334`-style number). Adding or removing bytes between `HEAD` and `END` may fail re-import. Prefer same-length string swaps. If you must insert/delete lines, recalculating the checksum is TBD — revert and ask the user to re-export.
3. **Don't invent new paragraph or character format codes.** `P1`/`C1`/`L`/`IT` must already exist in the form's style. Changing `P1` → `P5` fails silently if `P5` isn't defined.
4. **Keep `FORM HEADER`/`SFORM`/`HFORM` records intact.** Don't delete, reorder, or rename them — re-import reads them to find the target form.
5. **Preserve field symbols exactly:** `&FIELD&`, `&FIELD(N)&`, `&'lit: 'FIELD&`. Don't "tidy" ampersands, parens, or quoted literals.
6. **Comma gotcha:** `,,` is a tab marker in SAPscript. To print a literal double comma use `<(>,<)>`. (See wiki: `E:\my-wiki\raw\sapscript-formatting.md` §"Tab Marker".)
7. **Back up before edit:** always copy `<form>.FOR` → `<form>.FOR.bak` first so the user can diff or restore.
8. **Show before/after of affected lines only** — not a full-file diff — before applying.

## Same-length edit technique

For dialect B files the safest edit preserves exact byte count:

```
Original:  LINE/:PARAGRAPH CN TEXT 'Centered';
Edited:    LINE/:PARAGRAPH CN TEXT 'Centerer';
                                    ^^^^^^^^
                                    both 8 bytes — safe
```

To change semantic meaning without byte-count change, use paddings like adding a trailing space inside a string literal (rare — mostly for tests).

For real edits that change byte count, the current recommendation is: re-export after edit attempt; if import fails, the HEAD checksum was the culprit.

## Sub-objects in a typical FORM export (dialect B)

Order observed in `J_2GLP_D.FOR`:

1. `SFORM<name>` — start marker
2. `HFORM<name>` — header marker
3. ` OLANG` — original language
4. **` HEAD...DEF G`** + body — form definition in original language (Greek here): `/:FORM`, `/:PARAGRAPH`, `/:STRING`, `/:WINDOW`, `/:PAGE`, `/:PAGE WINDOW` control lines
5. ` END`
6. **` HEADFORM...TXT E`** + body — description/translation of the above in English (`/:FORM TEXT '...'`, `/:PARAGRAPH CN TEXT 'Centered'`, etc.)
7. ` END`
8. **` HEAD...`** + body — window contents (one sub-object per window + per language)
9. ` END`
10. ...repeat for each window/page/element...

The last ` END` before EOF closes the outer `SFORM`.

## RSTXSCRP parameters

Running `RSTXSCRP` (SE38):

| Param | Meaning | Typical |
|-------|---------|---------|
| MODE | `EXPORT` / `IMPORT` / `COMP` (compare) | |
| OBJECT | `FORM` / `STYLE` / `TEXT` / `DOKU` | Usually `FORM` |
| OBJNAME | Object name, e.g. `Z_FORM_NAME` | Single object at a time |
| OBJLANG | Language key (1 char internal, e.g. `E`, `G` for Greek, `8` for Ukrainian) | Original language |
| DATASET | Local file path | `C:\temp\Z_FORM.FOR` or `/tmp/form.itf` on Unix |
| FSECURE | `L` for local file, `X` for server file | `L` |

Export creates the file. Import reads it and writes back to STXH/STXL. Import on an existing form that's locked by a transport requires the user to have the transport open.

## Known limitations

- No way to bypass RSTXSCRP via RFC (confirmed: `sap-rfc` plugin tools don't cover SAPscript).
- Form style definitions are in a separate object (SE72) — `RSTXSCRP` on a FORM doesn't include the style. If the style has changed between export and import, paragraph codes may break.
- Pretty-printed outputs (RTF, ASCII via `RSTXSRTF` / `RSTXASCN`) are one-way — they can't round-trip back. Only ITF round-trips cleanly.
- The `00000C5000334`-style checksum token inside HEAD records hasn't been reverse-engineered fully. Until it is, prefer same-length edits.

## Read path in sap-rfc plugin

`rfc-mcp`'s `read_form` tool parses dialect-B `.FOR` files offline (no RFC round-trip — `READ_FORM` is not RFC-enabled). It produces a text outline and an optional first-page wireframe PNG. Live reads (via a Z-wrapper FM) and the write path are not yet implemented.

Notable parser quirks verified against `J_2GLP_D.FOR`:
- `/:PAGE MAIN` lines follow the shape `<x_bare> <skip_pair> <y_val> <y_unit> <w_val> <w_unit> <h_val> <h_unit>`. The second pair (e.g. `1 CH`) is an internal SAP field (default paragraph spacing), not a coordinate — the parser skips it.
- `/W` and `/E` names are glued to the TDFORMAT marker with no separator.
- The file trailer is ` ACTV<origin><lang>` (one leading space), not `ACTV...`.

## References

- `E:\my-wiki\raw\sapscript-formatting.md` — paragraph formats, tabs, alignment, field-width (complementary reference for form design, not file format)
- SAP Help: ITF Export and ITF Import — https://help.sap.com/saphelp_snc70/helpdata/EN/f4/b4a15e453611d189710000e8322d00/content.htm
- SAP Note 26526 — Conversion of SAPscript texts (legacy but still the canonical reference for round-trip behavior)

## Captured example

A full dialect-B export of the SAP-standard Greek delivery note form (456 lines, UTF-8, 19371 bytes) is committed as a fixture at `plugins/sap-rfc/servers/rfc-mcp/tests/fixtures/sapscript/J_2GLP_DASD.FOR`. When testing changes to this reference, use a Z-copy of the form on the SAP side — never edit the original SAP object.
