import pathlib

from PIL import Image

from picpic.analyze.exif import (
    ExifInfo,
    is_screenshot,
    read_exif,
    run_exif_pass,
    SCREEN_RESOLUTIONS,
)
from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(16, 16), color=(0, 128, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_read_exif_no_metadata_returns_none_camera(tmp_path):
    p = tmp_path / "plain.jpg"
    _make_jpeg(p, size=(400, 300))
    info = read_exif(p)
    assert info.width == 400 and info.height == 300
    assert info.camera_model is None
    assert info.created_at is None


def test_is_screenshot_flags_missing_camera():
    info = ExifInfo(width=800, height=600, camera_model=None, created_at=None)
    assert is_screenshot(info) is True


def test_is_screenshot_flags_screen_resolution_even_with_camera():
    assert (1170, 2532) in SCREEN_RESOLUTIONS
    info = ExifInfo(
        width=1170, height=2532, camera_model="iPhone 13", created_at=None
    )
    assert is_screenshot(info) is True


def test_is_screenshot_negative_case():
    info = ExifInfo(
        width=4032, height=3024, camera_model="iPhone 13", created_at=None
    )
    assert is_screenshot(info) is False


def test_run_exif_pass_updates_db(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "shot.jpg", size=(1170, 2532))
    _make_jpeg(lib / "photo.jpg", size=(4032, 3024))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_exif_pass(conn)
        rows = conn.execute(
            "SELECT path, is_screenshot, width, height FROM photos "
            "ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    by_name = {pathlib.Path(r["path"]).name: r for r in rows}
    assert by_name["shot.jpg"]["is_screenshot"] == 1
    assert by_name["photo.jpg"]["is_screenshot"] == 1  # no camera EXIF written by PIL default → treated as screenshot
    assert by_name["shot.jpg"]["width"] == 1170


def test_run_exif_pass_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg", size=(4032, 3024))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_exif_pass(conn)
        second = run_exif_pass(conn)
    finally:
        conn.close()

    assert first == 1
    assert second == 0  # nothing left with is_screenshot IS NULL
