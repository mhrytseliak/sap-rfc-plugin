from tools.text_pool import _to_external, _to_textpool, _merge, _SEL_PREFIX


def test_to_external_strips_sel_prefix():
    raw = [
        {"ID": "R", "KEY": "", "ENTRY": "Report Title", "LENGTH": 12},
        {"ID": "I", "KEY": "001", "ENTRY": "Hello", "LENGTH": 5},
        {"ID": "S", "KEY": "P_BUKRS  ", "ENTRY": _SEL_PREFIX + "Company Code", "LENGTH": 20},
    ]
    out = _to_external(raw)
    assert out[0] == {"id": "R", "key": "", "entry": "Report Title", "length": 12}
    assert out[1] == {"id": "I", "key": "001", "entry": "Hello", "length": 5}
    assert out[2]["entry"] == "Company Code"
    assert out[2]["key"] == "P_BUKRS"


def test_to_external_keeps_s_entry_when_no_prefix():
    out = _to_external([{"ID": "S", "KEY": "X", "ENTRY": "no prefix", "LENGTH": 9}])
    assert out[0]["entry"] == "no prefix"


def test_to_textpool_adds_sel_prefix_and_computes_length():
    out = _to_textpool([
        {"id": "r", "key": "", "entry": "Title"},
        {"id": "i", "key": "001", "entry": "Sym"},
        {"id": "s", "key": "p_x", "entry": "Sel"},
    ])
    assert out[0] == {"ID": "R", "KEY": "", "ENTRY": "Title", "LENGTH": 5}
    assert out[1] == {"ID": "I", "KEY": "001", "ENTRY": "Sym", "LENGTH": 3}
    assert out[2]["ID"] == "S"
    assert out[2]["KEY"] == "P_X"
    assert out[2]["ENTRY"] == _SEL_PREFIX + "Sel"
    assert out[2]["LENGTH"] == len(_SEL_PREFIX) + 3


def test_merge_replaces_matching_and_appends_new():
    current = [
        {"ID": "R", "KEY": "", "ENTRY": "Old Title", "LENGTH": 9},
        {"ID": "I", "KEY": "001", "ENTRY": "Old", "LENGTH": 3},
    ]
    incoming = [
        {"ID": "I", "KEY": "001", "ENTRY": "New", "LENGTH": 3},
        {"ID": "I", "KEY": "002", "ENTRY": "Added", "LENGTH": 5},
    ]
    merged, added, replaced = _merge(current, incoming)
    assert added == 1
    assert replaced == 1
    assert merged[0]["ENTRY"] == "Old Title"
    assert merged[1]["ENTRY"] == "New"
    assert merged[2]["KEY"] == "002"
    assert merged[2]["ENTRY"] == "Added"


def test_merge_preserves_original_order():
    current = [
        {"ID": "I", "KEY": "003", "ENTRY": "C", "LENGTH": 1},
        {"ID": "I", "KEY": "001", "ENTRY": "A", "LENGTH": 1},
    ]
    incoming = [{"ID": "I", "KEY": "001", "ENTRY": "AA", "LENGTH": 2}]
    merged, _, _ = _merge(current, incoming)
    assert [r["KEY"] for r in merged] == ["003", "001"]
    assert merged[1]["ENTRY"] == "AA"
