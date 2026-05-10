import pytest

from tools.test_run import _build_free_selinfo


def test_build_free_selinfo_parameters_only():
    out = _build_free_selinfo({"P_DATE": "20260510", "P_FLAG": "X"}, None)
    assert {"SELNAME": "P_DATE", "KIND": "P", "SIGN": "I", "OPTION": "EQ", "LOW": "20260510", "HIGH": ""} in out
    assert {"SELNAME": "P_FLAG", "KIND": "P", "SIGN": "I", "OPTION": "EQ", "LOW": "X", "HIGH": ""} in out
    assert len(out) == 2


def test_build_free_selinfo_select_options_only():
    out = _build_free_selinfo(
        None,
        [
            {"name": "SO_BUKRS", "sign": "I", "option": "EQ", "low": "1000", "high": ""},
            {"name": "SO_BUKRS", "sign": "I", "option": "BT", "low": "2000", "high": "2999"},
            {"name": "SO_DATE", "sign": "E", "option": "EQ", "low": "20260101", "high": ""},
        ],
    )
    bukrs = [r for r in out if r["SELNAME"] == "SO_BUKRS"]
    assert len(bukrs) == 2
    assert bukrs[1]["OPTION"] == "BT"
    assert bukrs[1]["HIGH"] == "2999"
    assert all(r["KIND"] == "S" for r in out)


def test_build_free_selinfo_uppercases_names():
    out = _build_free_selinfo({"p_x": "v"}, [{"name": "so_y", "sign": "I", "option": "EQ", "low": "z", "high": ""}])
    names = [r["SELNAME"] for r in out]
    assert "P_X" in names
    assert "SO_Y" in names


def test_build_free_selinfo_empty_inputs():
    assert _build_free_selinfo(None, None) == []
    assert _build_free_selinfo({}, []) == []
