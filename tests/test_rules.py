import pathlib

from PIL import Image

from picpic.analyze.runner import analyze_all
from picpic.db import open_db
from picpic.rules import apply_rules, DEFAULT_BLUR_THRESHOLD
from picpic.scan import scan_library


def _make(path, size=(400, 400), color=(80, 80, 80)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def _make_screenshot(path):
    _make(path, size=(1170, 2532), color=(30, 30, 30))


def test_screenshot_becomes_candidate(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_screenshot(lib / "s.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn, lib, run_clip=False)
        report = apply_rules(conn)
        row = conn.execute(
            "SELECT verdict, verdict_reason FROM photos"
        ).fetchone()
    finally:
        conn.close()

    assert row["verdict"] == "trash_candidate"
    assert row["verdict_reason"] == "screenshot"
    assert report.candidates == 1
    assert report.by_reason["screenshot"] == 1


def test_similar_group_is_not_auto_candidate(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg", color=(180, 20, 20))
    from PIL import Image as I
    I.open(lib / "a.jpg").resize((200, 200)).save(lib / "a2.jpg", "JPEG")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn, lib, run_clip=False)
        # give both photos an EXIF camera model to escape screenshot rule
        # and set blur_score above threshold to escape blur rule:
        conn.execute(
            "UPDATE photos SET camera_model='Canon', is_screenshot=0, "
            "blur_score=?", (DEFAULT_BLUR_THRESHOLD * 10,)
        )
        conn.commit()
        apply_rules(conn)
        rows = conn.execute(
            "SELECT verdict, dup_group FROM photos"
        ).fetchall()
    finally:
        conn.close()

    for r in rows:
        assert r["dup_group"] is not None
        # similar pairs stay 'keep' — spec: never auto-mark similar groups
        assert r["verdict"] == "keep"


def test_exact_dup_marks_extras(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    src = lib / "a.jpg"
    _make(src, color=(10, 200, 30))
    dup = lib / "sub" / "a_copy.jpg"
    dup.parent.mkdir(parents=True, exist_ok=True)
    dup.write_bytes(src.read_bytes())

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn, lib, run_clip=False)
        conn.execute(
            "UPDATE photos SET camera_model='Canon', is_screenshot=0, "
            "blur_score=?", (DEFAULT_BLUR_THRESHOLD * 10,)
        )
        conn.commit()
        apply_rules(conn)
        rows = conn.execute(
            "SELECT id, path, verdict, verdict_reason "
            "FROM photos ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    verdicts = [r["verdict"] for r in rows]
    reasons = [r["verdict_reason"] for r in rows]
    assert verdicts.count("keep") == 1
    assert verdicts.count("trash_candidate") == 1
    assert reasons[0] is None or reasons[0] == ""  # kept row
    assert reasons[1] == "exact_dup"


def test_apply_rules_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_screenshot(lib / "s.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn, lib, run_clip=False)
        first = apply_rules(conn)
        second = apply_rules(conn)
    finally:
        conn.close()

    assert first.candidates == second.candidates == 1


def test_apply_rules_warns_unanalyzed(tmp_path, tmp_db_path):
    """Running rules on a scanned-but-not-analyzed DB reports unanalyzed > 0."""
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 30, 30))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        # Do NOT run analyze_all — photos are unanalyzed
        report = apply_rules(conn)
    finally:
        conn.close()

    assert report.unanalyzed == 2
