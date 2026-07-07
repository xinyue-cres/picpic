import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library
from picpic.trash import (
    TRASH_DIRNAME, purge_trash, restore_photos, trash_photos,
)


def _make(path, color=(50, 50, 50)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path, "JPEG")


def _ids(conn):
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM photos ORDER BY id"
        ).fetchall()
    ]


def test_trash_photos_moves_and_marks(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 30, 30))
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        # Find id for a.jpg specifically (filesystem order varies by OS)
        a_row = conn.execute(
            "SELECT id FROM photos WHERE path LIKE '%/a.jpg'"
        ).fetchone()
        a_id = a_row["id"]
        moved = trash_photos(conn, lib, [a_id], now="2026-07-06T00:00:00")
        row = conn.execute(
            "SELECT status, trashed_at FROM photos WHERE id=?", (a_id,)
        ).fetchone()
    finally:
        conn.close()

    assert moved == 1
    assert row["status"] == "trashed"
    assert row["trashed_at"] == "2026-07-06T00:00:00"
    assert not (lib / "a.jpg").exists()
    trash_dir = lib / TRASH_DIRNAME
    assert trash_dir.exists()
    moved_files = list(trash_dir.iterdir())
    assert len(moved_files) == 1
    assert moved_files[0].name.startswith(f"{a_id}__")


def test_trash_skips_already_trashed(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        again = trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
    finally:
        conn.close()
    assert again == 0


def test_restore_moves_back(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        restored = restore_photos(conn, lib, ids)
        row = conn.execute(
            "SELECT status, trashed_at FROM photos WHERE id=?", (ids[0],)
        ).fetchone()
    finally:
        conn.close()

    assert restored == 1
    assert row["status"] == "active"
    assert row["trashed_at"] is None
    assert (lib / "a.jpg").exists()


def test_purge_deletes_files_and_rows(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(10, 200, 10))
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        n = purge_trash(conn, lib)
        remaining = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    finally:
        conn.close()

    assert n == 2
    assert remaining == 0
    trash_dir = lib / TRASH_DIRNAME
    assert list(trash_dir.iterdir()) == []
