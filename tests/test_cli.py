import pathlib

from PIL import Image

from picpic.cli import main
from picpic.db import open_db


def _make(path, size=(64, 64), color=(20, 40, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_cli_scan_then_analyze(tmp_path, capsys):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 30, 30))

    assert main(["scan", str(lib)]) == 0
    assert main(["analyze", str(lib)]) == 0

    conn = open_db(lib / "picpic.db")
    try:
        rows = conn.execute(
            "SELECT is_screenshot, blur_score FROM photos"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    assert all(r["is_screenshot"] is not None for r in rows)
    assert all(r["blur_score"] is not None for r in rows)

    out = capsys.readouterr().out
    assert "added" in out.lower() or "scanned" in out.lower()


def test_cli_unknown_command_returns_nonzero(capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code != 0


def test_cli_scan_nonexistent_library_returns_2(tmp_path, capsys):
    nonexistent = str(tmp_path / "no_such_dir")
    code = main(["scan", nonexistent])
    assert code == 2
    err = capsys.readouterr().err
    assert "not found or not a directory" in err
    # Must not create any files on disk
    assert not (tmp_path / "no_such_dir").exists()


# --- CLIP CLI flag tests (Task 4) ---
import pytest


def test_cli_analyze_no_clip_flag(tmp_path, monkeypatch):
    from picpic.analyze import clip as clip_mod
    from picpic.analyze.clip import ClipReport
    called = {"n": 0}

    def fake_run(*a, **kw):
        called["n"] += 1
        return ClipReport(0, 0, 0, 0)

    monkeypatch.setattr(clip_mod, "clip_available", lambda: True)
    monkeypatch.setattr(clip_mod, "run_clip_pass", fake_run)
    from picpic.cli import main as cli_main
    rc = cli_main(["analyze", str(tmp_path), "--no-clip"])
    assert rc == 0
    assert called["n"] == 0


def test_cli_analyze_clip_only_flag(tmp_path, monkeypatch):
    from picpic.categories import yaml_available
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    from picpic.analyze import clip as clip_mod, exif as exif_mod
    from picpic.analyze.clip import ClipReport
    exif_calls = {"n": 0}

    def fake_exif(_conn):
        exif_calls["n"] += 1
        return 0

    monkeypatch.setattr(clip_mod, "clip_available", lambda: True)
    monkeypatch.setattr(
        clip_mod, "run_clip_pass",
        lambda *a, **kw: ClipReport(0, 0, 0, 0),
    )
    monkeypatch.setattr(exif_mod, "run_exif_pass", fake_exif)
    from picpic.cli import main as cli_main
    rc = cli_main(["analyze", str(tmp_path), "--clip-only"])
    assert rc == 0
    assert exif_calls["n"] == 0


def test_analyze_rejects_no_clip_with_clip_only(tmp_path):
    """argparse's mutually-exclusive group must reject both flags."""
    with pytest.raises(SystemExit) as exc:
        main(["analyze", str(tmp_path), "--no-clip", "--clip-only"])
    assert exc.value.code == 2
