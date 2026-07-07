import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library
from picpic.thumbs import (
    THUMB_DIRNAME, THUMB_MAX, ensure_thumb, iter_missing_thumbs, thumb_path,
)


def _make(path, size=(1024, 1024)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (100, 150, 200)).save(path, "JPEG")


def test_ensure_thumb_creates_scaled_jpeg(tmp_path):
    lib = tmp_path / "lib"
    src = lib / "big.jpg"
    _make(src, size=(1024, 768))
    out = ensure_thumb(lib, 1, src)
    assert out == thumb_path(lib, 1)
    assert out.exists()
    with Image.open(out) as img:
        w, h = img.size
    assert max(w, h) <= max(THUMB_MAX)
    assert (lib / THUMB_DIRNAME).exists()


def test_ensure_thumb_is_idempotent(tmp_path):
    lib = tmp_path / "lib"
    src = lib / "big.jpg"
    _make(src)
    a = ensure_thumb(lib, 1, src)
    stat_a = a.stat().st_mtime_ns
    b = ensure_thumb(lib, 1, src)
    assert a == b
    assert b.stat().st_mtime_ns == stat_a  # not rewritten


def test_iter_missing_thumbs(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg")

    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        # generate thumb for one of them
        row = conn.execute(
            "SELECT id, path FROM photos ORDER BY id LIMIT 1"
        ).fetchone()
        ensure_thumb(lib, row["id"], pathlib.Path(row["path"]))
        missing = list(iter_missing_thumbs(conn, lib))
    finally:
        conn.close()

    assert len(missing) == 1
