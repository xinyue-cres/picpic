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
