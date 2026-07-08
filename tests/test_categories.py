from __future__ import annotations

import pathlib

import pytest

from picpic.categories import (
    CATEGORIES_FILENAME,
    CategoriesError,
    check_categories,
    load_categories,
    write_default,
    yaml_available,
)

pytestmark = pytest.mark.skipif(
    not yaml_available(), reason="PyYAML not installed"
)


def test_write_default_creates_file(tmp_path: pathlib.Path) -> None:
    path = write_default(tmp_path)
    assert path == tmp_path / CATEGORIES_FILENAME
    assert path.exists()


def test_write_default_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    with pytest.raises(FileExistsError):
        write_default(tmp_path)


def test_load_default_template(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    cfg = load_categories(tmp_path)
    assert cfg.version == 1
    assert cfg.model == "ViT-B-32"
    assert cfg.pretrained == "openai"
    assert cfg.top_k == 3
    assert len(cfg.categories) >= 3
    names = [c.name for c in cfg.categories]
    assert len(names) == len(set(names))  # unique


def test_load_missing_file_raises(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_categories(tmp_path)


def _write(tmp_path: pathlib.Path, body: str) -> None:
    (tmp_path / CATEGORIES_FILENAME).write_text(body, encoding="utf-8")


def test_load_rejects_wrong_version(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 2\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n  - {name: a, prompt: b}\n")
    with pytest.raises(CategoriesError, match="version"):
        load_categories(tmp_path)


def test_load_rejects_empty_categories(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories: []\n")
    with pytest.raises(CategoriesError, match="categories"):
        load_categories(tmp_path)


def test_load_rejects_duplicate_names(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {name: a, prompt: p1}\n"
        "  - {name: a, prompt: p2}\n",
    )
    with pytest.raises(CategoriesError, match="duplicate"):
        load_categories(tmp_path)


def test_load_rejects_empty_prompt(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {name: a, prompt: ''}\n",
    )
    with pytest.raises(CategoriesError, match="prompt"):
        load_categories(tmp_path)


def test_load_rejects_missing_name(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {prompt: hello}\n",
    )
    with pytest.raises(CategoriesError, match="name"):
        load_categories(tmp_path)


def test_load_rejects_top_k_out_of_range(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 5\ncategories:\n"
        "  - {name: a, prompt: p}\n"
        "  - {name: b, prompt: q}\n",
    )
    with pytest.raises(CategoriesError, match="top_k"):
        load_categories(tmp_path)


def test_check_ok_on_default(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    assert check_categories(tmp_path) == []


def test_check_lists_problems(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 2\ncategories: []\n")
    problems = check_categories(tmp_path)
    assert problems  # non-empty


def test_reserved_name_未分类_rejected(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {name: 未分类, prompt: p}\n",
    )
    with pytest.raises(CategoriesError, match="reserved"):
        load_categories(tmp_path)
