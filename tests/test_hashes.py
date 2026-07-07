import pathlib

from PIL import Image

from picpic.analyze.hashes import (
    perceptual_hash,
    run_hash_pass,
    sha256_file,
)
from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(64, 64), color=(200, 100, 50)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_sha256_file_stable(tmp_path):
    p = tmp_path / "a.jpg"
    _make_jpeg(p)
    h1 = sha256_file(p)
    h2 = sha256_file(p)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_sha256_differs_on_different_content(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    _make_jpeg(a, color=(255, 0, 0))
    _make_jpeg(b, color=(0, 255, 0))
    assert sha256_file(a) != sha256_file(b)


def test_perceptual_hash_is_hex_16(tmp_path):
    p = tmp_path / "a.jpg"
    _make_jpeg(p)
    h = perceptual_hash(p)
    assert len(h) == 16
    int(h, 16)  # hex parseable


def test_perceptual_hash_similar_for_resized(tmp_path):
    from PIL import Image as _I
    big = tmp_path / "big.jpg"
    small = tmp_path / "small.jpg"
    _I.new("RGB", (512, 512), (100, 100, 100)).save(big, "JPEG")
    _I.open(big).resize((256, 256)).save(small, "JPEG")

    import imagehash
    h1 = imagehash.hex_to_hash(perceptual_hash(big))
    h2 = imagehash.hex_to_hash(perceptual_hash(small))
    assert (h1 - h2) <= 4  # small hamming distance


def test_run_hash_pass_updates_rows(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")
    _make_jpeg(lib / "b.jpg", color=(10, 200, 30))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_hash_pass(conn)
        rows = conn.execute(
            "SELECT file_hash, phash FROM photos"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    assert all(r["file_hash"] and r["phash"] for r in rows)


def test_run_hash_pass_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_hash_pass(conn)
        second = run_hash_pass(conn)
    finally:
        conn.close()

    assert first == 1
    assert second == 0
