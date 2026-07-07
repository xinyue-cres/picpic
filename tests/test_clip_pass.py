from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest

from picpic.categories import CategoriesConfig, Category, yaml_available
from picpic.db import open_db

if not yaml_available():
    pytest.skip("PyYAML not installed", allow_module_level=True)

from picpic.analyze import clip as clip_mod  # noqa: E402


def _seed_photos(conn: sqlite3.Connection, library: pathlib.Path, n: int) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        p = library / f"img_{i}.jpg"
        p.write_bytes(b"stub")
        cur = conn.execute(
            "INSERT INTO photos(path, status) VALUES(?, 'active')", (str(p),)
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def _fixed_cfg() -> CategoriesConfig:
    return CategoriesConfig(
        version=1,
        model="ViT-B-32",
        pretrained="openai",
        top_k=2,
        categories=[
            Category("cat_a", "prompt a"),
            Category("cat_b", "prompt b"),
            Category("cat_c", "prompt c"),
        ],
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cfg: CategoriesConfig | None = None,
    image_scores: list[list[float]] | None = None,
    decode_fail_at: set[int] | None = None,
):
    call_state = {"decode_count": 0}
    scores = image_scores or []
    fail = decode_fail_at or set()

    def fake_load_categories(_library):
        return cfg or _fixed_cfg()

    def fake_load_model(_model, _pretrained):
        return ("FAKE_MODEL", "FAKE_PREPROC", "FAKE_TOKENIZER")

    def fake_encode_text(_bundle, _prompts):
        return "FAKE_TEXT_EMB"

    def fake_encode_image_batch(_bundle, paths):
        out: list[list[float] | None] = []
        for _ in paths:
            idx = call_state["decode_count"]
            call_state["decode_count"] += 1
            if idx in fail:
                out.append(None)
            else:
                out.append(scores[idx])
        return out

    monkeypatch.setattr(clip_mod, "load_categories", fake_load_categories)
    monkeypatch.setattr(clip_mod, "_load_model", fake_load_model)
    monkeypatch.setattr(clip_mod, "_encode_text", fake_encode_text)
    monkeypatch.setattr(clip_mod, "_encode_image_batch", fake_encode_image_batch)


def test_run_clip_pass_writes_labels(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    _install_fakes(
        monkeypatch,
        image_scores=[
            [0.10, 0.60, 0.20, 0.10],  # cat_a wins
            [0.20, 0.15, 0.55, 0.10],  # cat_b wins
        ],
    )
    report = clip_mod.run_clip_pass(conn, tmp_path)
    assert report.total == 2
    assert report.processed == 2
    assert report.failed == 0
    row0 = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    labels0 = json.loads(row0["clip_labels"])
    assert labels0[0]["name"] == "cat_a"
    assert labels0[0]["score"] > 0
    assert len(labels0) <= 2


def test_run_clip_pass_is_idempotent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 1)
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r1 = clip_mod.run_clip_pass(conn, tmp_path)
    assert r1.processed == 1
    r2 = clip_mod.run_clip_pass(conn, tmp_path)
    assert r2.processed == 0
    assert r2.skipped == 1


def test_run_clip_pass_force_reruns(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 1)
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    clip_mod.run_clip_pass(conn, tmp_path)
    # second call with force=True; fakes reset call_state at install time,
    # but the test only creates one row so index 0 is used again
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r = clip_mod.run_clip_pass(conn, tmp_path, force=True)
    assert r.processed == 1
    assert r.skipped == 0


def test_run_clip_pass_decode_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    _install_fakes(
        monkeypatch,
        image_scores=[[0.1, 0.6, 0.2, 0.1], [0.2, 0.3, 0.4, 0.1]],
        decode_fail_at={0},
    )
    report = clip_mod.run_clip_pass(conn, tmp_path)
    assert report.processed == 1
    assert report.failed == 1
    bad = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    assert bad["clip_labels"] == "[]"
    good = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[1],)).fetchone()
    labels = json.loads(good["clip_labels"])
    assert labels


def test_run_clip_pass_all_below_baseline(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 1)
    _install_fakes(
        monkeypatch,
        image_scores=[[0.9, 0.02, 0.03, 0.05]],  # baseline dominates
    )
    clip_mod.run_clip_pass(conn, tmp_path)
    row = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    assert row["clip_labels"] == "[]"


def test_run_clip_pass_batching(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 5)
    scores = [[0.1, 0.6, 0.2, 0.1]] * 5
    _install_fakes(monkeypatch, image_scores=scores)
    progress_calls: list[tuple[int, int]] = []
    r = clip_mod.run_clip_pass(
        conn, tmp_path, batch_size=2,
        progress=lambda d, t: progress_calls.append((d, t)),
    )
    assert r.processed == 5
    assert len(progress_calls) == 3  # 2 + 2 + 1
    assert progress_calls[-1] == (5, 5)


def test_run_clip_pass_skips_trashed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    conn.execute("UPDATE photos SET status='trashed' WHERE id=?", (ids[1],))
    conn.commit()
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r = clip_mod.run_clip_pass(conn, tmp_path)
    assert r.total == 1
    assert r.processed == 1
    trashed = conn.execute(
        "SELECT clip_labels FROM photos WHERE id=?", (ids[1],)
    ).fetchone()
    assert trashed["clip_labels"] is None


def test_clip_available_flag() -> None:
    assert isinstance(clip_mod.clip_available(), bool)
