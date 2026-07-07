import pathlib

from PIL import Image
from fastapi.testclient import TestClient

from picpic.analyze.runner import analyze_all
from picpic.db import open_db
from picpic.rules import apply_rules
from picpic.scan import scan_library
from picpic.web.app import create_app


def _make_screenshot(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1170, 2532), (0, 0, 0)).save(path, "JPEG")


def _make_photo(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 400), (200, 30, 30)).save(path, "JPEG")


def _prep(library):
    conn = open_db(library / "picpic.db")
    try:
        scan_library(library, conn)
        analyze_all(conn)
        apply_rules(conn)
    finally:
        conn.close()


def test_candidates_endpoint(tmp_path):
    lib = tmp_path / "lib"
    _make_screenshot(lib / "s.jpg")
    _make_photo(lib / "p.jpg")
    _prep(lib)

    app = create_app(lib)
    client = TestClient(app)

    r = client.get("/api/photos", params={"tab": "candidates"})
    assert r.status_code == 200
    photos = r.json()["photos"]
    assert len(photos) >= 1
    assert all(p["verdict"] == "trash_candidate" for p in photos)


def test_thumb_endpoint_returns_jpeg(tmp_path):
    lib = tmp_path / "lib"
    _make_photo(lib / "p.jpg")
    _prep(lib)

    app = create_app(lib)
    client = TestClient(app)

    photo_id = client.get(
        "/api/photos", params={"tab": "candidates"}
    ).json()["photos"]
    if not photo_id:  # nothing became a candidate; grab any row
        conn = open_db(lib / "picpic.db")
        try:
            row = conn.execute("SELECT id FROM photos LIMIT 1").fetchone()
        finally:
            conn.close()
        pid = row["id"]
    else:
        pid = photo_id[0]["id"]

    r = client.get(f"/thumb/{pid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert len(r.content) > 100


def test_trash_and_restore_roundtrip(tmp_path):
    lib = tmp_path / "lib"
    _make_photo(lib / "a.jpg")
    _prep(lib)

    conn = open_db(lib / "picpic.db")
    try:
        pid = conn.execute("SELECT id FROM photos").fetchone()["id"]
    finally:
        conn.close()

    app = create_app(lib)
    client = TestClient(app)

    r = client.post("/api/trash", json={"ids": [pid]})
    assert r.status_code == 200
    assert r.json()["moved"] == 1

    r = client.get("/api/photos", params={"tab": "trashed"})
    assert any(p["id"] == pid for p in r.json()["photos"])

    r = client.post("/api/restore", json={"ids": [pid]})
    assert r.json()["restored"] == 1


def test_purge_deletes(tmp_path):
    lib = tmp_path / "lib"
    _make_photo(lib / "a.jpg")
    _prep(lib)
    conn = open_db(lib / "picpic.db")
    try:
        pid = conn.execute("SELECT id FROM photos").fetchone()["id"]
    finally:
        conn.close()

    app = create_app(lib)
    client = TestClient(app)
    client.post("/api/trash", json={"ids": [pid]})
    r = client.post("/api/purge", json={})
    assert r.status_code == 200
    assert r.json()["deleted"] == 1


def test_rules_endpoint_reruns(tmp_path):
    lib = tmp_path / "lib"
    _make_photo(lib / "a.jpg")
    _prep(lib)
    app = create_app(lib)
    client = TestClient(app)
    r = client.post("/api/rules", json={"blur_threshold": 0.0})
    assert r.status_code == 200
    body = r.json()
    assert "kept" in body and "candidates" in body
