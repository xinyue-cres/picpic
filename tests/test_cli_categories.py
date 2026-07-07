from __future__ import annotations

import pathlib

import pytest

from picpic.categories import CATEGORIES_FILENAME, yaml_available
from picpic.cli import main

pytestmark = pytest.mark.skipif(
    not yaml_available(), reason="PyYAML not installed"
)


def test_categories_init_writes_file(tmp_path: pathlib.Path) -> None:
    rc = main(["categories", str(tmp_path), "--init"])
    assert rc == 0
    assert (tmp_path / CATEGORIES_FILENAME).exists()


def test_categories_init_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    main(["categories", str(tmp_path), "--init"])
    rc = main(["categories", str(tmp_path), "--init"])
    assert rc != 0


def test_categories_list_prints_entries(tmp_path: pathlib.Path, capsys) -> None:
    main(["categories", str(tmp_path), "--init"])
    capsys.readouterr()  # clear
    rc = main(["categories", str(tmp_path), "--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "收据" in out


def test_categories_check_reports_ok(tmp_path: pathlib.Path, capsys) -> None:
    main(["categories", str(tmp_path), "--init"])
    capsys.readouterr()
    rc = main(["categories", str(tmp_path), "--check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()


def test_categories_check_reports_missing(tmp_path: pathlib.Path, capsys) -> None:
    rc = main(["categories", str(tmp_path), "--check"])
    assert rc != 0
    captured = capsys.readouterr()
    haystack = (captured.out + captured.err).lower()
    assert "not found" in haystack or CATEGORIES_FILENAME.lower() in haystack


def test_categories_requires_one_flag(tmp_path: pathlib.Path) -> None:
    rc = main(["categories", str(tmp_path)])
    assert rc != 0
