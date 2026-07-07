import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(16, 16), color=(255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_scan_registers_supported_files(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")
    _make_jpeg(lib / "sub" / "b.jpeg")
    _make_jpeg(lib / "c.png")
    (lib / "notes.txt").write_text("hi")

    conn = open_db(tmp_db_path)
    try:
        report = scan_library(lib, conn)
        rows = conn.execute(
            "SELECT path, status, file_size FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert report.added == 3
    assert report.skipped == 1  # notes.txt
    paths = [r["path"] for r in rows]
    assert all(p.endswith((".jpg", ".jpeg", ".png")) for p in paths)
    assert all(r["status"] == "active" for r in rows)
    assert all(r["file_size"] > 0 for r in rows)


def test_scan_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")

    conn = open_db(tmp_db_path)
    try:
        first = scan_library(lib, conn)
        second = scan_library(lib, conn)
        count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    finally:
        conn.close()

    assert first.added == 1
    assert second.added == 0
    assert second.already_present == 1
    assert count == 1


def test_scan_ignores_trash_and_thumbs_and_dotfiles(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "keep.jpg")
    _make_jpeg(lib / "_picpic_trash" / "gone.jpg")
    _make_jpeg(lib / ".picpic_thumbs" / "cache.jpg")
    _make_jpeg(lib / ".hidden.jpg")

    conn = open_db(tmp_db_path)
    try:
        report = scan_library(lib, conn)
        paths = [
            r["path"]
            for r in conn.execute("SELECT path FROM photos").fetchall()
        ]
    finally:
        conn.close()

    assert report.added == 1
    assert paths[0].endswith("keep.jpg")


def test_scan_rejects_symlink_outside_library(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    outside = tmp_path / "outside.jpg"
    _make_jpeg(outside)
    # Create a symlink inside the library pointing outside
    (lib / "escape.jpg").symlink_to(outside)
    # Also add a legitimate file
    _make_jpeg(lib / "legit.jpg")

    conn = open_db(tmp_db_path)
    try:
        report = scan_library(lib, conn)
        paths = [
            r["path"]
            for r in conn.execute("SELECT path FROM photos").fetchall()
        ]
    finally:
        conn.close()

    assert report.added == 1
    assert report.skipped == 1  # the symlink
    assert all("outside.jpg" not in p for p in paths)
    assert any("legit.jpg" in p for p in paths)
