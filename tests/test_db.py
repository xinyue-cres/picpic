import sqlite3
import pathlib

import pytest

from picpic.db import open_db, SCHEMA_VERSION


def test_open_db_creates_schema(tmp_db_path: pathlib.Path):
    conn = open_db(tmp_db_path)
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "photos" in tables
        assert "meta" in tables

        cur = conn.execute("PRAGMA table_info(photos)")
        cols = {row[1] for row in cur.fetchall()}
        expected = {
            "id", "path", "file_hash", "phash", "width", "height",
            "file_size", "created_at", "camera_model",
            "is_screenshot", "blur_score", "dup_group", "clip_labels",
            "verdict", "verdict_reason", "status", "trashed_at",
        }
        assert expected.issubset(cols)

        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(version) == SCHEMA_VERSION
    finally:
        conn.close()


def test_open_db_is_idempotent(tmp_db_path: pathlib.Path):
    open_db(tmp_db_path).close()
    conn = open_db(tmp_db_path)
    try:
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(version) == SCHEMA_VERSION
    finally:
        conn.close()


def test_open_db_row_factory_is_row(tmp_db_path: pathlib.Path):
    conn = open_db(tmp_db_path)
    try:
        row = conn.execute("SELECT 1 AS x").fetchone()
        assert row["x"] == 1
    finally:
        conn.close()


def test_verdict_check_constraint(tmp_db_path: pathlib.Path):
    conn = open_db(tmp_db_path)
    try:
        conn.execute("INSERT INTO photos (path) VALUES (?)", ("/a.jpg",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE photos SET verdict='bogus' WHERE path=?", ("/a.jpg",)
            )
    finally:
        conn.close()
