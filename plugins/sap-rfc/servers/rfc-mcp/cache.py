import shutil
import tempfile
from pathlib import Path

CACHE_DIR = Path(tempfile.gettempdir()) / "sap-rfc-cache"
CACHE_DIR.mkdir(exist_ok=True)


def cache_dir() -> Path:
    """Return the cache directory. Tests may monkeypatch CACHE_DIR."""
    return CACHE_DIR


def cache_copy(src_path, dest_name: str) -> str:
    """Copy an arbitrary file into the cache dir under dest_name. Return path."""
    dst = CACHE_DIR / dest_name
    shutil.copyfile(str(src_path), str(dst))
    return str(dst)


def write_source(name: str, source: str) -> dict:
    """Write source code to cache and return path + line count."""
    path = CACHE_DIR / f"{name}.abap"
    path.write_text(source, encoding="utf-8")
    line_count = source.count("\n") + 1 if source else 0
    return {"source_file": str(path), "line_count": line_count}
