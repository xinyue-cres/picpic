import pathlib

from PIL import Image

from picpic.analyze.runner import analyze_all
from picpic.db import open_db
from picpic.scan import scan_library


def _make(path, size=(64, 64), color=(20, 40, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_analyze_all_runs_every_pass(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 20, 20))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        report = analyze_all(conn)
        rows = conn.execute(
            "SELECT is_screenshot, blur_score, file_hash, phash FROM photos"
        ).fetchall()
    finally:
        conn.close()

    assert report.exif == 2
    assert report.hashes == 2
    assert report.blur == 2
    assert all(
        r["is_screenshot"] is not None
        and r["blur_score"] is not None
        and r["file_hash"] and r["phash"]
        for r in rows
    )


def test_analyze_all_second_run_is_noop(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn)
        second = analyze_all(conn)
    finally:
        conn.close()

    assert second.exif == 0
    assert second.hashes == 0
    assert second.blur == 0
