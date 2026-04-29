from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sapscript"
FIXTURE_FORM = FIXTURE_DIR / "J_2GLP_DASD.FOR"
FIXTURE_DIALECT_A = FIXTURE_DIR / "fixture_dialect_a.itf"
FIXTURE_BAD_HEAD = FIXTURE_DIR / "fixture_bad_head.FOR"


def test_fixture_present():
    assert FIXTURE_FORM.exists()
    assert FIXTURE_DIALECT_A.exists()
    assert FIXTURE_BAD_HEAD.exists()


def test_dataclasses_importable():
    from tools.sapscript import (
        HeadMeta, ItfLine, Block,
        ParagraphFormat, CharFormat, WindowDef,
        PageWindowPos, PageDef, ElementBody, FormAST,
    )
    h = HeadMeta(object_kind="FORM", object_name="X", block_kind="DEF",
                 language="E", raw="raw")
    assert h.object_name == "X"
    line = ItfLine(tdformat="/:", content="FORM X;")
    assert line.tdformat == "/:"
    pf = ParagraphFormat(name="L")
    assert pf.tabs == [] and pf.description == {}


def test_classify_record_kinds():
    from tools.sapscript import _classify_record
    assert _classify_record("SFORMJ_2GLP_DASD")[0] == "SFORM"
    assert _classify_record("HFORMJ_2GLP_DASD")[0] == "HFORM"
    assert _classify_record(" OLANG")[0] == "OLANG"
    assert _classify_record(" HEADFORM      ZFOO  ...")[0] == "HEAD"
    assert _classify_record(" LINE/:FORM")[0] == "LINE"
    assert _classify_record(" END")[0] == "END"
    assert _classify_record("ACTVSAPE")[0] == "ACTV"


def test_classify_unknown_raises():
    from tools.sapscript import _classify_record, ITFParseError
    with pytest.raises(ITFParseError):
        _classify_record("WEIRDTAG")


def test_parse_head_def():
    from tools.sapscript import _parse_head
    line = " HEADFORM      J_2GLP_DASD     SAP                                                   DEF GFor printing DA(SD)                               J_2GLP_DASD             00000C5000334    22E 19970602132525CCC00419    756 2025062511370113200059 G0                                                                                                                           200"
    meta = _parse_head(line)
    assert meta.object_kind == "FORM"
    assert meta.object_name == "J_2GLP_DASD"
    assert meta.block_kind == "DEF"
    assert meta.language == "G"
    assert meta.raw == line


def test_parse_head_txt():
    from tools.sapscript import _parse_head
    line = " HEADFORM      J_2GLP_DASD     SAP                                                   TXT EFor printing DA(SD)                               J_2GLP_DASD             00000C5000334    22E 19970602132525CCC00419    756 2025062511370113200193 G0                                                                                                                           200"
    meta = _parse_head(line)
    assert meta.block_kind == "TXT"
    assert meta.language == "E"


def test_parse_form_file_structure():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert ast.form_name == "J_2GLP_DASD"
    assert ast.original_language == "G"
    assert ast.sform_line.startswith("SFORM")
    assert ast.hform_line.startswith("HFORM")
    assert ast.olang_line.startswith(" OLANG")
    assert ast.trailer.startswith("ACTV")
    assert ast.def_block is not None
    assert ast.def_block.meta.block_kind == "DEF"
    assert ast.def_block.meta.language == "G"
    assert len(ast.txt_blocks) == 2
    langs = {b.meta.language for b in ast.txt_blocks}
    assert langs == {"E", "G"}


def test_parse_form_file_def_has_line_records():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    first = ast.def_block.lines[0]
    assert first.tdformat == "/:"
    assert first.content.startswith("FORM CPI 12")


def test_parse_form_file_dialect_a_rejected():
    from tools.sapscript import parse_form_file, UnsupportedDialect
    with pytest.raises(UnsupportedDialect):
        parse_form_file(str(FIXTURE_DIALECT_A))


def test_parse_form_file_unbalanced_head_rejected():
    from tools.sapscript import parse_form_file, ITFParseError
    with pytest.raises(ITFParseError):
        parse_form_file(str(FIXTURE_BAD_HEAD))


@pytest.mark.parametrize("bad_name", [
    "../../etc/passwd",
    "..\\..\\windows",
    "/etc/passwd",
    "C:\\Windows",
    "name with spaces",
    "lowercase",
    "TOO_LONG_FORM_NAME_OVER_THIRTY_CHARS_XX",
    "with.dot",
    "",
])
def test_parse_form_file_rejects_unsafe_form_name(tmp_path, bad_name):
    from tools.sapscript import parse_form_file, ITFParseError
    p = tmp_path / "evil.FOR"
    p.write_text(f"SFORM{bad_name}\n", encoding="utf-8")
    with pytest.raises(ITFParseError):
        parse_form_file(str(p))


def test_parse_form_file_missing_raises_file_not_found():
    from tools.sapscript import parse_form_file
    with pytest.raises(FileNotFoundError):
        parse_form_file("/no/such/file.FOR")


def test_def_form_settings():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert ast.cpi == 12.0
    assert ast.lpi == 6.0
    assert ast.page_format == "DINA4"
    assert ast.orientation == "LANDSCAPE"
    assert ast.form_settings.get("START-PAGE") == "FIRST"


def test_def_paragraphs():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert set(ast.paragraphs) == {"L", "IT", "CN", "R", "VS", "VT"}
    cn = ast.paragraphs["CN"]
    assert cn.alignment == "CENTER"
    assert cn.line_space == "1 LN"
    it = ast.paragraphs["IT"]
    assert len(it.tabs) == 10
    assert it.tabs[0] == (6, "CH", "LEFT")
    assert it.tabs[-1] == (113, "CH", "LEFT")


def test_def_char_formats():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert set(ast.char_formats) == {"B", "BC", "UB"}
    assert ast.char_formats["B"].bold is True
    assert ast.char_formats["UB"].bold is True
    assert ast.char_formats["UB"].underline is True
    assert ast.char_formats["BC"].barcode == "J2GQR"


def test_def_windows():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    expected = {"AADE", "CARRYTO", "COMPANY", "EDAT", "EDDOC", "HEADER",
                "MAIN", "PAGE", "PAIPS", "PAR", "PEL", "PRO", "SUM", "VAT"}
    assert set(ast.windows) == expected
    assert ast.windows["MAIN"].type == "MAIN"
    assert ast.windows["HEADER"].type == "CONST"
    assert ast.windows["EDAT"].type == "VAR"


def test_units_to_cm_basic():
    from tools.sapscript import _units_to_cm
    assert abs(_units_to_cm(1, "CH", cpi=12.0, lpi=6.0) - 0.2117) < 1e-3
    assert abs(_units_to_cm(1, "LN", cpi=12.0, lpi=6.0) - 0.4233) < 1e-3
    assert _units_to_cm(5, "CM", cpi=12, lpi=6) == 5.0
    assert abs(_units_to_cm(10, "MM", cpi=12, lpi=6) - 1.0) < 1e-6
    assert abs(_units_to_cm(1, "IN", cpi=12, lpi=6) - 2.54) < 1e-6
    assert abs(_units_to_cm(1440, "TW", cpi=12, lpi=6) - 2.54) < 1e-3


def test_page_definitions():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert set(ast.pages) == {"FIRST", "NEXT"}
    assert ast.pages["FIRST"].next_page == "NEXT"
    assert ast.pages["NEXT"].next_page == "NEXT"
    mw = ast.pages["FIRST"].main_window
    assert mw is not None
    assert abs(mw[0]) < 1e-3
    assert abs(mw[1] - 7.1967) < 1e-2
    assert abs(mw[2] - 27.94) < 1e-2
    assert abs(mw[3] - 8.4667) < 1e-2


def test_page_window_positions():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    first_positions = [p for p in ast.page_windows if p.page == "FIRST"]
    next_positions = [p for p in ast.page_windows if p.page == "NEXT"]
    # 13 /:PAGE ... WINDOW placements on FIRST; MAIN is tracked separately on
    # PageDef.main_window. NEXT has 9 placements + MAIN.
    assert len(first_positions) == 13
    assert len(next_positions) == 9
    header = next(p for p in first_positions if p.window == "HEADER")
    assert abs(header.x_cm - 59 * (2.54/12)) < 1e-3
    assert abs(header.y_cm - 3 * (2.54/6)) < 1e-3
    assert abs(header.width_cm - 74 * (2.54/12)) < 1e-3
    assert abs(header.height_cm - 5 * (2.54/6)) < 1e-3
    aade = next(p for p in first_positions if p.window == "AADE")
    assert aade.x_cm == 26.0
    assert aade.width_cm == 2.70


def test_txt_descriptions_english():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert ast.windows["MAIN"].description.get("E") == "Item details"
    assert ast.windows["HEADER"].description.get("E") == "Header info"
    assert ast.paragraphs["CN"].description.get("E") == "Centered"
    assert ast.char_formats["B"].description.get("E") == "Bold"
    assert ast.pages["FIRST"].description.get("E") == "First page"


def test_txt_descriptions_greek_also_present():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    assert ast.windows["MAIN"].description.get("G") == "Item details"


def test_elements_in_main_window():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    main_e = [e for e in ast.elements if e.window == "MAIN" and e.language == "E"]
    names = {e.name for e in main_e}
    assert {"MY_TOP", "CARRY_FROM", "HEADER_TEXT", "ITEM_LINE"} <= names
    item_line = next(e for e in main_e if e.name == "ITEM_LINE")
    content_joined = "\n".join(l.tdformat + l.content for l in item_line.lines)
    assert "/:INCLUDE" in content_joined
    assert "/:IF" in content_joined
    assert "/:ENDIF" in content_joined


def test_element_counts_match_reference_summary():
    from tools.sapscript import parse_form_file
    ast = parse_form_file(str(FIXTURE_FORM))
    e_elements = [e for e in ast.elements if e.language == "E"]
    assert len(e_elements) >= 20


def test_write_outline_creates_file(tmp_path):
    from tools.sapscript import parse_form_file, write_outline
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.txt"
    write_outline(ast, str(out), prefer_language="E")
    content = out.read_text(encoding="utf-8")
    assert "FORM J_2GLP_DASD" in content
    assert "PAGES" in content
    assert "WINDOWS" in content
    assert "PARAGRAPH FORMATS" in content
    assert "CHARACTER FORMATS" in content
    assert "ELEMENTS" in content
    assert "Header info" in content
    assert "Item details" in content
    assert "ITEM_LINE" in content


def test_outline_matches_snapshot(tmp_path):
    from tools.sapscript import parse_form_file, write_outline
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.txt"
    write_outline(ast, str(out), prefer_language="E")
    actual = out.read_text(encoding="utf-8")
    expected = (FIXTURE_DIR / "J_2GLP_DASD.outline.expected.txt").read_text(encoding="utf-8")
    assert actual == expected


def test_render_wireframe_produces_png(tmp_path):
    from tools.sapscript import parse_form_file, render_wireframe
    pytest.importorskip("PIL")
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.png"
    result = render_wireframe(ast, page="FIRST", path=str(out), prefer_language="E")
    assert result is True
    data = out.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    from PIL import Image
    with Image.open(out) as im:
        assert im.width >= 1000
        assert im.height >= 600


def test_render_wireframe_without_pillow_is_guarded(tmp_path, monkeypatch):
    from tools import sapscript
    ast = sapscript.parse_form_file(str(FIXTURE_FORM))
    monkeypatch.setattr(sapscript, "_import_pillow", lambda: None)
    ok = sapscript.render_wireframe(ast, page="FIRST", path=str(tmp_path / "out.png"))
    assert ok is False


def test_read_form_tool_success(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl(str(FIXTURE_FORM), render=True)
    assert "error" not in result
    assert result["form_name"] == "J_2GLP_DASD"
    assert result["original_language"] == "G"
    assert result["pages"] == 2
    assert result["windows"] == 14
    assert result["elements"] >= 20
    from pathlib import Path
    assert Path(result["source_file"]).exists()
    assert Path(result["outline_file"]).exists()
    assert result["wireframe_file"] is not None
    assert Path(result["wireframe_file"]).exists()


def test_read_form_tool_missing_file(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl("/no/such/file.FOR", render=True)
    assert result["error"] == "FileNotFound"


def test_read_form_tool_dialect_a(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl(str(FIXTURE_DIALECT_A), render=True)
    assert result["error"] == "UnsupportedDialect"


def test_read_form_tool_render_false_skips_wireframe(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl(str(FIXTURE_FORM), render=False)
    assert result["wireframe_file"] is None


def test_extract_symbols_basic():
    from tools.sapscript import _extract_symbols
    assert _extract_symbols("hello world") == []
    assert _extract_symbols("&VBAK-VBELN&") == ["&VBAK-VBELN&"]
    assert _extract_symbols(",,&VBAP-KWMENG& &VBAP-VRKME&,,&KOMV-KBETR&") == [
        "&VBAP-KWMENG&", "&VBAP-VRKME&", "&KOMV-KBETR&",
    ]
    # SAPscript uses `&&` as a literal ampersand escape — must not be extracted.
    assert _extract_symbols("Price: 10&&20 &VBAP-NETPR&") == ["&VBAP-NETPR&"]


def test_extract_symbols_deduplicates_preserves_first_order():
    from tools.sapscript import _extract_symbols
    # VBAK-VBELN appears twice; should land once, in its first-seen position.
    line = "&VBAK-VBELN& something &VBAK-KUNNR& then &VBAK-VBELN& again"
    assert _extract_symbols(line) == ["&VBAK-VBELN&", "&VBAK-KUNNR&"]


def test_extract_symbols_supports_format_suffix_and_functions():
    from tools.sapscript import _extract_symbols
    # SAPscript supports &SYMBOL(C)&, &SYMBOL+5(10)&, &SYMBOL.DATE()& etc. — any
    # non-whitespace run between two & characters counts.
    assert _extract_symbols("&VBAK-ERDAT(DATE)&") == ["&VBAK-ERDAT(DATE)&"]
    assert _extract_symbols("&SYMBOL+5(10)&") == ["&SYMBOL+5(10)&"]


def test_render_html_produces_file(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl(str(FIXTURE_FORM), render=False, render_html=True)
    assert "error" not in result
    assert result["preview_file"] is not None
    from pathlib import Path
    assert Path(result["preview_file"]).exists()
    html = Path(result["preview_file"]).read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "J_2GLP_DASD" in html


def test_render_html_disabled_when_flag_false(tmp_path, monkeypatch):
    import cache
    from tools import sapscript as ss
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = ss._read_form_impl(str(FIXTURE_FORM), render=False, render_html=False)
    assert result["preview_file"] is None


def test_render_html_canvas_sized_in_cm():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    ast = parse_form_file(str(FIXTURE_FORM))
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # DINA4 LANDSCAPE = 29.7 x 21 cm
    assert 'width: 29.7cm' in html or 'width:29.7cm' in html
    assert 'height: 21' in html or 'height:21' in html


def test_render_html_has_one_section_per_placed_window():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    ast = parse_form_file(str(FIXTURE_FORM))
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # All 14 windows have a placement on FIRST (13 via /:PAGE WINDOW + 1 MAIN).
    for name in ["AADE","CARRYTO","COMPANY","EDAT","EDDOC","HEADER","MAIN",
                 "PAGE","PAIPS","PAR","PEL","PRO","SUM","VAT"]:
        assert f'data-name="{name}"' in html, f"missing window {name}"


def test_render_html_elements_in_main():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # Inside MAIN window: 4 elements in English.
    for name in ("MY_TOP", "CARRY_FROM", "HEADER_TEXT", "ITEM_LINE"):
        assert f'data-element="{name}"' in html, f"missing element {name}"


def test_render_html_line_present_in_sum_item():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # A line from SUM/ITEM — the first totals field — must appear as an escaped
    # literal (ampersands encoded). The AST uses TDFORMAT VT for these lines.
    assert "J_2GLPPSDTOT-GRVAL" in html


def test_outline_element_body_has_content_and_paragraph_tag(tmp_path):
    from tools.sapscript import parse_form_file, write_outline
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.txt"
    write_outline(ast, str(out), prefer_language="E")
    content = out.read_text(encoding="utf-8")

    # The ITEM_LINE element lives in MAIN and uses paragraph IT.
    assert "ITEM_LINE" in content
    # Header line carries the paragraph annotation.
    header_line = next(
        l for l in content.splitlines()
        if "ITEM_LINE" in l and "paragraph=" in l
    )
    assert "paragraph=IT" in header_line

    # At least one of the body lines retains the IT tdformat marker and a
    # SAPscript symbol reference from the original ITF source.
    assert "IT  " in content  # 2-char tdformat + 2 spaces gap
    assert "&J_2GLPPSDM-" in content

    # The paragraph annotation must only carry real paragraph names (keys of
    # ast.paragraphs), never continuation/control tdformats like '= ' or '* '.
    # No header line should carry `paragraph==` or `paragraph=*`.
    for line in content.splitlines():
        if "paragraph=" in line:
            assert "paragraph==" not in line
            assert "paragraph=*" not in line


def test_outline_element_body_has_fields_summary(tmp_path):
    from tools.sapscript import parse_form_file, write_outline
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.txt"
    write_outline(ast, str(out), prefer_language="E")
    content = out.read_text(encoding="utf-8")
    # At least one fields: line must appear under an element that references
    # SAPscript symbols. We don't pin the exact fields — the snapshot test
    # does that — but we verify the line label is present.
    assert "fields:" in content


def test_outline_element_body_respects_cap(tmp_path, monkeypatch):
    from tools import sapscript as ss
    from tools.sapscript import parse_form_file, write_outline
    # Force the cap low so the real fixture exercises truncation.
    monkeypatch.setattr(ss, "ELEMENT_BODY_LINE_CAP", 5)
    ast = parse_form_file(str(FIXTURE_FORM))
    out = tmp_path / "out.txt"
    write_outline(ast, str(out), prefer_language="E")
    content = out.read_text(encoding="utf-8")
    # Truncation marker must mention remaining line count and point at the
    # source file.
    assert "more lines" in content
    assert ".FOR" in content


def test_render_html_tdformat_class_whitelist():
    """Unknown TDFORMAT tokens fall back to tf-unknown, not a raw class token."""
    from tools.sapscript import FormAST, WindowDef, ElementBody, ItfLine, PageDef, PageWindowPos
    from tools.sapscript_html import render_html
    ast = FormAST(form_name="ZTEST", original_language="E")
    ast.page_format = "DINA4"
    ast.orientation = "PORTRAIT"
    ast.windows["W"] = WindowDef(name="W", type="VAR",
                                  description={"E": "test window"})
    ast.pages["FIRST"] = PageDef(name="FIRST")
    ast.page_windows.append(PageWindowPos(page="FIRST", window="W",
                                          x_cm=1, y_cm=1, width_cm=5, height_cm=3))
    # TDFORMAT with a space — would have been split into two class tokens before.
    ast.elements.append(ElementBody(window="W", name="E1", language="E",
                                    lines=[ItfLine(tdformat="X Y", content="test")]))
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # No dangling space inside the class attribute.
    assert 'class="line tf-unknown"' in html
    # And the data-tdformat attribute still carries the raw value for debugging.
    assert 'data-tdformat="X Y"' in html


def test_render_html_falls_back_to_original_language_for_elements():
    """When no elements exist in prefer_language, fall back to original."""
    from tools.sapscript import FormAST, WindowDef, ElementBody, ItfLine, PageDef, PageWindowPos
    from tools.sapscript_html import render_html
    ast = FormAST(form_name="ZTEST", original_language="G")
    ast.page_format = "DINA4"
    ast.orientation = "PORTRAIT"
    ast.windows["W"] = WindowDef(name="W", type="CONST",
                                  description={"G": "Greek-only"})
    ast.pages["FIRST"] = PageDef(name="FIRST")
    ast.page_windows.append(PageWindowPos(page="FIRST", window="W",
                                          x_cm=1, y_cm=1, width_cm=5, height_cm=3))
    # Only Greek elements exist; renderer is asked for English.
    ast.elements.append(ElementBody(window="W", name="ONLY_GREEK", language="G",
                                    lines=[ItfLine(tdformat="L ", content="hello")]))
    import tempfile, pathlib
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    assert 'data-element="ONLY_GREEK"' in html
    assert "hello" in html


def test_render_html_field_symbol_highlighted():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # J_2GLPPSDNM-VBELN(I) should be rendered as a field span with its options
    # as a sub. Check the span class and the I11-like option sub exists.
    assert '<span class="field"' in html
    # At least one known field name from HEADER element.
    assert "J_2GLPPSDNM-VBELN" in html
    # Option bracket wrapped as sub (for any of the many I11/I8.3/Z/... uses).
    assert '<sub class="opts">' in html


def test_render_html_inline_bold():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # COMPANY has a line: LINEL <B>Στοιχεία Εταιρίας</>
    # Expected: <b class="cf-B">Στοιχεία Εταιρίας</b>
    assert '<b class="cf-B">Στοιχεία Εταιρίας</b>' in html


def test_render_html_inline_ub_both_bold_and_underline():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # MY_TOP has <UB>AA,,ΚΩΔΙΚΟΣ,,...</>
    # Expected: an element with class="cf-UB" wrapping the text, rendered as
    # both bold + underline.
    assert '<b class="cf-UB"><u>' in html
    assert '</u></b>' in html


def test_render_html_barcode_pill():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # AADE element has <BC>https://www1.aade.gr/tameiakes/...</>
    # Expected: wrapped in class="cf-BC".
    assert '<span class="cf-BC">' in html


def test_render_html_paragraph_class_applied():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # HEADER has R-aligned lines ("/:WINDOW HEADER" → element lines use R format).
    # The generated stylesheet must declare .pf-R with text-align: right.
    assert ".pf-R" in html
    assert "text-align: right" in html or "text-align:right" in html
    # At least one <div class="line pf-R"> from the AADE/HEADER region.
    assert 'class="line pf-R' in html


def test_render_html_continuation_merged():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # MY_TOP line 1 uses TDFORMAT IT; line 2 uses TDFORMAT '= ' (continuation).
    # After merge, there should be exactly one pf-IT line containing both
    # "ΚΩΔΙΚΟΣ" and "ΣΧΕΤΙΚΟ ΠΑΡΑΣΤ." (first + continuation content), and
    # NO standalone <div class="line tf-eq"> for that pair inside MY_TOP.
    import re
    main_block = re.search(
        r'data-name="MAIN"[\s\S]*?data-element="MY_TOP"[\s\S]*?</article>',
        html,
    )
    assert main_block is not None
    section = main_block.group(0)
    assert "ΚΩΔΙΚΟΣ" in section
    assert "ΣΧΕΤΙΚΟ ΠΑΡΑΣΤ." in section
    # The continuation's merged content should live inside a single pf-IT line.
    # We count the number of pf-IT div lines in MY_TOP (tab rendering uses
    # class="line tabbed pf-IT", plain rendering uses class="line pf-IT tf-IT"):
    pf_it_lines = section.count('pf-IT')
    # Before merge: 1 pf-IT + 1 tf-eq = 2. After merge: 1 pf-IT only.
    assert pf_it_lines == 1


def test_render_html_if_tree_rendered():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib, re
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # ITEM_LINE in MAIN has /:IF ... /:ELSEIF ... /:ELSE ... /:ENDIF.
    block = re.search(
        r'data-element="ITEM_LINE"[\s\S]*?</article>',
        html,
    ).group(0)
    # The IF tree should be wrapped in a container.
    assert '<div class="iff"' in block
    # ELSEIF label visible (iff-cond is always followed by a type class).
    assert 'class="iff-cond ' in block
    # At least one /:PROTECT ... /:ENDPROTECT inside a branch → class="protect".
    assert 'class="protect"' in block


def test_render_html_nested_if_balanced():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib, re
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # PEL element has nested /:IF ... /:IF ... /:ENDIF /:ENDIF.
    block = re.search(
        r'data-name="PEL"[\s\S]*?</section>',
        html,
    ).group(0)
    open_count = block.count('<div class="iff"')
    # Two IFs → two `iff` divs; closing counts must match.
    assert open_count >= 2
    # Balance: each `<div class="iff"` has exactly one matching `</div>` pair
    # — we just sanity-check that the document is well-formed by counting
    # div opens/closes in the PEL section. Allow extra for sub-wrappers.
    # Every <div opens must have a matching </div close in this section.
    assert block.count("<div") == block.count("</div")


def test_render_html_tabs_split_into_cells():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib, re
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # MY_TOP header row is TDFORMAT IT with 10 ,,-separated cells after merge.
    block = re.search(
        r'data-element="MY_TOP"[\s\S]*?</article>',
        html,
    ).group(0)
    # Expect a tabbed container and cells.
    assert 'class="line tabbed' in block
    # Count cells; MY_TOP header has 11 labels → 11 cells.
    cell_count = block.count('class="cell')
    assert cell_count >= 10
    # Issue 2 fix: <UB>...</> straddles cells in MY_TOP. Every cell that
    # originally was inside the <UB>...</> span should now render with
    # cf-UB formatting. The block should contain multiple cf-UB segments.
    assert block.count("cf-UB") >= 2


def test_render_html_include_stub():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib, re
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # MAIN/HEADER_TEXT has /:INCLUDE &J_2GLPPSDNM-TDNAME& OBJECT VBBK ID 0001 ...
    block = re.search(
        r'data-element="HEADER_TEXT"[\s\S]*?</article>',
        html,
    ).group(0)
    assert 'class="incl"' in block
    assert "OBJECT VBBK" in block


def test_render_html_address_block():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    # COMPANY has /:ADDRESS ... /:NAME /:STREET /:CITY /:POSTCODE /:COUNTRY
    # /:FROMCOUNTRY /:ENDADDRESS. Expect a <div class="address"> wrapper.
    assert '<div class="address"' in html
    # Interior should still contain the field span for the company name.
    assert "J_2GLPPSDNM-COM-NAME1" in html


def test_render_html_legend_and_controls():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    assert '<footer class="legend">' in html
    assert 'id="show-grid"' in html
    assert 'id="show-borders"' in html


def test_render_html_inspector_json_embedded():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib, json, re
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(
        r'<script type="application/json" id="raw-windows">(.*?)</script>',
        html, re.DOTALL,
    )
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload["form_name"] == "J_2GLP_DASD"
    # 14 windows, each mapped to a list of ITF line dicts.
    assert set(payload["windows"].keys()) == {
        "AADE","CARRYTO","COMPANY","EDAT","EDDOC","HEADER","MAIN",
        "PAGE","PAIPS","PAR","PEL","PRO","SUM","VAT",
    }
    main = payload["windows"]["MAIN"]
    assert isinstance(main, list)
    assert len(main) > 0
    row = main[0]
    assert set(row.keys()) >= {"element", "tdformat", "content"}


def test_render_html_inspector_aside_present():
    from tools.sapscript import parse_form_file
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = parse_form_file(str(FIXTURE_FORM))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    assert '<aside class="inspector"' in html
    assert 'id="insp-close"' in html
    # JS is inlined.
    assert '<script>' in html and 'addEventListener' in html


def test_render_html_json_escapes_line_separators():
    """U+2028 / U+2029 in SAP content must be escaped inside the inline JSON
    so the <script> block parses cleanly in strict JS parsers."""
    from tools.sapscript import (FormAST, WindowDef, ElementBody, ItfLine,
                                   PageDef, PageWindowPos)
    from tools.sapscript_html import render_html
    import tempfile, pathlib, re
    ast = FormAST(form_name="ZBAD", original_language="E")
    ast.page_format = "DINA4"
    ast.orientation = "PORTRAIT"
    ast.windows["W"] = WindowDef(name="W", type="VAR",
                                  description={"E": "w"})
    ast.pages["FIRST"] = PageDef(name="FIRST")
    ast.page_windows.append(PageWindowPos(page="FIRST", window="W",
                                          x_cm=1, y_cm=1, width_cm=5, height_cm=3))
    # Content containing U+2028 and U+2029.
    ast.elements.append(ElementBody(window="W", name="E1", language="E",
                                    lines=[ItfLine(tdformat="L ",
                                                   content="before\u2028after\u2029end")]))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(
        r'<script type="application/json" id="raw-windows">(.*?)</script>',
        html, re.DOTALL,
    )
    assert m is not None
    payload_str = m.group(1)
    # Raw U+2028 / U+2029 must NOT appear inside the script tag.
    assert "\u2028" not in payload_str
    assert "\u2029" not in payload_str
    # Escaped forms must appear.
    assert "\\u2028" in payload_str
    assert "\\u2029" in payload_str


def test_render_html_box_directive_rendered():
    """/:BOX FRAME 10 TW should emit a <div class="box"> with visible border
    and show the directive parameters as a label."""
    from tools.sapscript import (FormAST, WindowDef, ElementBody, ItfLine,
                                   PageDef, PageWindowPos)
    from tools.sapscript_html import render_html
    import tempfile, pathlib
    ast = FormAST(form_name="ZBOX", original_language="E")
    ast.page_format = "DINA4"
    ast.orientation = "PORTRAIT"
    ast.windows["W"] = WindowDef(name="W", type="VAR", description={"E": "w"})
    ast.pages["FIRST"] = PageDef(name="FIRST")
    ast.page_windows.append(PageWindowPos(page="FIRST", window="W",
                                          x_cm=1, y_cm=1, width_cm=5, height_cm=3))
    ast.elements.append(ElementBody(window="W", name="E1", language="E",
                                    lines=[ItfLine(tdformat="/:",
                                                   content="BOX FRAME 10 TW")]))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        path = f.name
    render_html(ast, path, page="FIRST", prefer_language="E")
    html = pathlib.Path(path).read_text(encoding="utf-8")
    assert '<div class="box"' in html
    assert "FRAME 10 TW" in html
