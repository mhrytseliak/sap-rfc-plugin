"""SAPscript ITF reader — parses RSTXSCRP dialect-B .FOR exports."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class HeadMeta:
    object_kind: str            # 'FORM' | 'STYL' | 'TEXT' | 'DOKU'
    object_name: str
    block_kind: str             # 'DEF' | 'TXT'
    language: str               # 1-char SAP langu
    raw: str                    # full HEAD line verbatim


@dataclass
class ItfLine:
    tdformat: str               # 2 chars from cols 6-7
    content: str                # cols 8.. of the LINE record


@dataclass
class Block:
    meta: HeadMeta
    lines: list[ItfLine] = field(default_factory=list)


@dataclass
class ParagraphFormat:
    name: str
    alignment: str | None = None
    line_space: str | None = None
    font: str | None = None
    font_size: int | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    tabs: list[tuple[int, str, str]] = field(default_factory=list)  # (pos, unit, align)
    description: dict[str, str] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class CharFormat:
    name: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    barcode: str | None = None
    description: dict[str, str] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class WindowDef:
    name: str
    type: str = "VAR"           # 'CONST' | 'VAR' | 'MAIN'
    description: dict[str, str] = field(default_factory=dict)


@dataclass
class PageWindowPos:
    page: str
    window: str
    x_cm: float
    y_cm: float
    width_cm: float
    height_cm: float
    raw: str = ""               # original /:PAGE ... WINDOW line for debugging


@dataclass
class PageDef:
    name: str
    next_page: str | None = None
    counter_mode: str | None = None
    main_window: tuple[float, float, float, float] | None = None
    description: dict[str, str] = field(default_factory=dict)


@dataclass
class ElementBody:
    window: str
    name: str                   # '' for lines before a /E in a window
    language: str
    lines: list[ItfLine] = field(default_factory=list)


@dataclass
class FormAST:
    form_name: str
    original_language: str
    sform_line: str = ""
    hform_line: str = ""
    olang_line: str = ""
    def_block: Block | None = None
    txt_blocks: list[Block] = field(default_factory=list)
    paragraphs: dict[str, ParagraphFormat] = field(default_factory=dict)
    char_formats: dict[str, CharFormat] = field(default_factory=dict)
    windows: dict[str, WindowDef] = field(default_factory=dict)
    pages: dict[str, PageDef] = field(default_factory=dict)
    page_windows: list[PageWindowPos] = field(default_factory=list)
    elements: list[ElementBody] = field(default_factory=list)
    trailer: str = ""
    form_settings: dict[str, str] = field(default_factory=dict)  # from /:FORM
    cpi: float = 10.0
    lpi: float = 6.0
    page_format: str = "DINA4"
    orientation: str = "PORTRAIT"


class ITFParseError(Exception):
    pass


_FORM_NAME_RE = re.compile(r"^[A-Z0-9_/]{1,30}$")


class UnsupportedDialect(Exception):
    pass


# Record tags are matched on their first 5 bytes. SFORM/HFORM/ACTV have no
# leading space; LINE/HEAD/END/OLANG have one.
_RECORD_TAGS = {
    "SFORM": "SFORM",
    "HFORM": "HFORM",
    " HEAD": "HEAD",
    " LINE": "LINE",
}


def _classify_record(line: str) -> tuple[str, str]:
    """Return (kind, body) where body is the portion after the record tag.

    Raises ITFParseError for unrecognised lines.
    """
    line = line.rstrip("\r")
    if line.startswith("ACTV") or line.startswith(" ACTV"):
        off = 4 if line.startswith("ACTV") else 5
        return "ACTV", line[off:]
    if line.startswith(" OLANG"):
        return "OLANG", line[6:]
    if line.startswith(" END"):
        return "END", line[4:].lstrip()
    prefix = line[:5]
    if prefix in _RECORD_TAGS:
        return _RECORD_TAGS[prefix], line[5:]
    raise ITFParseError(f"unrecognised record: {line[:20]!r}")


def _parse_head(line: str) -> HeadMeta:
    """Parse a ` HEAD<meta>` line into HeadMeta."""
    _, body = _classify_record(line)
    idx_def = body.find(" DEF ")
    idx_txt = body.find(" TXT ")
    if idx_def >= 0:
        block_kind = "DEF"
        lang_pos = idx_def + len(" DEF ")
    elif idx_txt >= 0:
        block_kind = "TXT"
        lang_pos = idx_txt + len(" TXT ")
    else:
        raise ITFParseError(f"HEAD missing DEF/TXT marker: {line[:80]!r}")
    language = body[lang_pos:lang_pos + 1]

    object_kind = body[:4].strip()
    rest = body[4:].lstrip()
    object_name = rest.split()[0] if rest.split() else ""
    return HeadMeta(
        object_kind=object_kind,
        object_name=object_name,
        block_kind=block_kind,
        language=language,
        raw=line,
    )


_TAB_RE = re.compile(
    r"\bTAB\s+(\d+)\s+(\d+(?:\.\d+)?)\s*(CH|CM|MM|IN|TW|PT|LN)\s+(LEFT|RIGHT|CENTER)",
    re.IGNORECASE,
)


def _parse_form_settings(ast: FormAST, content: str) -> None:
    """Extract CPI, LPI, FORMAT, orientation, START-PAGE from /:FORM body."""
    tokens = [t.strip(";") for t in content.split()]
    i = 0
    while i < len(tokens):
        tok = tokens[i].upper()
        if tok == "FORM":
            i += 1
            continue
        if tok == "CPI" and i + 1 < len(tokens):
            try:
                ast.cpi = float(tokens[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if tok == "LPI" and i + 1 < len(tokens):
            try:
                ast.lpi = float(tokens[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if tok == "FORMAT" and i + 1 < len(tokens):
            ast.page_format = tokens[i + 1].upper()
            if i + 2 < len(tokens) and tokens[i + 2].upper() in ("LANDSCAPE", "PORTRAIT"):
                ast.orientation = tokens[i + 2].upper()
                i += 3
            else:
                i += 2
            continue
        if tok == "START-PAGE" and i + 1 < len(tokens):
            ast.form_settings["START-PAGE"] = tokens[i + 1].upper()
            i += 2
            continue
        if tok == "FONT-SIZE" and i + 1 < len(tokens):
            try:
                ast.form_settings["FONT-SIZE"] = str(int(tokens[i + 1]))
            except ValueError:
                pass
            i += 2
            continue
        if tok == "PARAGRAPH" and i + 1 < len(tokens):
            ast.form_settings["DEFAULT-PARAGRAPH"] = tokens[i + 1].upper()
            i += 2
            continue
        i += 1


def _upsert_paragraph(ast: FormAST, name: str) -> ParagraphFormat:
    pf = ast.paragraphs.get(name)
    if pf is None:
        pf = ParagraphFormat(name=name)
        ast.paragraphs[name] = pf
    return pf


def _apply_paragraph_line(ast: FormAST, content: str) -> None:
    tokens = content.split()
    if len(tokens) < 2:
        return
    name = tokens[1].upper().rstrip(";")
    pf = _upsert_paragraph(ast, name)
    pf.raw_lines.append(content)

    for m in _TAB_RE.finditer(content):
        _pos_idx, pos_val, unit, align = m.groups()
        try:
            pf.tabs.append((int(float(pos_val)), unit.upper(), align.upper()))
        except ValueError:
            pass

    upper = content.upper()
    if " ALIGN CENTER" in upper:
        pf.alignment = "CENTER"
    elif " ALIGN RIGHT" in upper:
        pf.alignment = "RIGHT"
    elif " ALIGN LEFT" in upper:
        pf.alignment = "LEFT"

    m = re.search(r"LINE-SPACE\s+(\d+(?:\.\d+)?\s*LN)", upper)
    if m:
        pf.line_space = m.group(1)

    m = re.search(r"\bFONT\s+([A-Z][A-Z0-9_]*)", upper)
    if m:
        pf.font = m.group(1)
    m = re.search(r"FONT-SIZE\s+(\d+)", upper)
    if m:
        pf.font_size = int(m.group(1))

    if " BOLD ON" in upper:
        pf.bold = True
    elif " BOLD OFF" in upper:
        pf.bold = False
    if " ITALIC ON" in upper:
        pf.italic = True
    elif " ITALIC OFF" in upper:
        pf.italic = False
    if " ULINE ON" in upper:
        pf.underline = True
    elif " ULINE OFF" in upper:
        pf.underline = False


def _apply_string_line(ast: FormAST, content: str) -> None:
    tokens = content.split()
    if len(tokens) < 2:
        return
    name = tokens[1].upper().rstrip(";")
    cf = ast.char_formats.get(name)
    if cf is None:
        cf = CharFormat(name=name)
        ast.char_formats[name] = cf
    cf.raw_lines.append(content)
    upper = content.upper()
    if " BOLD ON" in upper:
        cf.bold = True
    elif " BOLD OFF" in upper:
        cf.bold = False
    if " ULINE ON" in upper:
        cf.underline = True
    elif " ULINE OFF" in upper:
        cf.underline = False
    if " ITALIC ON" in upper:
        cf.italic = True
    elif " ITALIC OFF" in upper:
        cf.italic = False
    m = re.search(r"\bBARCODE\s+([A-Z0-9_]+)", upper)
    if m:
        cf.barcode = m.group(1)


def _apply_window_line(ast: FormAST, content: str) -> None:
    tokens = content.split()
    if len(tokens) < 2:
        return
    name = tokens[1].upper().rstrip(";")
    wd = ast.windows.get(name)
    if wd is None:
        wd = WindowDef(name=name)
        ast.windows[name] = wd
    if name == "MAIN" and "TYPE" not in content.upper():
        wd.type = "MAIN"
        return
    m = re.search(r"\bTYPE\s+(VAR|CONST|MAIN)\b", content, re.IGNORECASE)
    if m:
        wd.type = m.group(1).upper()


def _units_to_cm(value: float, unit: str, cpi: float, lpi: float) -> float:
    u = unit.upper()
    if u == "CM":
        return float(value)
    if u == "MM":
        return float(value) / 10.0
    if u == "IN":
        return float(value) * 2.54
    if u == "PT":
        return float(value) * 2.54 / 72.0
    if u == "TW":
        return float(value) * 2.54 / 1440.0
    if u == "CH":
        return float(value) * 2.54 / (cpi if cpi > 0 else 10.0)
    if u == "LN":
        return float(value) * 2.54 / (lpi if lpi > 0 else 6.0)
    return float(value)


_NUM_UNIT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(CH|CM|MM|IN|TW|PT|LN)",
    re.IGNORECASE,
)


def _extract_xywh(tail: str, cpi: float, lpi: float) -> tuple[float, float, float, float] | None:
    pairs = _NUM_UNIT_RE.findall(tail)
    if len(pairs) < 4:
        return None
    vals = [_units_to_cm(float(v), u, cpi, lpi) for v, u in pairs[:4]]
    return (vals[0], vals[1], vals[2], vals[3])


def _apply_page_line(ast: FormAST, content: str) -> None:
    """Handle /:PAGE <p> ... variants."""
    tokens = content.split()
    if len(tokens) < 2:
        return
    page = tokens[1].upper().rstrip(";")
    pd = ast.pages.get(page)
    if pd is None:
        pd = PageDef(name=page)
        ast.pages[page] = pd

    if len(tokens) >= 3 and tokens[2].upper() == "WINDOW":
        if len(tokens) < 4:
            return
        window = tokens[3].upper().rstrip(";")
        tail = " ".join(tokens[4:])
        xywh = _extract_xywh(tail, ast.cpi, ast.lpi)
        if xywh is None:
            return
        ast.page_windows.append(PageWindowPos(
            page=page, window=window,
            x_cm=xywh[0], y_cm=xywh[1],
            width_cm=xywh[2], height_cm=xywh[3],
            raw=content,
        ))
        return

    if len(tokens) >= 3 and tokens[2].upper() == "MAIN":
        # /:PAGE <p> MAIN <x> <skip_pair> <y> <uy> <w> <uw> <h> <uh>
        # First token is a bare number (usually 0) representing LEFT margin.
        # Following `1 CH` is an internal field (paragraph spacing default).
        # The four positional (y, w, h) pairs come after it.
        mtokens = tokens[3:]
        if not mtokens:
            return
        try:
            x_val = float(mtokens[0])
        except ValueError:
            return
        rest = " ".join(mtokens[1:])
        pairs = _NUM_UNIT_RE.findall(rest)
        if len(pairs) < 4:
            return
        # pairs[0] is the skip pair (e.g. "1 CH"); positional values are [1..3].
        y = _units_to_cm(float(pairs[1][0]), pairs[1][1], ast.cpi, ast.lpi)
        w = _units_to_cm(float(pairs[2][0]), pairs[2][1], ast.cpi, ast.lpi)
        h = _units_to_cm(float(pairs[3][0]), pairs[3][1], ast.cpi, ast.lpi)
        pd.main_window = (x_val, y, w, h)
        return

    # /:PAGE <name> <next> [<mode>]
    if len(tokens) >= 3:
        pd.next_page = tokens[2].upper().rstrip(";")
    if len(tokens) >= 4:
        pd.counter_mode = tokens[3].upper().rstrip(";")


def _semantic_pass_def(ast: FormAST) -> None:
    if ast.def_block is None:
        return
    for line in ast.def_block.lines:
        if line.tdformat != "/:":
            continue
        content = line.content.strip()
        head = content.split(None, 1)[0].upper() if content else ""
        if head == "FORM":
            _parse_form_settings(ast, content)
        elif head == "PARAGRAPH":
            _apply_paragraph_line(ast, content)
        elif head == "STRING":
            _apply_string_line(ast, content)
        elif head == "WINDOW":
            _apply_window_line(ast, content)
        elif head == "PAGE":
            _apply_page_line(ast, content)


_SYMBOL_RE = re.compile(r"&[^&\s]+&")


def _extract_symbols(content: str) -> list[str]:
    """Return SAPscript &SYMBOL& references from `content`, deduplicated,
    in order of first appearance. Matches any non-whitespace run between two
    `&` characters, so format suffixes like &F-VAL(C)&, &F+5(10)&,
    &F.DATE()& are preserved verbatim.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _SYMBOL_RE.finditer(content):
        sym = m.group(0)
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


ELEMENT_BODY_LINE_CAP = 200


_TEXT_LITERAL_RE = re.compile(r"TEXT\s+'([^']*)'")


def _extract_text_literal(content: str) -> str | None:
    m = _TEXT_LITERAL_RE.search(content)
    return m.group(1) if m else None


def _apply_txt_description_line(ast: FormAST, content: str, language: str) -> None:
    tokens = content.split()
    if len(tokens) < 2:
        return
    head = tokens[0].upper()
    if head == "FORM":
        text = _extract_text_literal(content)
        if text is not None:
            ast.form_settings.setdefault(f"DESC_{language}", text)
        return
    if len(tokens) < 3:
        return
    name = tokens[1].upper().rstrip(";")
    text = _extract_text_literal(content)
    if text is None:
        return
    if head == "PARAGRAPH":
        pf = ast.paragraphs.get(name)
        if pf is None:
            pf = ParagraphFormat(name=name)
            ast.paragraphs[name] = pf
        pf.description[language] = text
    elif head == "STRING":
        cf = ast.char_formats.get(name)
        if cf is None:
            cf = CharFormat(name=name)
            ast.char_formats[name] = cf
        cf.description[language] = text
    elif head == "WINDOW":
        wd = ast.windows.get(name)
        if wd is None:
            wd = WindowDef(name=name)
            ast.windows[name] = wd
        wd.description[language] = text
    elif head == "PAGE":
        pd = ast.pages.get(name)
        if pd is None:
            pd = PageDef(name=name)
            ast.pages[name] = pd
        pd.description[language] = text


def _semantic_pass_txt(ast: FormAST) -> None:
    for block in ast.txt_blocks:
        language = block.meta.language
        current_window = ""
        current_body: ElementBody | None = None

        def flush() -> None:
            nonlocal current_body
            if current_body is not None and current_body.lines:
                ast.elements.append(current_body)
            current_body = None

        for line in block.lines:
            tf = line.tdformat
            content = line.content

            if tf == "/:" and current_window == "":
                head = content.strip().split(None, 1)[0].upper() if content.strip() else ""
                if head in ("FORM", "PARAGRAPH", "STRING", "WINDOW", "PAGE"):
                    _apply_txt_description_line(ast, content.strip(), language)
                    continue

            if tf == "/W":
                flush()
                current_window = content.strip().upper()
                current_body = ElementBody(
                    window=current_window, name="", language=language,
                )
                continue

            if tf == "/E":
                flush()
                current_element = content.strip().upper()
                current_body = ElementBody(
                    window=current_window, name=current_element, language=language,
                )
                continue

            if current_body is not None:
                current_body.lines.append(line)

        flush()


def _prefer_description(descs: dict[str, str], prefer_language: str, orig: str) -> str:
    if prefer_language in descs and descs[prefer_language]:
        return descs[prefer_language]
    if orig and orig in descs and descs[orig]:
        return descs[orig]
    for v in descs.values():
        if v:
            return v
    return ""


def _format_tabs(tabs: list[tuple[int, str, str]]) -> str:
    return ", ".join(f"{pos}{unit} {align}" for pos, unit, align in tabs)


def write_outline(ast: FormAST, path: str, prefer_language: str = "E") -> None:
    """Render FormAST to a human-readable text outline and save to `path`."""
    from pathlib import Path

    lines: list[str] = []
    form_desc = ast.form_settings.get(f"DESC_{prefer_language}") \
        or ast.form_settings.get(f"DESC_{ast.original_language}", "")
    lines.append(
        f"FORM {ast.form_name}   "
        f"(original language: {ast.original_language or '?'}; "
        f"page format: {ast.page_format} {ast.orientation}; "
        f"CPI={ast.cpi:g} LPI={ast.lpi:g})"
    )
    if form_desc:
        lines.append(f"  Description: {form_desc}")
    lines.append("")

    lines.append("PAGES")
    for name, pd in ast.pages.items():
        chunk = f"  {name:<6}"
        if pd.next_page:
            chunk += f" -> {pd.next_page:<6}"
        if pd.counter_mode:
            chunk += f"  mode={pd.counter_mode}"
        if pd.main_window:
            x, y, w, h = pd.main_window
            chunk += f"  main=(x={x:.2f}cm y={y:.2f}cm w={w:.2f}cm h={h:.2f}cm)"
        desc = _prefer_description(pd.description, prefer_language, ast.original_language)
        if desc:
            chunk += f'  "{desc}"'
        lines.append(chunk)
    lines.append("")

    lines.append("PARAGRAPH FORMATS")
    for name, pf in ast.paragraphs.items():
        desc = _prefer_description(pf.description, prefer_language, ast.original_language)
        bits: list[str] = []
        if pf.alignment:
            bits.append(f"align={pf.alignment}")
        if pf.line_space:
            bits.append(f"line-space={pf.line_space}")
        if pf.font:
            bits.append(f"font={pf.font}")
        if pf.font_size:
            bits.append(f"size={pf.font_size}pt")
        if pf.bold is not None:
            bits.append(f"bold={'on' if pf.bold else 'off'}")
        if pf.italic is not None:
            bits.append(f"italic={'on' if pf.italic else 'off'}")
        if pf.underline is not None:
            bits.append(f"uline={'on' if pf.underline else 'off'}")
        if pf.tabs:
            bits.append(f"tabs=[{_format_tabs(pf.tabs)}]")
        attrs = "  ".join(bits)
        label = f"{name:<4}{(desc or '(no description)').ljust(30)}"
        lines.append(f"  {label}{attrs}")
    lines.append("")

    lines.append("CHARACTER FORMATS")
    for name, cf in ast.char_formats.items():
        desc = _prefer_description(cf.description, prefer_language, ast.original_language)
        bits: list[str] = []
        if cf.bold is not None:
            bits.append(f"bold={'on' if cf.bold else 'off'}")
        if cf.italic is not None:
            bits.append(f"italic={'on' if cf.italic else 'off'}")
        if cf.underline is not None:
            bits.append(f"uline={'on' if cf.underline else 'off'}")
        if cf.barcode:
            bits.append(f"barcode={cf.barcode}")
        attrs = "  ".join(bits)
        label = f"{name:<4}{(desc or '(no description)').ljust(30)}"
        lines.append(f"  {label}{attrs}")
    lines.append("")

    preferred_page = "FIRST" if "FIRST" in ast.pages else (next(iter(ast.pages), ""))
    lines.append(f"WINDOWS (placements on page {preferred_page or '?'})")
    by_window = {p.window: p for p in ast.page_windows if p.page == preferred_page}
    for name, wd in ast.windows.items():
        desc = _prefer_description(wd.description, prefer_language, ast.original_language)
        pos = by_window.get(name)
        if wd.type == "MAIN":
            pd = ast.pages.get(preferred_page)
            if pd and pd.main_window:
                x, y, w, h = pd.main_window
                pos_s = f"x={x:6.2f}cm y={y:6.2f}cm w={w:6.2f}cm h={h:6.2f}cm"
            else:
                pos_s = "(no MAIN placement on this page)"
        elif pos:
            pos_s = (
                f"x={pos.x_cm:6.2f}cm y={pos.y_cm:6.2f}cm "
                f"w={pos.width_cm:6.2f}cm h={pos.height_cm:6.2f}cm"
            )
        else:
            pos_s = "(no placement on this page)"
        lines.append(f"  {name:<9} [{wd.type:<5}] {pos_s}  {desc}")
    lines.append("")

    langs_present = {e.language for e in ast.elements}
    use_lang = prefer_language if prefer_language in langs_present else (
        ast.original_language if ast.original_language in langs_present else next(iter(langs_present), "")
    )
    if use_lang == prefer_language:
        lines.append(f"ELEMENTS (language {prefer_language})")
    elif use_lang:
        lines.append(f"ELEMENTS (language {use_lang} — {prefer_language} not found)")
    else:
        lines.append("ELEMENTS (none)")
    by_win: dict[str, list[ElementBody]] = {}
    for e in ast.elements:
        if e.language != use_lang:
            continue
        by_win.setdefault(e.window or "(no window)", []).append(e)
    for win, items in by_win.items():
        lines.append(f"  {win}")
        for e in items:
            tag = e.name or "(lines before /E)"
            header_bits: list[str] = []
            # First non-control line whose tdformat isn't blank gives the
            # default paragraph for the element.
            para_tag: str | None = None
            for itf in e.lines:
                tf_stripped = itf.tdformat.strip()
                if tf_stripped and tf_stripped in ast.paragraphs:
                    para_tag = tf_stripped
                    break
            if para_tag:
                header_bits.append(f"paragraph={para_tag}")
            header_extra = ("  " + "  ".join(header_bits)) if header_bits else ""
            lines.append(f"    {tag:<20}{header_extra}")

            body = e.lines[:ELEMENT_BODY_LINE_CAP]
            truncated = len(e.lines) - len(body)
            all_symbols: list[str] = []
            symbol_seen: set[str] = set()
            for itf in body:
                tf = (itf.tdformat + "  ")[:2]
                content_line = itf.content.rstrip()
                lines.append(f"      {tf}  {content_line}")
                for sym in _extract_symbols(itf.content):
                    if sym not in symbol_seen:
                        symbol_seen.add(sym)
                        all_symbols.append(sym)
            # Include symbols from truncated tail too — we don't want a low
            # cap to hide references.
            for itf in e.lines[ELEMENT_BODY_LINE_CAP:]:
                for sym in _extract_symbols(itf.content):
                    if sym not in symbol_seen:
                        symbol_seen.add(sym)
                        all_symbols.append(sym)

            if truncated > 0:
                lines.append(
                    f"      … ({truncated} more lines — see {ast.form_name}.FOR)"
                )
            if all_symbols:
                lines.append(f"      fields: {', '.join(all_symbols)}")
    lines.append("")

    Path(path).write_text("\n".join(lines), encoding="utf-8")


_PAGE_SIZES_CM = {
    "DINA4":     (21.0, 29.7),
    "LETTER":    (21.59, 27.94),
    "DINA3":     (29.7, 42.0),
    "DINA5":     (14.8, 21.0),
    "EXECUTIVE": (18.41, 26.67),
    "LEGAL":     (21.59, 35.56),
}


def _page_dimensions_cm(ast: FormAST) -> tuple[float, float]:
    base = _PAGE_SIZES_CM.get(ast.page_format.upper(), (21.0, 29.7))
    w, h = base
    if ast.orientation == "LANDSCAPE":
        w, h = h, w
    return w, h


def _import_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except Exception:
        return None


def _window_fill(type_: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int]]:
    if type_ == "MAIN":
        return (173, 216, 230, 180), (40, 80, 120)
    if type_ == "CONST":
        return (220, 220, 220, 200), (80, 80, 80)
    return (255, 255, 255, 0), (120, 120, 120)


def render_wireframe(
    ast: FormAST,
    page: str,
    path: str,
    prefer_language: str = "E",
) -> bool:
    """Render a wireframe of the given page to PNG. Returns True on success."""
    mods = _import_pillow()
    if mods is None:
        return False
    Image, ImageDraw, ImageFont = mods

    try:
        page_w_cm, page_h_cm = _page_dimensions_cm(ast)
        target_long_cm = max(page_w_cm, page_h_cm)
        scale = 1600.0 / target_long_cm
        margin_px = int(1.0 * scale)
        img_w = int(page_w_cm * scale) + 2 * margin_px
        img_h = int(page_h_cm * scale) + 2 * margin_px + int(1.5 * scale)

        img = Image.new("RGB", (img_w, img_h), (245, 245, 245))
        draw = ImageDraw.Draw(img, "RGBA")

        def _font(name: str, size: int):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                return ImageFont.load_default()

        font_title = _font("DejaVuSans-Bold.ttf", 22)
        font_label = _font("DejaVuSans.ttf", 14)
        font_small = _font("DejaVuSans.ttf", 11)

        title = (
            f"FORM {ast.form_name} — page {page} — "
            f"{ast.page_format} {ast.orientation} "
            f"({page_w_cm:.1f} x {page_h_cm:.1f} cm)"
        )
        draw.text((margin_px, int(0.25 * scale)), title, fill=(20, 20, 20), font=font_title)

        page_x0 = margin_px
        page_y0 = margin_px + int(1.5 * scale)
        page_x1 = page_x0 + int(page_w_cm * scale)
        page_y1 = page_y0 + int(page_h_cm * scale)
        draw.rectangle(
            [page_x0, page_y0, page_x1, page_y1],
            fill=(255, 255, 255), outline=(40, 40, 40), width=2,
        )

        # MAIN placement (stored on PageDef)
        positions: list[tuple[str, str, float, float, float, float]] = []
        pd = ast.pages.get(page)
        if pd and pd.main_window:
            x, y, w, h = pd.main_window
            positions.append(("MAIN", "MAIN", x, y, w, h))

        for p in ast.page_windows:
            if p.page != page:
                continue
            wd = ast.windows.get(p.window)
            kind = (wd.type if wd else "VAR").upper()
            positions.append((p.window, kind, p.x_cm, p.y_cm, p.width_cm, p.height_cm))

        # Draw larger boxes first so smaller ones land on top.
        positions.sort(key=lambda t: t[4] * t[5], reverse=True)

        elements_by_win: dict[str, list[str]] = {}
        for e in ast.elements:
            if prefer_language and e.language != prefer_language:
                continue
            if e.name:
                elements_by_win.setdefault(e.window, []).append(e.name)

        for name, kind, x_cm, y_cm, w_cm, h_cm in positions:
            fill_rgba, outline = _window_fill(kind)

            wx0 = page_x0 + int(x_cm * scale)
            wy0 = page_y0 + int(y_cm * scale)
            wx1 = wx0 + int(w_cm * scale)
            wy1 = wy0 + int(h_cm * scale)

            draw.rectangle([wx0, wy0, wx1, wy1], fill=fill_rgba, outline=outline, width=1)

            wd = ast.windows.get(name)
            desc = ""
            if wd:
                desc = _prefer_description(wd.description, prefer_language, ast.original_language)
            label1 = f"{name} [{kind}]"
            draw.text((wx0 + 4, wy0 + 3), label1, fill=(0, 0, 0), font=font_label)
            if desc:
                draw.text(
                    (wx0 + 4, wy0 + 3 + int(0.5 * scale)),
                    desc, fill=(40, 40, 40), font=font_small,
                )

            el_names = elements_by_win.get(name, [])
            if el_names:
                el_line = ", ".join(el_names)
                max_chars = max(5, int((wx1 - wx0 - 8) / 6))
                if len(el_line) > max_chars:
                    el_line = el_line[: max_chars - 1] + "…"
                draw.text(
                    (wx0 + 4, wy0 + 3 + int(1.0 * scale)),
                    el_line, fill=(60, 60, 120), font=font_small,
                )

        img.save(path, format="PNG")
        return True
    except Exception:
        return False


def parse_form_file(path: str) -> FormAST:
    """Parse a dialect-B RSTXSCRP export into a FormAST.

    Raises FileNotFoundError, UnsupportedDialect, ITFParseError.
    """
    from pathlib import Path
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    lines = raw.splitlines()

    if not lines:
        raise ITFParseError("empty file")

    first = lines[0].rstrip("\r")
    if not (first.startswith("SFORM") or first.startswith("SSTYL") or first.startswith("SDOKU")):
        raise UnsupportedDialect(
            "dialect A (classic ITF) not supported yet; first line "
            f"{first[:20]!r} is not SFORM/SSTYL/SDOKU"
        )
    if not first.startswith("SFORM"):
        raise UnsupportedDialect(
            f"only SFORM is supported in v1; got {first[:5]!r}"
        )

    form_name = first[5:].strip()
    if not _FORM_NAME_RE.match(form_name):
        raise ITFParseError(
            f"invalid form name {form_name!r} on SFORM line — "
            "must match SAP TDFORM charset [A-Z0-9_/], max 30 chars"
        )

    ast = FormAST(form_name=form_name, original_language="")
    ast.sform_line = first

    current_block: Block | None = None
    idx = 1
    while idx < len(lines):
        line = lines[idx].rstrip("\r")
        idx += 1
        if not line and idx == len(lines):
            break
        try:
            kind, body = _classify_record(line)
        except ITFParseError as e:
            raise ITFParseError(f"line {idx}: {e}") from e

        if kind == "HFORM":
            ast.hform_line = line
        elif kind == "OLANG":
            ast.olang_line = line
            if len(line) > 6:
                ast.original_language = line[6:7]
        elif kind == "HEAD":
            if current_block is not None:
                raise ITFParseError(f"line {idx}: HEAD without preceding END")
            meta = _parse_head(line)
            current_block = Block(meta=meta)
        elif kind == "LINE":
            if current_block is None:
                raise ITFParseError(f"line {idx}: LINE outside HEAD/END block")
            tdformat = (body[:2] + "  ")[:2]
            content = body[2:] if len(body) >= 2 else ""
            current_block.lines.append(ItfLine(tdformat=tdformat, content=content))
        elif kind == "END":
            if current_block is None:
                raise ITFParseError(f"line {idx}: END without HEAD")
            if current_block.meta.block_kind == "DEF":
                if ast.def_block is not None:
                    raise ITFParseError(f"line {idx}: duplicate DEF block")
                ast.def_block = current_block
            else:
                ast.txt_blocks.append(current_block)
            current_block = None
        elif kind == "ACTV":
            ast.trailer = line.lstrip()
            break
        elif kind == "SFORM":
            raise ITFParseError(f"line {idx}: unexpected second SFORM")
        else:
            raise ITFParseError(f"line {idx}: unhandled record kind {kind}")

    if current_block is not None:
        raise ITFParseError("file ended inside a HEAD/END block")

    # Original language: OLANG body if present, else inferred from DEF block.
    if not ast.original_language and ast.def_block is not None:
        ast.original_language = ast.def_block.meta.language

    _semantic_pass_def(ast)
    _semantic_pass_txt(ast)
    return ast


def _read_form_impl(file_path: str, render: bool = True,
                    render_html: bool = True) -> dict:
    """Non-tool entry point; used by tests. Converts exceptions to error dicts."""
    import cache
    from pathlib import Path

    src = Path(file_path)
    if not src.exists():
        return {"error": "FileNotFound", "detail": f"no such file: {file_path}"}
    try:
        ast = parse_form_file(file_path)
    except UnsupportedDialect as e:
        return {"error": "UnsupportedDialect", "detail": str(e)}
    except ITFParseError as e:
        return {"error": "ITFParseError", "detail": str(e)}
    except Exception as e:
        return {"error": type(e).__name__, "detail": str(e)}

    cached_src = cache.cache_copy(src, f"{ast.form_name}.FOR")
    outline_path = cache.cache_dir() / f"{ast.form_name}.outline.txt"
    write_outline(ast, str(outline_path), prefer_language="E")

    wireframe_path: str | None = None
    render_error: str | None = None
    if render:
        wf = cache.cache_dir() / f"{ast.form_name}.wireframe.png"
        ok = render_wireframe(ast, page="FIRST", path=str(wf), prefer_language="E")
        if ok:
            wireframe_path = str(wf)
        else:
            render_error = "Pillow not available or rendering failed"

    preview_path: str | None = None
    preview_error: str | None = None
    if render_html:
        try:
            from tools.sapscript_html import render_html as _render_html
            p = cache.cache_dir() / f"{ast.form_name}.preview.html"
            _render_html(ast, str(p), page="FIRST", prefer_language="E")
            preview_path = str(p)
        except Exception as e:
            preview_error = f"{type(e).__name__}: {e}"

    result = {
        "form_name": ast.form_name,
        "original_language": ast.original_language,
        "page_format": f"{ast.page_format} {ast.orientation}",
        "pages": len(ast.pages),
        "windows": len(ast.windows),
        "elements": len(ast.elements),
        "source_file": cached_src,
        "outline_file": str(outline_path),
        "wireframe_file": wireframe_path,
        "preview_file": preview_path,
    }
    if render_error:
        result["render_error"] = render_error
    if preview_error:
        result["preview_error"] = preview_error
    return result


def register(mcp):
    @mcp.tool()
    def read_form(file_path: str, render: bool = True,
                  render_html: bool = True) -> dict:
        """Parse a SAPscript form exported via RSTXSCRP (dialect-B .FOR file)
        and produce a text outline, an optional wireframe PNG, and an optional
        interactive HTML preview of the first page.

        Args:
            file_path: absolute path to the .FOR file.
            render: produce a wireframe PNG. Default True.
            render_html: produce an interactive HTML preview. Default True.

        Returns: {form_name, original_language, page_format, pages, windows,
                  elements, source_file, outline_file, wireframe_file,
                  preview_file}. On parse failure returns {error, detail}.
        """
        return _read_form_impl(file_path, render, render_html)
