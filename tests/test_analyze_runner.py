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
        report = analyze_all(conn, lib, run_clip=False)
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
        analyze_all(conn, lib, run_clip=False)
        second = analyze_all(conn, lib, run_clip=False)
    finally:
        conn.close()

    assert second.exif == 0
    assert second.hashes == 0
    assert second.blur == 0


# --- CLIP integration tests (Task 4) ---
import pytest

from picpic.analyze import clip as clip_mod
from picpic.analyze.clip import ClipReport, ClipUnavailable
from picpic.categories import yaml_available


def _install_clip_stub(monkeypatch, *, available=True, report=None):
    monkeypatch.setattr(clip_mod, "clip_available", lambda: available)

    def fake_run(conn, library, *, force=False, batch_size=32, progress=None):
        return report or ClipReport(total=0, processed=0, failed=0, skipped=0)

    monkeypatch.setattr(clip_mod, "run_clip_pass", fake_run)


def test_analyze_all_includes_clip_when_available(tmp_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True, report=ClipReport(1, 1, 0, 0))
    report = analyze_all(conn, tmp_path)
    assert report.clip is not None
    assert report.clip.processed == 1


def test_analyze_all_skips_clip_when_unavailable(tmp_path, monkeypatch):
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=False)
    report = analyze_all(conn, tmp_path)
    assert report.clip is None


def test_analyze_all_no_clip_flag(tmp_path, monkeypatch):
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True)
    report = analyze_all(conn, tmp_path, run_clip=False)
    assert report.clip is None


def test_analyze_all_clip_only_skips_others(tmp_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True, report=ClipReport(3, 3, 0, 0))
    report = analyze_all(conn, tmp_path, clip_only=True)
    assert report.exif == 0
    assert report.hashes == 0
    assert report.similar == 0
    assert report.blur == 0
    assert report.clip.processed == 3


def test_analyze_all_isolates_clip_unavailable(tmp_path, tmp_db_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 20, 20))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        monkeypatch.setattr(clip_mod, "clip_available", lambda: True)

        def boom(conn, library, *, force=False, batch_size=32, progress=None):
            raise ClipUnavailable("boom")

        monkeypatch.setattr(clip_mod, "run_clip_pass", boom)
        report = analyze_all(conn, lib, run_clip=True)
    finally:
        conn.close()

    from picpic.analyze.runner import AnalyzeReport

    assert isinstance(report, AnalyzeReport)
    assert report.clip is None
    assert report.exif == 2
    assert report.hashes == 2
    assert report.similar >= 0
    assert report.blur == 2


def test_analyze_all_isolates_runtime_error(tmp_path, tmp_db_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 20, 20))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        monkeypatch.setattr(clip_mod, "clip_available", lambda: True)

        def boom(conn, library, *, force=False, batch_size=32, progress=None):
            raise RuntimeError("cuda oom")

        monkeypatch.setattr(clip_mod, "run_clip_pass", boom)
        report = analyze_all(conn, lib, run_clip=True)
    finally:
        conn.close()

    from picpic.analyze.runner import AnalyzeReport

    assert isinstance(report, AnalyzeReport)
    assert report.clip is None
    assert report.exif == 2
    assert report.hashes == 2
    assert report.blur == 2


def test_analyze_all_isolates_assertion_error(tmp_path, tmp_db_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 20, 20))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        monkeypatch.setattr(clip_mod, "clip_available", lambda: True)

        def boom(conn, library, *, force=False, batch_size=32, progress=None):
            raise AssertionError("text_emb None")

        monkeypatch.setattr(clip_mod, "run_clip_pass", boom)
        report = analyze_all(conn, lib, run_clip=True)
    finally:
        conn.close()

    from picpic.analyze.runner import AnalyzeReport

    assert isinstance(report, AnalyzeReport)
    assert report.clip is None
    assert report.exif == 2
    assert report.hashes == 2
    assert report.blur == 2
