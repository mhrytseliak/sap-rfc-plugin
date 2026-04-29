"""HTML preview renderer for SAPscript forms. Produces a single self-contained
HTML file with inlined CSS + JS. No external assets."""
from __future__ import annotations

import html as _html
import json as _json
import re as _re
from pathlib import Path

from tools.sapscript import FormAST, _page_dimensions_cm


_WINDOW_KIND_CLASS = {
    "MAIN":  "w-main",
    "CONST": "w-const",
    "VAR":   "w-var",
}

_TDFORMAT_CLASS = {
    "/:": "tf-slash-colon",
    "/*": "tf-slash-star",
    "/ ": "tf-slash-blank",
    "/E": "tf-slash-e",
    "/W": "tf-slash-w",
    "= ": "tf-eq",
    "* ": "tf-star",
    "":   "tf-blank",
}


def _tdformat_class(tdformat: str) -> str:
    """Map a 2-char TDFORMAT to a safe CSS class token.

    Known control/continuation codes have dedicated class names. Paragraph
    codes (e.g. 'L ', 'IT', 'CN') are A-Z only and safe to embed directly
    after stripping whitespace. Anything unexpected falls back to tf-unknown.
    """
    if tdformat in _TDFORMAT_CLASS:
        return _TDFORMAT_CLASS[tdformat]
    stripped = tdformat.strip()
    if stripped.isalnum() and stripped.isascii():
        return f"tf-{stripped}"
    return "tf-unknown"


def _esc(s: str) -> str:
    return _html.escape(s, quote=True)


_FIELD_RE = _re.compile(
    r"&(?:'(?P<lit>[^']*)')?(?P<name>[A-Z0-9_\-.~]+)(?P<opts>\([^)]*\))?&",
    _re.IGNORECASE,
)

_CHAR_TAG_RE = _re.compile(r"</?>|<([A-Z][A-Z0-9]*)>", _re.IGNORECASE)


def _render_inline(content: str) -> str:
    """Turn a raw ITF line content into HTML fragment with:
    - `<span class="field">` around &FIELD&, &'lit: 'FIELD&, &FIELD(opts)&
    - `<b class="cf-X">` / `<b><u class="cf-X">` / `<span class="cf-BC">`
      around <B>...</>, <UB>...</>, <BC>...</>
    All other text is HTML-escaped.
    """
    if not content:
        return ""

    # First pass: replace field symbols with sentinels so the char-tag pass
    # below can operate on the rest without confusing `&` characters.
    fields: list[str] = []
    def _field_sub(m: _re.Match) -> str:
        lit = m.group("lit") or ""
        name = m.group("name") or ""
        opts = (m.group("opts") or "").strip()
        pieces = ['<span class="field"']
        raw_symbol = m.group(0)
        pieces.append(f' data-raw="{_esc(raw_symbol)}">')
        if lit:
            pieces.append(f'<span class="field-lit">{_esc(lit)}</span>')
        pieces.append(_esc(name))
        if opts:
            pieces.append(f'<sub class="opts">{_esc(opts)}</sub>')
        pieces.append('</span>')
        fields.append("".join(pieces))
        return f"\x00FIELD{len(fields)-1}\x00"

    stage1 = _FIELD_RE.sub(_field_sub, content)

    # Second pass: tokenise on <TAG> / </>. For everything between an opening
    # <X> and the next </>, wrap in a bold/underline/pill span class="cf-X".
    # Pattern matches either `</>` (SAPscript bare close) or `<TAGNAME>`.
    tokens: list[tuple[str, str]] = []
    pos = 0
    stack: list[str] = []
    for m in _CHAR_TAG_RE.finditer(stage1):
        text = stage1[pos:m.start()]
        if text:
            tokens.append(("text", text))
        pos = m.end()
        tag_name = m.group(1)  # None for `</>`, else the tag name
        is_close = tag_name is None  # `</>` has no capture group
        if is_close:
            if stack:
                opened = stack.pop()
                tokens.append(("close", opened))
            else:
                # stray close with no open — drop silently
                continue
        else:
            tag_name = tag_name.upper()
            stack.append(tag_name)
            tokens.append(("open", tag_name))
    if pos < len(stage1):
        tokens.append(("text", stage1[pos:]))

    # Third pass: assemble HTML. Close any open tags at end (defensive).
    out: list[str] = []
    open_stack: list[str] = []
    for kind, payload in tokens:
        if kind == "text":
            piece = _esc(payload)
            # Restore field sentinels
            for i, f in enumerate(fields):
                piece = piece.replace(f"\x00FIELD{i}\x00", f)
            out.append(piece)
        elif kind == "open":
            cls = f"cf-{_esc(payload)}"
            if payload == "BC":
                out.append(f'<span class="{cls}">')
                open_stack.append("span")
            elif "U" in payload and "B" in payload:
                out.append(f'<b class="{cls}"><u>')
                open_stack.append("b-u")
            elif payload == "B":
                out.append(f'<b class="{cls}">')
                open_stack.append("b")
            elif payload == "U":
                out.append(f'<u class="{cls}">')
                open_stack.append("u")
            elif payload == "I":
                out.append(f'<i class="{cls}">')
                open_stack.append("i")
            else:
                out.append(f'<span class="{cls}">')
                open_stack.append("span")
        elif kind == "close":
            if not open_stack:
                continue
            opened = open_stack.pop()
            if opened == "b-u":
                out.append("</u></b>")
            elif opened == "b":
                out.append("</b>")
            elif opened == "u":
                out.append("</u>")
            elif opened == "i":
                out.append("</i>")
            else:
                out.append("</span>")
    # Defensive close of anything still open.
    while open_stack:
        opened = open_stack.pop()
        out.append({"b-u": "</u></b>", "b": "</b>", "u": "</u>",
                    "i": "</i>", "span": "</span>"}[opened])
    return "".join(out)


def _paragraph_css(ast: FormAST) -> str:
    """Emit CSS rules for each paragraph format, derived from the AST."""
    rules: list[str] = []
    for name, pf in ast.paragraphs.items():
        sel = f".pf-{_esc(name)}"
        props: list[str] = []
        if pf.alignment == "CENTER":
            props.append("text-align: center")
        elif pf.alignment == "RIGHT":
            props.append("text-align: right")
        elif pf.alignment == "LEFT":
            props.append("text-align: left")
        if pf.font:
            # Map SAP fonts to reasonable web fallbacks.
            fm = {
                "TIMES": "'Times New Roman', Times, serif",
                "HELVE": "Arial, 'Helvetica', sans-serif",
                "COURIER": "'Courier New', Consolas, monospace",
                "LETGOTH": "'Letter Gothic', Consolas, monospace",
                "LNPRINT": "'Courier New', Consolas, monospace",
                "ROMAN": "'Times New Roman', Times, serif",
            }.get(pf.font.upper(), "'Times New Roman', serif")
            props.append(f"font-family: {fm}")
        if pf.font_size:
            props.append(f"font-size: {pf.font_size}pt")
        if pf.bold:
            props.append("font-weight: bold")
        elif pf.bold is False:
            props.append("font-weight: normal")
        if pf.italic:
            props.append("font-style: italic")
        elif pf.italic is False:
            props.append("font-style: normal")
        if pf.underline:
            props.append("text-decoration: underline")
        if props:
            rules.append(f"{sel} {{ {'; '.join(props)}; }}")
    return "\n".join(rules)


def _render_head(ast: FormAST, page: str) -> str:
    title = _esc(f"{ast.form_name} — page {page} — preview")
    style = _MINIMAL_CSS + "\n" + _paragraph_css(ast)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        f"<style>{style}</style>\n</head>\n"
    )


_MINIMAL_CSS = """
body { font-family: 'Times New Roman', 'DejaVu Serif', serif; font-size: 10pt; margin: 0; background: #f4f4f4; }
header.topbar { padding: 1em; background: #fff; border-bottom: 1px solid #ccc; }
header.topbar h1 { margin: 0; font-size: 14pt; }
header.topbar .sub { color: #666; font-weight: normal; }
header.topbar .banner { margin: 0.5em 0 0; padding: 0.5em; background: #fff8dc; border: 1px solid #e2c96a; font-size: 10pt; }
main.canvas { position: relative; background: white; border: 1px solid #888; margin: 2cm auto; box-shadow: 0 2px 20px rgba(0,0,0,0.12); }
section.window { position: absolute; box-sizing: border-box; overflow: hidden; }
.w-main { background: rgba(173,216,230,0.25); border: 1px solid #3871a0; }
.w-const { background: rgba(210,210,210,0.45); border: 1px solid #808080; }
.w-var { background: transparent; border: 1px dashed #a0a0a0; }
.window-label { position: absolute; top: 0; left: 0; right: 0; margin: 0; padding: 0.1cm 0.2cm; font-family: Arial, sans-serif; font-size: 8pt; background: rgba(255,255,255,0.8); border-bottom: 1px solid rgba(0,0,0,0.1); }
.window-label .kind { color: #666; font-weight: normal; }
.window-label .desc { color: #333; margin-left: 0.5em; font-weight: normal; }
.window-body { margin-top: 0.7cm; padding: 0.1cm 0.2cm; }
article.element { margin: 0.2cm 0; padding: 0.1cm 0.2cm; background: rgba(255,255,255,0.5); border: 1px solid rgba(0,0,0,0.07); border-radius: 2px; }
article.element > h3.element-label { margin: 0 0 0.1cm; font-family: Arial, sans-serif; font-size: 8pt; color: #555; }
.itf-body { font-family: 'Times New Roman', serif; font-size: 10pt; line-height: 1.2; }
.line { white-space: pre-wrap; }
.line .tf { display: inline-block; width: 2ch; color: #999; font-family: Consolas, monospace; font-size: 8pt; }
.line .content { }
.field { background: #eaf3ff; border: 1px solid #9fc2ea; border-radius: 2px; padding: 0 0.05cm; font-family: Consolas, monospace; font-size: 9pt; color: #234; }
.field .field-lit { color: #666; font-style: italic; margin-right: 0.05em; }
.field sub.opts { font-size: 7pt; color: #567; vertical-align: sub; }
.cf-B { font-weight: bold; }
.cf-UB { font-weight: bold; text-decoration: underline; }
.cf-BC { font-family: monospace; background: #fdf8c6; padding: 0.05cm 0.1cm; border: 1px dashed #b8a64a; border-radius: 2px; }
.line.br { height: 1.2em; }
.line.ctrl { color: #6a7fa0; font-family: Consolas, monospace; font-size: 9pt; }
.line.comment { color: #888; font-style: italic; font-family: Consolas, monospace; font-size: 9pt; }
.line.marker { color: #b06a00; font-family: Consolas, monospace; font-size: 9pt; }
.iff { border-left: 3px solid #9fc2ea; margin: 0.1cm 0; padding-left: 0.2cm; background: rgba(159,194,234,0.04); }
.iff-cond { font-family: Consolas, monospace; font-size: 8pt; color: #3a6099; background: rgba(159,194,234,0.15); padding: 0.05cm 0.15cm; margin: 0 -0.2cm; }
.iff-if { border-top: 1px solid #9fc2ea; }
.iff-elseif, .iff-else { border-top: 1px dashed #9fc2ea; }
.iff-branch { padding: 0.1cm 0; }
.protect { border-right: 3px solid #e2c96a; padding-right: 0.15cm; margin: 0.05cm 0; position: relative; }
.protect .protect-label { position: absolute; right: -2.5em; top: 0; font-size: 7pt; color: #8a7020; transform: rotate(90deg); transform-origin: top right; }
.line.tabbed { display: grid; align-items: baseline; gap: 0 0.1cm; }
.line.tabbed .cell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line.tabbed .cell-right { text-align: right; }
.line.tabbed .cell-center { text-align: center; }
.line.tabbed .cell-left { text-align: left; }
.line.tabbed .tf { grid-column: 1 / -1; }
.line.tabbed .tf + .cell { grid-column: 1 / span 1; }
.incl { border: 1px dashed #a78bb7; background: rgba(167,139,183,0.08); padding: 0.05cm 0.15cm; margin: 0.1cm 0; font-family: Consolas, monospace; font-size: 9pt; color: #6a4585; }
.incl .incl-label { font-weight: bold; margin-right: 0.3em; }
.address { border: 1px dotted #668; background: rgba(102,102,136,0.05); padding: 0.1cm 0.15cm; margin: 0.1cm 0; position: relative; }
.address .addr-label { position: absolute; top: -0.5em; left: 0.3cm; background: #fff; padding: 0 0.15cm; font-size: 7pt; color: #557; font-family: Arial, sans-serif; }
.addr-row { display: flex; gap: 0.3cm; font-size: 9pt; line-height: 1.15; }
.addr-key { color: #668; font-family: Consolas, monospace; font-size: 8pt; min-width: 7em; }
.addr-val { flex: 1; }
footer.legend { display: flex; gap: 1em; padding: 0.5em 1em; background: #fff; border-top: 1px solid #ccc; font-size: 9pt; color: #555; flex-wrap: wrap; }
footer.legend .swatch { display: inline-block; width: 1em; height: 1em; vertical-align: middle; margin-right: 0.3em; border: 1px solid rgba(0,0,0,0.1); }
footer.legend .swatch.k-main { background: rgba(173,216,230,0.5); border-color: #3871a0; }
footer.legend .swatch.k-const { background: rgba(210,210,210,0.7); border-color: #808080; }
footer.legend .swatch.k-var { background: white; border-style: dashed; }
footer.legend .swatch.k-field { background: #eaf3ff; border-color: #9fc2ea; }
footer.legend .swatch.k-iff { background: rgba(159,194,234,0.3); border-left: 3px solid #9fc2ea; }
footer.legend .swatch.k-incl { background: rgba(167,139,183,0.15); border-color: #a78bb7; border-style: dashed; }
main.canvas.grid { background-image:
  linear-gradient(to right, rgba(0,0,0,0.05) 0, rgba(0,0,0,0.05) 1px, transparent 1px, transparent 100%),
  linear-gradient(to bottom, rgba(0,0,0,0.05) 0, rgba(0,0,0,0.05) 1px, transparent 1px, transparent 100%);
  background-size: 1cm 1cm; }
main.canvas.no-borders section.window { border-color: transparent; background: transparent; }
main.canvas.no-borders section.window .window-label { display: none; }
nav.controls { margin-top: 0.5em; font-size: 10pt; }
nav.controls label { margin-right: 1.5em; }
.box { border: 1px solid #666; padding: 0.1cm 0.15cm; margin: 0.1cm 0; min-height: 0.8cm; position: relative; font-family: Consolas, monospace; font-size: 8pt; color: #666; }
.box .box-label { font-weight: bold; margin-right: 0.3em; color: #444; }
.box .box-params { color: #888; }
aside.inspector { position: fixed; right: 0; top: 0; bottom: 0; width: 40vw; max-width: 800px; background: #1e2430; color: #d0d8e4; display: flex; flex-direction: column; box-shadow: -2px 0 12px rgba(0,0,0,0.3); z-index: 100; }
aside.inspector[hidden] { display: none; }
aside.inspector header { display: flex; align-items: center; justify-content: space-between; padding: 0.5em 1em; background: #151a22; border-bottom: 1px solid #2b333f; }
aside.inspector h2 { margin: 0; font-size: 11pt; font-family: Consolas, monospace; }
aside.inspector button { background: transparent; color: inherit; border: 1px solid #444; padding: 0.2em 0.6em; cursor: pointer; font-size: 14pt; }
aside.inspector pre { margin: 0; padding: 0.8em 1em; overflow: auto; flex: 1; font-family: Consolas, monospace; font-size: 10pt; line-height: 1.35; white-space: pre; }
"""


def _render_topbar(ast: FormAST, page: str, w_cm: float, h_cm: float) -> str:
    return (
        "<header class=\"topbar\">\n"
        f"<h1>FORM {_esc(ast.form_name)} "
        f"<span class=\"sub\">— page {_esc(page)} — "
        f"{_esc(ast.page_format)} {_esc(ast.orientation)} — "
        f"{w_cm:.1f} × {h_cm:.1f} cm</span></h1>\n"
        "<p class=\"banner\">Approximate layout. Fonts are proportional; "
        "columns and absolute positions may drift from the printed output. "
        "Use the SAP print preview for pixel-accurate review.</p>\n"
        "<nav class=\"controls\">\n"
        "<label><input type=\"checkbox\" id=\"show-borders\" checked> "
        "Window borders</label>\n"
        "<label><input type=\"checkbox\" id=\"show-grid\"> Grid (1 cm)</label>\n"
        "</nav>\n"
        "</header>\n"
    )


def _render_legend() -> str:
    return (
        '<footer class="legend">\n'
        '<div><span class="swatch k-main"></span> MAIN</div>\n'
        '<div><span class="swatch k-const"></span> CONST (static layout)</div>\n'
        '<div><span class="swatch k-var"></span> VAR (variable-height)</div>\n'
        '<div><span class="swatch k-field"></span> Field symbol</div>\n'
        '<div><span class="swatch k-iff"></span> /:IF branch</div>\n'
        '<div><span class="swatch k-incl"></span> /:INCLUDE stub</div>\n'
        "</footer>\n"
    )


def _collect_raw_payload(ast: FormAST, page: str, prefer_language: str) -> dict:
    """Embed raw ITF lines per window for the inspector panel."""
    placed_windows = {"MAIN"} | {p.window for p in ast.page_windows if p.page == page}
    windows: dict[str, list[dict]] = {w: [] for w in placed_windows}
    for e in ast.elements:
        if e.language != prefer_language:
            continue
        if e.window not in windows:
            continue
        for line in e.lines:
            windows[e.window].append({
                "element": e.name or "(pre)",
                "tdformat": line.tdformat,
                "content": line.content,
            })
    w_cm, h_cm = _page_dimensions_cm(ast)
    return {
        "form_name": ast.form_name,
        "page": page,
        "page_format": f"{ast.page_format} {ast.orientation}",
        "page_size_cm": [w_cm, h_cm],
        "language": prefer_language,
        "windows": windows,
    }


_INSPECTOR_JS = """
(function () {
  var payload;
  try {
    payload = JSON.parse(document.getElementById('raw-windows').textContent);
  } catch (e) { console.error('raw-windows parse failed', e); return; }
  var aside = document.querySelector('aside.inspector');
  var title = document.getElementById('insp-title');
  var body  = document.getElementById('insp-body');
  document.getElementById('insp-close').addEventListener('click', function () {
    aside.hidden = true;
  });
  document.querySelectorAll('section.window').forEach(function (sec) {
    var name = sec.getAttribute('data-name');
    var lbl = sec.querySelector('.window-label');
    if (!lbl) return;
    lbl.addEventListener('click', function () {
      var rows = (payload.windows[name] || []).map(function (r) {
        var tf = (r.tdformat || '  ').padEnd(2);
        return '[' + r.element + '] ' + tf + ' ' + r.content;
      }).join('\\n');
      title.textContent = name + '  —  ' + (payload.windows[name] || []).length + ' lines';
      body.textContent  = rows || '(no lines)';
      aside.hidden = false;
    });
  });
  document.querySelectorAll('.field').forEach(function (f) {
    var raw = f.getAttribute('data-raw');
    if (raw) { f.setAttribute('title', raw); }
  });
  var canvas = document.querySelector('main.canvas');
  document.getElementById('show-grid').addEventListener('change', function (e) {
    canvas.classList.toggle('grid', e.target.checked);
  });
  document.getElementById('show-borders').addEventListener('change', function (e) {
    canvas.classList.toggle('no-borders', !e.target.checked);
  });
})();
"""


def _render_inspector_and_js(payload: dict) -> str:
    payload_json = _json.dumps(payload, ensure_ascii=False)
    # Inline JSON; neutralise sequences that would break out of the <script>
    # or terminate JS string literals:
    #  - `</` → `<\/` (prevents premature </script> close)
    #  - U+2028 / U+2029 → \u2028 / \u2029 (legal in JSON, illegal in raw JS
    #    string literals in pre-ES2019 parsers).
    payload_safe = (
        payload_json
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return (
        '<aside class="inspector" hidden>\n'
        '<header><h2 id="insp-title">—</h2>'
        '<button id="insp-close" type="button" aria-label="Close inspector">×</button></header>\n'
        '<pre id="insp-body"></pre>\n'
        '</aside>\n'
        f'<script type="application/json" id="raw-windows">{payload_safe}</script>\n'
        "<script>\n"
        + _INSPECTOR_JS +
        "\n</script>\n"
    )


def _resolve_desc(wd, prefer_language: str, original_language: str) -> str:
    if wd is None:
        return ""
    for lg in (prefer_language, original_language):
        if lg and wd.description.get(lg):
            return wd.description[lg]
    return ""


def _render_window_section(name: str, kind: str, cls: str,
                           x: float, y: float, w: float, h: float,
                           desc: str, body: str) -> str:
    return (
        f'<section class="window {cls}" data-name="{_esc(name)}" '
        f'data-kind="{_esc(kind)}" '
        f'style="left:{x}cm;top:{y}cm;width:{w}cm;height:{h}cm;">\n'
        f'<h2 class="window-label">{_esc(name)} '
        f'<span class="kind">[{_esc(kind)}]</span>'
        f'<span class="desc">{_esc(desc)}</span></h2>\n'
        f'<div class="window-body">{body}</div>\n'
        f'</section>\n'
    )


def _render_canvas(ast: FormAST, page: str, w_cm: float, h_cm: float,
                   prefer_language: str) -> str:
    out = [f'<main class="canvas" style="width: {w_cm}cm; height: {h_cm}cm;">\n']

    # MAIN placement (stored on PageDef)
    pd = ast.pages.get(page)
    if pd and pd.main_window:
        x, y, ww, hh = pd.main_window
        wd = ast.windows.get("MAIN")
        kind = wd.type if wd else "MAIN"
        cls = _WINDOW_KIND_CLASS.get(kind, "w-var")
        desc = _resolve_desc(wd, prefer_language, ast.original_language)
        body = "".join(_render_element_raw(e, ast)
                       for e in _elements_for(ast, "MAIN", prefer_language,
                                              ast.original_language))
        out.append(_render_window_section("MAIN", kind, cls, x, y, ww, hh, desc, body))

    for p in ast.page_windows:
        if p.page != page:
            continue
        wd = ast.windows.get(p.window)
        kind = wd.type if wd else "VAR"
        cls = _WINDOW_KIND_CLASS.get(kind, "w-var")
        desc = _resolve_desc(wd, prefer_language, ast.original_language)
        body = "".join(_render_element_raw(e, ast)
                       for e in _elements_for(ast, p.window, prefer_language,
                                              ast.original_language))
        out.append(_render_window_section(p.window, kind, cls,
                                          p.x_cm, p.y_cm, p.width_cm, p.height_cm,
                                          desc, body))

    out.append("</main>\n")
    return "".join(out)


def _elements_for(ast: FormAST, window: str, language: str,
                  fallback_language: str = "") -> list:
    primary = [e for e in ast.elements
               if e.window == window and e.language == language]
    if primary:
        return primary
    if fallback_language and fallback_language != language:
        return [e for e in ast.elements
                if e.window == window and e.language == fallback_language]
    return []


_CH_PER_CM = 12.0 / 2.54   # at 12 CPI
_CH_PER_INCH = 12.0


def _tab_pos_to_ch(pos: float, unit: str) -> float:
    """Approximate a SAPscript tab-stop position in 12-CPI `ch` units.

    SAPscript units: CH (character), CM, MM, IN, TW (twip = 1/1440 inch),
    PT (point = 1/72 inch). We assume a 12-CPI baseline, matching the
    fixture's /:FORM CPI 12 declaration. Forms with other CPI will drift
    but the layout stays visually sensible.
    """
    u = unit.upper()
    if u == "CH":
        return float(pos)
    if u == "CM":
        return float(pos) * _CH_PER_CM
    if u == "MM":
        return float(pos) * _CH_PER_CM / 10.0
    if u == "IN":
        return float(pos) * _CH_PER_INCH
    if u == "TW":
        return float(pos) / 120.0  # 1 inch = 1440 TW, 12 CH/inch → 1 CH = 120 TW
    if u == "PT":
        return float(pos) / 6.0    # 1 inch = 72 PT, 12 CH/inch → 1 CH = 6 PT
    return float(pos)  # unknown unit — treat as already-in-ch


def _tab_grid_style(pf) -> tuple[str, list[str]]:
    """Build grid-template-columns + per-column align classes from tab stops.

    Tab stops are cumulative positions. Column N width = position N minus
    previous position. All emitted widths are in `ch` units, converted from
    the tab-stop's declared unit via _tab_pos_to_ch. Last column = 1fr.
    Returns (style_value, list_of_align_classes).
    """
    prev_ch = 0.0
    cols: list[str] = []
    aligns: list[str] = []
    for pos, unit, align in pf.tabs:
        pos_ch = _tab_pos_to_ch(pos, unit)
        width = max(1.0, pos_ch - prev_ch)
        # Round to 1 decimal for compact CSS
        cols.append(f"{width:g}ch")
        aligns.append(align.lower())
        prev_ch = pos_ch
    cols.append("1fr")
    aligns.append("left")
    return " ".join(cols), aligns


def _active_tags_at_splits(merged: str) -> list[list[str]]:
    """For each `,,` split point in `merged`, return the stack of inline-char
    tags (e.g. ["UB"]) that are open at that point. Returns len(cells) lists;
    cells[0] always starts with an empty list (no tags carried in from
    outside).
    """
    snapshots: list[list[str]] = [[]]
    stack: list[str] = []
    i = 0
    # Simple forward scan. We duplicate a subset of _CHAR_TAG_RE's matching
    # logic to stay in sync with _render_inline; if someone changes the tag
    # grammar there, this helper must change too.
    while i < len(merged):
        # Detect `,,`
        if merged.startswith(",,", i):
            snapshots.append(list(stack))
            i += 2
            continue
        # Detect `</>`: close top of stack.
        if merged.startswith("</>", i):
            if stack:
                stack.pop()
            i += 3
            continue
        # Detect `<TAG>` for bold / underline / barcode style names.
        if merged[i] == "<":
            m = _CHAR_TAG_RE.match(merged, i)
            if m:
                is_close = m.group(1) is None  # `</>` has no capture group
                if is_close:
                    if stack:
                        stack.pop()
                else:
                    stack.append(m.group(1).upper())
                i = m.end()
                continue
        i += 1
    return snapshots


def _render_tab_line(merged: str, pf, tf: str) -> str:
    """Render a `,,`-tabbed line as a CSS-grid row."""
    cells = merged.split(",,")
    tf_key = tf.strip() or "_blank"
    style, aligns = _tab_grid_style(pf)
    tag_stacks = _active_tags_at_splits(merged)  # len == len(cells)

    parts = [
        f'<div class="line tabbed pf-{_esc(tf_key)}" data-tdformat="{_esc(tf)}" '
        f'style="grid-template-columns: {style};">'
        f'<span class="tf">{_esc(tf)}</span>'
    ]
    for idx, cell in enumerate(cells):
        a = aligns[idx] if idx < len(aligns) else "left"
        active = tag_stacks[idx]
        # Re-open any tags active at this split point so the cell renders with
        # the correct inline formatting even if the original `<TAG>` lives in
        # an earlier cell. Close them at the end so _render_inline sees a
        # balanced fragment.
        prefix = "".join(f"<{t}>" for t in active)
        suffix = "".join("</>" for _ in active)
        parts.append(
            f'<span class="cell cell-{a}">'
            f'{_render_inline(prefix + cell + suffix)}'
            f'</span>'
        )
    parts.append("</div>\n")
    return "".join(parts)


_IFF_START = ("IF",)
_IFF_ELSE = ("ELSEIF", "ELSE")
_IFF_END = ("ENDIF",)
_PROT_START = ("PROTECT",)
_PROT_END = ("ENDPROTECT",)


def _first_token(s: str) -> str:
    s = s.strip()
    return s.split(None, 1)[0].upper() if s else ""


def _render_element_raw(element, ast: FormAST) -> str:
    """Render an element, recognising /:IF trees and /:PROTECT wrappers."""
    out = [f'<article class="element" data-element="{_esc(element.name or "_pre")}">\n',
           f'<h3 class="element-label">/E {_esc(element.name or "(pre)")}</h3>\n',
           '<div class="itf-body">\n']

    # Track open-scope depth with plain counters; only len() / truthiness
    # matters, so a list-of-True sentinels would be misleading.
    iff_depth = 0
    protect_depth = 0

    def _open_iff(cond: str) -> str:
        nonlocal iff_depth
        iff_depth += 1
        return (f'<div class="iff">'
                f'<div class="iff-cond iff-if">IF {_esc(cond)}</div>'
                f'<div class="iff-branch">')

    def _elseif(cond: str, keyword: str) -> str:
        # Close previous branch, open new one. Only close when an IF is open
        # to avoid injecting a stray </div> on malformed input.
        close = "</div>" if iff_depth else ""
        return (f'{close}<div class="iff-cond iff-{keyword.lower()}">'
                f'{_esc(keyword)} {_esc(cond)}</div>'
                f'<div class="iff-branch">')

    def _close_iff() -> str:
        nonlocal iff_depth
        if iff_depth:
            iff_depth -= 1
        return "</div></div>"

    def _open_protect() -> str:
        nonlocal protect_depth
        protect_depth += 1
        return '<div class="protect"><div class="protect-label">PROTECT</div>'

    def _close_protect() -> str:
        nonlocal protect_depth
        if protect_depth:
            protect_depth -= 1
        return "</div>"

    i = 0
    lines = element.lines
    while i < len(lines):
        line = lines[i]
        tf = line.tdformat
        content = line.content
        head = _first_token(content) if tf == "/:" else ""

        # /:IF, /:ELSEIF, /:ELSE, /:ENDIF
        if tf == "/:" and head in _IFF_START:
            cond = content.strip()[len(head):].strip()
            out.append(_open_iff(cond))
            i += 1
            continue
        if tf == "/:" and head in _IFF_END:
            out.append(_close_iff())
            i += 1
            continue
        if tf == "/:" and head == "ELSEIF":
            cond = content.strip()[len("ELSEIF"):].strip()
            out.append(_elseif(cond, "ELSEIF"))
            i += 1
            continue
        if tf == "/:" and head == "ELSE":
            out.append(_elseif("", "ELSE"))
            i += 1
            continue

        # /:PROTECT, /:ENDPROTECT
        if tf == "/:" and head in _PROT_START:
            out.append(_open_protect())
            i += 1
            continue
        if tf == "/:" and head in _PROT_END:
            out.append(_close_protect())
            i += 1
            continue

        # /:BOX — draws a framed rectangle in SAPscript. We render a visible
        # bordered div as a structural hint. The directive's parameters
        # (FRAME thickness, XPOS, YPOS, WIDTH, HEIGHT, etc.) are shown as
        # a small monospace label inside for reference.
        if tf == "/:" and head == "BOX":
            # content is like "BOX FRAME 10 TW" or "BOX XPOS 1 CM YPOS 2 CM WIDTH 5 CM HEIGHT 3 CM FRAME 10 TW"
            params = content.strip()[len(head):].strip()
            out.append(
                f'<div class="box" data-tdformat="/:">'
                f'<span class="box-label">BOX</span>'
                f'<span class="box-params">{_esc(params)}</span>'
                f'</div>\n'
            )
            i += 1
            continue

        # /:INCLUDE stub
        if tf == "/:" and head == "INCLUDE":
            out.append(
                f'<div class="incl" data-tdformat="/:">'
                f'<span class="incl-label">INCLUDE</span>'
                f'<span class="content">{_render_inline(content)}</span>'
                f'</div>\n'
            )
            i += 1
            continue
        # Begin address block. Consume lines until /:ENDADDRESS.
        # If /:ENDADDRESS is missing (truncated export), the inner loop
        # reaches end-of-lines and the remaining element body is silently
        # absorbed into the address block — acceptable for a preview tool.
        if tf == "/:" and head == "ADDRESS":
            addr_rows: list[str] = []
            j = i + 1
            while j < len(lines):
                a_tf = lines[j].tdformat
                a_content = lines[j].content
                if a_tf == "/:" and _first_token(a_content) == "ENDADDRESS":
                    j += 1
                    break
                if a_tf == "/:":
                    kw = _first_token(a_content)
                    val = a_content.strip()[len(kw):].strip()
                    addr_rows.append(
                        f'<div class="addr-row"><span class="addr-key">{_esc(kw)}</span>'
                        f'<span class="addr-val">{_render_inline(val)}</span></div>'
                    )
                j += 1
            out.append(
                f'<div class="address"><div class="addr-label">ADDRESS</div>'
                f'{"".join(addr_rows)}</div>\n'
            )
            i = j
            continue
        # Blank-paragraph marker `/ `: emit a spacer, no text.
        if tf == "/ ":
            out.append(
                '<div class="line br" data-tdformat="/ ">'
                '<span class="tf">/ </span>'
                '</div>\n'
            )
            i += 1
            continue
        # Control lines + comments are emitted raw.
        if tf in ("/:", "/*"):
            klass = "ctrl" if tf == "/:" else "comment"
            out.append(
                f'<div class="line tf-slash-colon {klass}" data-tdformat="{_esc(tf)}">'
                f'<span class="tf">{_esc(tf)}</span>'
                f'<span class="content">{_render_inline(content)}</span>'
                f'</div>\n'
            )
            i += 1
            continue
        # /W or /E markers should never appear inside an element body (AST
        # already split them off). Emit them as plain if somehow present.
        if tf in ("/W", "/E"):
            out.append(
                f'<div class="line marker" data-tdformat="{_esc(tf)}">'
                f'<span class="tf">{_esc(tf)}</span>'
                f'<span class="content">{_render_inline(content)}</span>'
                f'</div>\n'
            )
            i += 1
            continue
        # Data line. Look ahead: gather all `= ` continuation lines into one.
        merged = content
        j = i + 1
        while j < len(lines) and lines[j].tdformat == "= ":
            # SAP wrap rules: continuation replaces the trailing newline, but
            # we want a single space join so the merged content reads correctly
            # and inline tags (like <UB>...</>) straddling the split still match.
            merged += lines[j].content
            j += 1

        tf_key = tf.strip() or "_blank"
        pf = ast.paragraphs.get(tf_key)
        if pf is not None and pf.tabs and ",," in merged:
            out.append(_render_tab_line(merged, pf, tf))
        else:
            pf_class = f"pf-{_esc(tf_key)}" if pf is not None else ""
            tf_class = _tdformat_class(tf)
            # Class order matters: `pf-<name>` MUST come before `tf-<code>` so tests
            # that check `class="line pf-R` substrings keep matching as more classes
            # are added in later tasks.
            if pf_class:
                classes = f"line {pf_class} {tf_class}"
            else:
                classes = f"line {tf_class}"
            out.append(
                f'<div class="{classes}" data-tdformat="{_esc(tf)}">'
                f'<span class="tf">{_esc(tf)}</span>'
                f'<span class="content">{_render_inline(merged)}</span>'
                f'</div>\n'
            )
        i = j

    # Defensive close for malformed elements.
    while iff_depth:
        out.append(_close_iff())
    while protect_depth:
        out.append(_close_protect())

    out.append('</div></article>\n')
    return "".join(out)


def render_html(ast: FormAST, path: str, page: str = "FIRST",
                prefer_language: str = "E") -> None:
    """Render an AST to a self-contained HTML preview file at `path`."""
    w_cm, h_cm = _page_dimensions_cm(ast)
    payload = _collect_raw_payload(ast, page, prefer_language)
    parts = [
        _render_head(ast, page),
        "<body>\n",
        _render_topbar(ast, page, w_cm, h_cm),
        _render_canvas(ast, page, w_cm, h_cm, prefer_language),
        _render_legend(),
        _render_inspector_and_js(payload),
        "</body>\n</html>\n",
    ]
    Path(path).write_text("".join(parts), encoding="utf-8")
