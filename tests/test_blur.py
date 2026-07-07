import pathlib

import cv2
import numpy as np
from PIL import Image, ImageFilter

from picpic.analyze.blur import laplacian_variance, run_blur_pass
from picpic.db import open_db
from picpic.scan import scan_library


def _make_sharp(path, size=(200, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[::4, :, :] = 255  # sharp horizontal stripes
    Image.fromarray(arr).save(path, "JPEG", quality=95)


def _make_blurry(path, size=(200, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[::4, :, :] = 255
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(radius=8))
    img.save(path, "JPEG", quality=95)


def test_laplacian_variance_higher_for_sharp(tmp_path):
    sharp = tmp_path / "sharp.jpg"
    blurry = tmp_path / "blur.jpg"
    _make_sharp(sharp)
    _make_blurry(blurry)
    assert laplacian_variance(sharp) > laplacian_variance(blurry)


def test_run_blur_pass_writes_scores(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_sharp(lib / "s.jpg")
    _make_blurry(lib / "b.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_blur_pass(conn)
        rows = conn.execute(
            "SELECT path, blur_score FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    assert all(r["blur_score"] is not None for r in rows)
    scores = {pathlib.Path(r["path"]).name: r["blur_score"] for r in rows}
    assert scores["s.jpg"] > scores["b.jpg"]


def test_run_blur_pass_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_sharp(lib / "a.jpg")
    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_blur_pass(conn)
        second = run_blur_pass(conn)
    finally:
        conn.close()
    assert first == 1
    assert second == 0
