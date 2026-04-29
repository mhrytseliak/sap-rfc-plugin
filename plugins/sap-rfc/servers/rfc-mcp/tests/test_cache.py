from pathlib import Path
import cache


def test_write_returns_path_and_line_count(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    out = cache.write_source("ZTEST", "line1\nline2\nline3")
    assert out["line_count"] == 3
    assert Path(out["source_file"]).exists()
    assert Path(out["source_file"]).read_text(encoding="utf-8") == "line1\nline2\nline3"


def test_write_sanitises_name(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    out = cache.write_source("CL_FOO.METHOD", "x")
    assert Path(out["source_file"]).name == "CL_FOO.METHOD.abap"


def test_cache_dir_function(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    assert cache.cache_dir() == tmp_path


def test_cache_copy_bytes(tmp_path, monkeypatch):
    src = tmp_path / "src.bin"
    src.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    cache.CACHE_DIR.mkdir()
    dst = cache.cache_copy(src, "foo.FOR")
    from pathlib import Path
    assert Path(dst).read_bytes() == b"\x89PNG\r\n\x1a\nfake"
    assert Path(dst).name == "foo.FOR"
