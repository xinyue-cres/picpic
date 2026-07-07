import pathlib

from PIL import Image, ImageDraw

from picpic.analyze.hashes import run_hash_pass
from picpic.analyze.similar import HAMMING_THRESHOLD, run_similarity_pass
from picpic.db import open_db
from picpic.scan import scan_library


def _make(path, size=(64, 64), color=(0, 0, 0)):
    # phash of a perfectly-uniform image is degenerate (all AC=0, same hash for
    # any color), so paint a small central spot in the inverse color to give
    # phash real color-dependent signal that survives resizing.
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    inv = tuple(255 - c for c in color)
    w, h = size
    cx, cy = w // 2, h // 2
    r = max(1, min(w, h) // 8)
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=inv)
    img.save(path, "JPEG")


def test_similarity_groups_near_duplicates(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    # a.jpg and a2.jpg are the same image at different sizes
    _make(lib / "a.jpg", size=(400, 400), color=(180, 20, 20))
    from PIL import Image as I
    I.open(lib / "a.jpg").resize((200, 200)).save(lib / "a2.jpg", "JPEG")
    _make(lib / "b.jpg", size=(400, 400), color=(10, 200, 30))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        run_hash_pass(conn)
        placed = run_similarity_pass(conn)
        rows = conn.execute(
            "SELECT path, dup_group FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    by_name = {pathlib.Path(r["path"]).name: r["dup_group"] for r in rows}
    assert by_name["a.jpg"] is not None
    assert by_name["a.jpg"] == by_name["a2.jpg"]
    assert by_name["b.jpg"] is None
    assert placed == 2


def test_similarity_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make(lib / "solo.jpg", color=(1, 2, 3))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        run_hash_pass(conn)
        first = run_similarity_pass(conn)
        second = run_similarity_pass(conn)
        row = conn.execute(
            "SELECT dup_group FROM photos"
        ).fetchone()
    finally:
        conn.close()

    assert first == 0
    assert second == 0
    assert row["dup_group"] is None


def test_threshold_default_is_six():
    assert HAMMING_THRESHOLD == 6
