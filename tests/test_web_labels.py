from __future__ import annotations

import json
import pathlib

import pytest
from httpx2 import ASGITransport, AsyncClient

from picpic.db import open_db
from picpic.web.app import create_app


UNCLASSIFIED = "未分类"


def _seed(conn, path, labels):
    cur = conn.execute(
        "INSERT INTO photos(path, status, clip_labels) VALUES(?, 'active', ?)",
        (path, json.dumps(labels)),
    )
    conn.commit()
    return cur.lastrowid


def _seed_null(conn, path):
    cur = conn.execute(
        "INSERT INTO photos(path, status, clip_labels) VALUES(?, 'active', NULL)",
        (path,),
    )
    conn.commit()
    return cur.lastrowid


async def _get(app, url):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as ac:
        return await ac.get(url)


@pytest.mark.anyio
async def test_labels_no_categories_yml(tmp_path: pathlib.Path) -> None:
    open_db(tmp_path / "picpic.db").close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/labels")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False


@pytest.mark.anyio
async def test_labels_counts_top1_per_category(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    _seed(conn, str(tmp_path / "b.jpg"),
          [{"name": "收据", "score": 0.5}, {"name": "文档", "score": 0.4}])
    _seed(conn, str(tmp_path / "c.jpg"), [])
    _seed(conn, str(tmp_path / "d.jpg"), [{"name": "食物", "score": 0.15}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/labels?min_score=0.25")
    body = r.json()
    assert body["available"] is True
    counts = {c["name"]: c["count"] for c in body["categories"]}
    assert counts["收据"] == 2
    assert counts.get("食物", 0) == 0
    assert body["unclassified_count"] == 2  # c + d


@pytest.mark.anyio
async def test_photos_labeled_filter(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    id_a = _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    id_b = _seed(conn, str(tmp_path / "b.jpg"), [{"name": "收据", "score": 0.5}])
    _seed(conn, str(tmp_path / "c.jpg"), [{"name": "食物", "score": 0.7}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/photos?tab=labeled&label=收据&min_score=0.25")
    ids = [p["id"] for p in r.json()["photos"]]
    assert ids == [id_a, id_b]


@pytest.mark.anyio
async def test_photos_labeled_unclassified(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    id_b = _seed(conn, str(tmp_path / "b.jpg"), [])
    id_c = _seed(conn, str(tmp_path / "c.jpg"), [{"name": "食物", "score": 0.1}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(
        app, f"/api/photos?tab=labeled&label={UNCLASSIFIED}&min_score=0.25"
    )
    ids = {p["id"] for p in r.json()["photos"]}
    assert ids == {id_b, id_c}


@pytest.mark.anyio
async def test_photos_dict_includes_clip_labels(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/photos?tab=labeled&label=收据&min_score=0.25")
    p = r.json()["photos"][0]
    assert p["top_label"]["name"] == "收据"
    assert p["clip_labels"][0]["score"] == 0.9


@pytest.mark.anyio
async def test_labels_null_clip_labels_counted_unclassified(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    _seed_null(conn, str(tmp_path / "b.jpg"))
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/labels?min_score=0.25")
    data = r.json()
    assert data["available"] is True
    assert data["unclassified_count"] >= 1


@pytest.mark.anyio
async def test_photos_labeled_unclassified_includes_null(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    id_empty = _seed(conn, str(tmp_path / "b.jpg"), [])
    id_below = _seed(conn, str(tmp_path / "c.jpg"), [{"name": "食物", "score": 0.1}])
    id_null = _seed_null(conn, str(tmp_path / "d.jpg"))
    conn.close()
    app = create_app(tmp_path)
    r = await _get(
        app, f"/api/photos?tab=labeled&label={UNCLASSIFIED}&min_score=0.25"
    )
    ids = {p["id"] for p in r.json()["photos"]}
    assert ids == {id_empty, id_below, id_null}


def test_labels_tab_button_in_html() -> None:
    from picpic.web.app import _STATIC_DIR
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="labeled"' in html
    assert "标签" in html


def test_labels_controls_in_html() -> None:
    from picpic.web.app import _STATIC_DIR
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="label-select"' in html
    assert 'id="min-score"' in html
