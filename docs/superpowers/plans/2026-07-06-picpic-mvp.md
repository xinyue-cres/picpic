# picpic Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, privacy-preserving photo cleanup tool: CLI pipeline (scan → analyze → rules) + local web UI to review candidates and move them to a reversible trash. Phase 1 handles duplicates, blur, and screenshots. No CLIP.

**Architecture:** Python CLI writes to a single SQLite DB (source of truth). Detectors are independent and idempotent — each writes its own columns. A rules step turns detector outputs into per-photo verdicts. FastAPI serves a single-page UI reading the same DB. "Delete" moves files to `_picpic_trash/` and flips a status bit; purge is a separate confirmed step.

**Tech Stack:** Python 3.12, SQLite (stdlib `sqlite3`), Pillow, imagehash, opencv-python-headless, FastAPI + uvicorn, vanilla JS single-page frontend, pytest.

## Global Constraints

- Python 3.12+ (matches user's `python3 --version`).
- Originals are read-only for the entire lifecycle. No code path may write, rename, or delete an original file. "Delete" = move to `_picpic_trash/`.
- SQLite is the single source of truth. UI never scans the filesystem for photo state.
- All processing is local — no network calls, no telemetry.
- Package name: `picpic`. CLI entry point: `picpic` (installed as a console script).
- Database default location: `<library-root>/picpic.db`. Trash default: `<library-root>/_picpic_trash/`. Thumbnails default: `<library-root>/.picpic_thumbs/`.
- Verdicts: exactly `keep` or `trash_candidate`. Statuses: exactly `active` or `trashed`.
- Verdict reasons in Phase 1: exactly `screenshot`, `blurry`, `exact_dup`. (Similar-group photos never get a `trash_candidate` verdict — they're only grouped for manual review.)

---

## File Structure

```
picpic/
├── pyproject.toml                          # Task 1
├── src/picpic/
│   ├── __init__.py                         # Task 1
│   ├── cli.py                              # Task 9  (argparse entry)
│   ├── db.py                               # Task 2  (schema + connection)
│   ├── scan.py                             # Task 3  (walk fs, register rows)
│   ├── analyze/
│   │   ├── __init__.py                     # Task 4
│   │   ├── exif.py                         # Task 4  (screenshot detector)
│   │   ├── hashes.py                       # Task 5  (file_hash + phash + exact-dup grouping)
│   │   ├── similar.py                      # Task 6  (phash → dup_group)
│   │   ├── blur.py                         # Task 7  (Laplacian variance)
│   │   └── runner.py                       # Task 8  (orchestrates detectors)
│   ├── rules.py                            # Task 10 (verdicts from detector output)
│   ├── trash.py                            # Task 11 (move to/from trash, purge)
│   ├── thumbs.py                           # Task 12 (thumbnail generation + cache)
│   └── web/
│       ├── __init__.py                     # Task 13
│       ├── app.py                          # Task 13 (FastAPI app + routes)
│       └── static/
│           ├── index.html                  # Task 14
│           ├── app.js                      # Task 14
│           └── style.css                   # Task 14
└── tests/
    ├── conftest.py                         # Task 2
    ├── fixtures/                           # Task 3 (test images)
    ├── test_db.py                          # Task 2
    ├── test_scan.py                        # Task 3
    ├── test_exif.py                        # Task 4
    ├── test_hashes.py                      # Task 5
    ├── test_similar.py                     # Task 6
    ├── test_blur.py                        # Task 7
    ├── test_analyze_runner.py              # Task 8
    ├── test_cli.py                         # Task 9
    ├── test_rules.py                       # Task 10
    ├── test_trash.py                       # Task 11
    ├── test_thumbs.py                      # Task 12
    └── test_web.py                         # Task 13
```

**Design notes:**
- Each detector is one file, one responsibility, one column set. They're independent — you can rerun any single detector without disturbing others.
- `db.py` owns the schema and the connection factory. Every other module accepts a connection or a library root; nobody hard-codes DB paths.
- `rules.py` reads detector columns and writes `verdict` / `verdict_reason`. It never inspects the filesystem.
- `trash.py` is the ONLY module allowed to move files. All UI actions call into it.
- Web layer is thin: routes → module functions → JSON. No business logic in `app.py`.

---

I'll break the tasks into three chunks so we don't hit the token cap. This document (part 1) contains **Tasks 1–4**. I'll append Tasks 5–9 (part 2) and Tasks 10–14 + self-review (part 3) in follow-up edits.

---

### Task 1: Package scaffold + pyproject

**Files:**
- Create: `pyproject.toml`
- Create: `src/picpic/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md` (one-paragraph placeholder)

**Interfaces:**
- Consumes: nothing
- Produces: an installable package `picpic` with a `picpic` console script pointing at `picpic.cli:main` (defined in Task 9). Import path `from picpic import ...` works.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "picpic"
version = "0.1.0"
description = "Local, privacy-preserving photo triage tool"
requires-python = ">=3.12"
dependencies = [
  "Pillow>=10.0",
  "imagehash>=4.3",
  "opencv-python-headless>=4.8",
  "fastapi>=0.110",
  "uvicorn>=0.29",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
picpic = "picpic.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
picpic = ["web/static/*"]
```

- [ ] **Step 2: Write `src/picpic/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Write `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Write `README.md`**

```markdown
# picpic

Local photo triage tool. See `docs/superpowers/specs/2026-07-06-picpic-design.md`.
```

- [ ] **Step 5: Create venv and install in editable mode**

Run:
```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```
Expected: install succeeds, `.venv/bin/picpic` exists (will fail to run until Task 9 — that's OK).

- [ ] **Step 6: Verify import**

Run: `.venv/bin/python -c "import picpic; print(picpic.__version__)"`
Expected: prints `0.1.0`.

- [ ] **Step 7: Extend `.gitignore`**

The repo already ignores `__pycache__`, `.venv`, `picpic.db`, `_picpic_trash`. Add these lines to `.gitignore`:

```
*.egg-info/
build/
dist/
.pytest_cache/
```

- [ ] **Step 8: Commit**

```
git add pyproject.toml src/picpic/__init__.py tests/__init__.py README.md .gitignore
git commit -m "chore: scaffold picpic package"
```

---

### Task 2: Database schema and connection helper

**Files:**
- Create: `src/picpic/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `open_db(path: pathlib.Path) -> sqlite3.Connection` — opens (creating if needed), applies schema, returns a connection with `row_factory = sqlite3.Row` and foreign keys on.
  - `SCHEMA_VERSION: int = 1`
  - Table `photos` with these exact columns and types:
    - `id INTEGER PRIMARY KEY AUTOINCREMENT`
    - `path TEXT NOT NULL UNIQUE`
    - `file_hash TEXT`
    - `phash TEXT`
    - `width INTEGER`
    - `height INTEGER`
    - `file_size INTEGER`
    - `created_at TEXT` (ISO 8601 string, or NULL)
    - `camera_model TEXT`
    - `is_screenshot INTEGER` (0/1, NULL = not analyzed)
    - `blur_score REAL`
    - `dup_group INTEGER`
    - `clip_labels TEXT` (JSON, unused in Phase 1 but reserved)
    - `verdict TEXT CHECK(verdict IN ('keep','trash_candidate')) DEFAULT NULL`
    - `verdict_reason TEXT`
    - `status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','trashed'))`
    - `trashed_at TEXT`
  - A `meta` table with `key TEXT PRIMARY KEY, value TEXT` — stores `schema_version`.
  - Indexes: `idx_photos_status(status)`, `idx_photos_verdict(verdict)`, `idx_photos_dup_group(dup_group)`, `idx_photos_file_hash(file_hash)`.

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import pathlib
import pytest


@pytest.fixture
def tmp_db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "picpic.db"
```

Create `tests/test_db.py`:

```python
import sqlite3
import pathlib

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


import pytest  # noqa: E402  (used by test above; kept at bottom to avoid moving)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: `ImportError` — `picpic.db` does not exist yet.

- [ ] **Step 3: Write `src/picpic/db.py`**

```python
import pathlib
import sqlite3

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  path           TEXT NOT NULL UNIQUE,
  file_hash      TEXT,
  phash          TEXT,
  width          INTEGER,
  height         INTEGER,
  file_size      INTEGER,
  created_at     TEXT,
  camera_model   TEXT,
  is_screenshot  INTEGER,
  blur_score     REAL,
  dup_group      INTEGER,
  clip_labels    TEXT,
  verdict        TEXT CHECK(verdict IN ('keep','trash_candidate')) DEFAULT NULL,
  verdict_reason TEXT,
  status         TEXT NOT NULL DEFAULT 'active'
                 CHECK(status IN ('active','trashed')),
  trashed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_status     ON photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_verdict    ON photos(verdict);
CREATE INDEX IF NOT EXISTS idx_photos_dup_group  ON photos(dup_group);
CREATE INDEX IF NOT EXISTS idx_photos_file_hash  ON photos(file_hash);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""


def open_db(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/db.py tests/conftest.py tests/test_db.py
git commit -m "feat(db): sqlite schema and open_db helper"
```

---

### Task 3: Filesystem scan (register photos)

**Files:**
- Create: `src/picpic/scan.py`
- Create: `tests/fixtures/` (a helper for tests to build tiny JPEGs; no images committed — generated in-test)
- Create: `tests/test_scan.py`

**Interfaces:**
- Consumes: `open_db` from Task 2.
- Produces:
  - `SUPPORTED_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".heic", ".webp"})`
  - `scan_library(root: pathlib.Path, conn: sqlite3.Connection) -> ScanReport`
  - `@dataclass ScanReport: added: int; already_present: int; skipped: int`
  - Every added row has `path` set to the absolute POSIX path, `file_size` filled from `os.stat`, and `status='active'`. Detector columns remain NULL — the analyze step fills them.
  - Skips files under any directory named `_picpic_trash` or `.picpic_thumbs`, plus dotfiles.
  - Idempotent: rescanning the same root does not create duplicate rows (uses `path` UNIQUE constraint).

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan.py`:

```python
import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(16, 16), color=(255, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_scan_registers_supported_files(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")
    _make_jpeg(lib / "sub" / "b.jpeg")
    _make_jpeg(lib / "c.png")
    (lib / "notes.txt").write_text("hi")

    conn = open_db(tmp_db_path)
    try:
        report = scan_library(lib, conn)
        rows = conn.execute(
            "SELECT path, status, file_size FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert report.added == 3
    assert report.skipped == 1  # notes.txt
    paths = [r["path"] for r in rows]
    assert all(p.endswith((".jpg", ".jpeg", ".png")) for p in paths)
    assert all(r["status"] == "active" for r in rows)
    assert all(r["file_size"] > 0 for r in rows)


def test_scan_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")

    conn = open_db(tmp_db_path)
    try:
        first = scan_library(lib, conn)
        second = scan_library(lib, conn)
        count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    finally:
        conn.close()

    assert first.added == 1
    assert second.added == 0
    assert second.already_present == 1
    assert count == 1


def test_scan_ignores_trash_and_thumbs_and_dotfiles(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "keep.jpg")
    _make_jpeg(lib / "_picpic_trash" / "gone.jpg")
    _make_jpeg(lib / ".picpic_thumbs" / "cache.jpg")
    _make_jpeg(lib / ".hidden.jpg")

    conn = open_db(tmp_db_path)
    try:
        report = scan_library(lib, conn)
        paths = [
            r["path"]
            for r in conn.execute("SELECT path FROM photos").fetchall()
        ]
    finally:
        conn.close()

    assert report.added == 1
    assert paths[0].endswith("keep.jpg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scan.py -v`
Expected: `ImportError` — `picpic.scan` does not exist.

- [ ] **Step 3: Write `src/picpic/scan.py`**

```python
from __future__ import annotations

import os
import pathlib
import sqlite3
from dataclasses import dataclass


SUPPORTED_EXTS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".webp"})
_IGNORED_DIRS = frozenset({"_picpic_trash", ".picpic_thumbs"})


@dataclass
class ScanReport:
    added: int
    already_present: int
    skipped: int


def _iter_photo_paths(root: pathlib.Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORED_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            ext = pathlib.Path(name).suffix.lower()
            if ext in SUPPORTED_EXTS:
                yield pathlib.Path(dirpath) / name


def scan_library(root: pathlib.Path, conn: sqlite3.Connection) -> ScanReport:
    root = root.resolve()
    added = already = skipped = 0

    for full in os.scandir_walk_all_files(root) if False else []:
        pass

    seen_supported = 0
    for path in _iter_photo_paths(root):
        seen_supported += 1
        abs_path = str(path.resolve())
        size = path.stat().st_size
        try:
            conn.execute(
                "INSERT INTO photos(path, file_size, status) "
                "VALUES(?, ?, 'active')",
                (abs_path, size),
            )
            added += 1
        except sqlite3.IntegrityError:
            already += 1

    total_files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORED_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if not name.startswith("."):
                total_files += 1
    skipped = total_files - seen_supported

    conn.commit()
    return ScanReport(added=added, already_present=already, skipped=skipped)
```

Note: the `os.scandir_walk_all_files` line is a deliberate no-op guard used only to keep imports minimal — remove it in the actual write. The final version should just be the two loops. If you're doing this literally, delete the dead `for full in ...` loop before running tests.

**Cleaned-up version to actually write:**

```python
from __future__ import annotations

import os
import pathlib
import sqlite3
from dataclasses import dataclass


SUPPORTED_EXTS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".webp"})
_IGNORED_DIRS = frozenset({"_picpic_trash", ".picpic_thumbs"})


@dataclass
class ScanReport:
    added: int
    already_present: int
    skipped: int


def _walk(root: pathlib.Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORED_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            yield pathlib.Path(dirpath) / name


def scan_library(root: pathlib.Path, conn: sqlite3.Connection) -> ScanReport:
    root = root.resolve()
    added = already = skipped = 0

    for path in _walk(root):
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTS:
            skipped += 1
            continue
        abs_path = str(path.resolve())
        size = path.stat().st_size
        try:
            conn.execute(
                "INSERT INTO photos(path, file_size, status) "
                "VALUES(?, ?, 'active')",
                (abs_path, size),
            )
            added += 1
        except sqlite3.IntegrityError:
            already += 1

    conn.commit()
    return ScanReport(added=added, already_present=already, skipped=skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scan.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/scan.py tests/test_scan.py
git commit -m "feat(scan): register photos into sqlite (idempotent)"
```

---

### Task 4: EXIF-based screenshot detector

**Files:**
- Create: `src/picpic/analyze/__init__.py` (empty)
- Create: `src/picpic/analyze/exif.py`
- Create: `tests/test_exif.py`

**Interfaces:**
- Consumes: `open_db` from Task 2, rows populated by `scan_library` from Task 3.
- Produces:
  - `read_exif(path: pathlib.Path) -> ExifInfo` — pure, no DB.
  - `@dataclass ExifInfo: width: int; height: int; camera_model: str | None; created_at: str | None`
    - `created_at` is ISO 8601 (`YYYY-MM-DDTHH:MM:SS`) or `None`.
  - `is_screenshot(info: ExifInfo) -> bool` — `True` when `camera_model is None` OR the (width, height) matches a known screen resolution.
  - `SCREEN_RESOLUTIONS: frozenset[tuple[int, int]]` — includes both orientations of common phone/desktop sizes: (1080,1920), (1170,2532), (1179,2556), (1290,2796), (1284,2778), (1440,2560), (1440,3120), (1080,2400), (750,1334), (828,1792), (1242,2688), (1920,1080), (2560,1440), (3840,2160), (2732,2048), (2048,2732), (1668,2388), (2388,1668).
  - `run_exif_pass(conn: sqlite3.Connection) -> int` — reads all `active` rows with `is_screenshot IS NULL`, fills `width`, `height`, `camera_model`, `created_at`, `is_screenshot`. Returns number of rows updated.

- [ ] **Step 1: Write the failing test**

Create `tests/test_exif.py`:

```python
import pathlib

from PIL import Image

from picpic.analyze.exif import (
    ExifInfo,
    is_screenshot,
    read_exif,
    run_exif_pass,
    SCREEN_RESOLUTIONS,
)
from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(16, 16), color=(0, 128, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_read_exif_no_metadata_returns_none_camera(tmp_path):
    p = tmp_path / "plain.jpg"
    _make_jpeg(p, size=(400, 300))
    info = read_exif(p)
    assert info.width == 400 and info.height == 300
    assert info.camera_model is None
    assert info.created_at is None


def test_is_screenshot_flags_missing_camera():
    info = ExifInfo(width=800, height=600, camera_model=None, created_at=None)
    assert is_screenshot(info) is True


def test_is_screenshot_flags_screen_resolution_even_with_camera():
    assert (1170, 2532) in SCREEN_RESOLUTIONS
    info = ExifInfo(
        width=1170, height=2532, camera_model="iPhone 13", created_at=None
    )
    assert is_screenshot(info) is True


def test_is_screenshot_negative_case():
    info = ExifInfo(
        width=4032, height=3024, camera_model="iPhone 13", created_at=None
    )
    assert is_screenshot(info) is False


def test_run_exif_pass_updates_db(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "shot.jpg", size=(1170, 2532))
    _make_jpeg(lib / "photo.jpg", size=(4032, 3024))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_exif_pass(conn)
        rows = conn.execute(
            "SELECT path, is_screenshot, width, height FROM photos "
            "ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    by_name = {pathlib.Path(r["path"]).name: r for r in rows}
    assert by_name["shot.jpg"]["is_screenshot"] == 1
    assert by_name["photo.jpg"]["is_screenshot"] == 1  # no camera EXIF written by PIL default → treated as screenshot
    assert by_name["shot.jpg"]["width"] == 1170


def test_run_exif_pass_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg", size=(4032, 3024))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_exif_pass(conn)
        second = run_exif_pass(conn)
    finally:
        conn.close()

    assert first == 1
    assert second == 0  # nothing left with is_screenshot IS NULL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_exif.py -v`
Expected: `ImportError` — module doesn't exist.

- [ ] **Step 3: Write `src/picpic/analyze/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Write `src/picpic/analyze/exif.py`**

```python
from __future__ import annotations

import pathlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from PIL import ExifTags, Image


_MODEL_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "Model")
_DATETIME_TAG = next(
    k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"
)


SCREEN_RESOLUTIONS = frozenset({
    # Phones (both orientations)
    (1080, 1920), (1920, 1080),
    (1170, 2532), (2532, 1170),
    (1179, 2556), (2556, 1179),
    (1290, 2796), (2796, 1290),
    (1284, 2778), (2778, 1284),
    (1440, 2560), (2560, 1440),
    (1440, 3120), (3120, 1440),
    (1080, 2400), (2400, 1080),
    (750, 1334),  (1334, 750),
    (828, 1792),  (1792, 828),
    (1242, 2688), (2688, 1242),
    # Tablets / desktop
    (2732, 2048), (2048, 2732),
    (1668, 2388), (2388, 1668),
    (3840, 2160), (2160, 3840),
})


@dataclass
class ExifInfo:
    width: int
    height: int
    camera_model: str | None
    created_at: str | None


def _parse_exif_datetime(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return dt.isoformat()


def read_exif(path: pathlib.Path) -> ExifInfo:
    with Image.open(path) as img:
        width, height = img.size
        exif = img.getexif() or {}
    model = exif.get(_MODEL_TAG)
    if isinstance(model, bytes):
        model = model.decode("utf-8", errors="replace")
    if isinstance(model, str):
        model = model.strip() or None
    created = _parse_exif_datetime(exif.get(_DATETIME_TAG))
    return ExifInfo(
        width=width, height=height, camera_model=model, created_at=created
    )


def is_screenshot(info: ExifInfo) -> bool:
    if info.camera_model is None:
        return True
    return (info.width, info.height) in SCREEN_RESOLUTIONS


def run_exif_pass(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id, path FROM photos "
        "WHERE status='active' AND is_screenshot IS NULL"
    )
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        try:
            info = read_exif(pathlib.Path(row["path"]))
        except Exception:
            conn.execute(
                "UPDATE photos SET is_screenshot=0 WHERE id=?", (row["id"],)
            )
            updated += 1
            continue
        conn.execute(
            "UPDATE photos SET width=?, height=?, camera_model=?, "
            "created_at=?, is_screenshot=? WHERE id=?",
            (
                info.width, info.height, info.camera_model, info.created_at,
                1 if is_screenshot(info) else 0,
                row["id"],
            ),
        )
        updated += 1
    conn.commit()
    return updated
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_exif.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```
git add src/picpic/analyze/__init__.py src/picpic/analyze/exif.py tests/test_exif.py
git commit -m "feat(analyze): exif-based screenshot detector"
```

---

### Task 5: File hash + perceptual hash

**Files:**
- Create: `src/picpic/analyze/hashes.py`
- Create: `tests/test_hashes.py`

**Interfaces:**
- Consumes: `open_db` (Task 2), rows populated by `scan_library` (Task 3).
- Produces:
  - `sha256_file(path: pathlib.Path, chunk: int = 65536) -> str` — hex digest.
  - `perceptual_hash(path: pathlib.Path) -> str` — hex string of `imagehash.phash`, 16 hex chars.
  - `run_hash_pass(conn: sqlite3.Connection) -> int` — for every `active` row where `file_hash IS NULL OR phash IS NULL`, computes both and writes them. Returns rows updated.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hashes.py`:

```python
import pathlib

from PIL import Image

from picpic.analyze.hashes import (
    perceptual_hash,
    run_hash_pass,
    sha256_file,
)
from picpic.db import open_db
from picpic.scan import scan_library


def _make_jpeg(path: pathlib.Path, size=(64, 64), color=(200, 100, 50)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_sha256_file_stable(tmp_path):
    p = tmp_path / "a.jpg"
    _make_jpeg(p)
    h1 = sha256_file(p)
    h2 = sha256_file(p)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_sha256_differs_on_different_content(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    _make_jpeg(a, color=(255, 0, 0))
    _make_jpeg(b, color=(0, 255, 0))
    assert sha256_file(a) != sha256_file(b)


def test_perceptual_hash_is_hex_16(tmp_path):
    p = tmp_path / "a.jpg"
    _make_jpeg(p)
    h = perceptual_hash(p)
    assert len(h) == 16
    int(h, 16)  # hex parseable


def test_perceptual_hash_similar_for_resized(tmp_path):
    from PIL import Image as _I
    big = tmp_path / "big.jpg"
    small = tmp_path / "small.jpg"
    _I.new("RGB", (512, 512), (100, 100, 100)).save(big, "JPEG")
    _I.open(big).resize((256, 256)).save(small, "JPEG")

    import imagehash
    h1 = imagehash.hex_to_hash(perceptual_hash(big))
    h2 = imagehash.hex_to_hash(perceptual_hash(small))
    assert (h1 - h2) <= 4  # small hamming distance


def test_run_hash_pass_updates_rows(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")
    _make_jpeg(lib / "b.jpg", color=(10, 200, 30))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_hash_pass(conn)
        rows = conn.execute(
            "SELECT file_hash, phash FROM photos"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    assert all(r["file_hash"] and r["phash"] for r in rows)


def test_run_hash_pass_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_jpeg(lib / "a.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_hash_pass(conn)
        second = run_hash_pass(conn)
    finally:
        conn.close()

    assert first == 1
    assert second == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_hashes.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/analyze/hashes.py`**

```python
from __future__ import annotations

import hashlib
import pathlib
import sqlite3

import imagehash
from PIL import Image


def sha256_file(path: pathlib.Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def perceptual_hash(path: pathlib.Path) -> str:
    with Image.open(path) as img:
        return str(imagehash.phash(img))


def run_hash_pass(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id, path FROM photos "
        "WHERE status='active' AND (file_hash IS NULL OR phash IS NULL)"
    )
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        p = pathlib.Path(row["path"])
        try:
            fh = sha256_file(p)
            ph = perceptual_hash(p)
        except Exception:
            continue
        conn.execute(
            "UPDATE photos SET file_hash=?, phash=? WHERE id=?",
            (fh, ph, row["id"]),
        )
        updated += 1
    conn.commit()
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_hashes.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/analyze/hashes.py tests/test_hashes.py
git commit -m "feat(analyze): file and perceptual hashes"
```

---

### Task 6: Similar-image grouping (dup_group)

**Files:**
- Create: `src/picpic/analyze/similar.py`
- Create: `tests/test_similar.py`

**Interfaces:**
- Consumes: `phash` column populated by Task 5.
- Produces:
  - `HAMMING_THRESHOLD: int = 6` — module constant, phash distance ≤ this ⇒ same group.
  - `run_similarity_pass(conn: sqlite3.Connection, threshold: int = HAMMING_THRESHOLD) -> int` — assigns `dup_group` (integer group id starting at 1) to any photos that are visually similar. Photos with no near-neighbor keep `dup_group = NULL`. Returns number of photos placed into a group.
  - Deterministic: for the same phashes, same input order, same groups. Group IDs are assigned in ascending order of the smallest photo `id` in the group.
  - Idempotent when re-run on the same data — clears prior `dup_group` values on each run so groups reflect current phash state.

Algorithm: union-find over active photos with non-null phash. For each pair (i,j) with i<j, if `hamming(phash_i, phash_j) <= threshold`, union them. Then assign group IDs to components of size ≥ 2.

Complexity note: O(n²) pair comparison is fine for MVP (2w photos ≈ 200M compares of a 64-bit int XOR + popcount, seconds-scale in Python). Optimize later if needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_similar.py`:

```python
import pathlib

from PIL import Image

from picpic.analyze.hashes import run_hash_pass
from picpic.analyze.similar import HAMMING_THRESHOLD, run_similarity_pass
from picpic.db import open_db
from picpic.scan import scan_library


def _make(path, size=(64, 64), color=(0, 0, 0)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def test_similarity_groups_near_duplicates(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    # a.jpg and a2.jpg are the same image at different sizes
    _make(lib / "a.jpg", size=(400, 400), color=(180, 20, 20))
    from PIL import Image as I
    I.open(lib / "a.jpg").resize((200, 200)).save(lib / "a2.jpg", "JPEG")
    _make(lib / "b.jpg", size=(400, 400), color=(10, 200, 30))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        run_hash_pass(conn)
        placed = run_similarity_pass(conn)
        rows = conn.execute(
            "SELECT path, dup_group FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    by_name = {pathlib.Path(r["path"]).name: r["dup_group"] for r in rows}
    assert by_name["a.jpg"] is not None
    assert by_name["a.jpg"] == by_name["a2.jpg"]
    assert by_name["b.jpg"] is None
    assert placed == 2


def test_similarity_is_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make(lib / "solo.jpg", color=(1, 2, 3))

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        run_hash_pass(conn)
        first = run_similarity_pass(conn)
        second = run_similarity_pass(conn)
        row = conn.execute(
            "SELECT dup_group FROM photos"
        ).fetchone()
    finally:
        conn.close()

    assert first == 0
    assert second == 0
    assert row["dup_group"] is None


def test_threshold_default_is_six():
    assert HAMMING_THRESHOLD == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_similar.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/analyze/similar.py`**

```python
from __future__ import annotations

import sqlite3


HAMMING_THRESHOLD = 6


def _hex_to_int(h: str) -> int:
    return int(h, 16)


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def run_similarity_pass(
    conn: sqlite3.Connection,
    threshold: int = HAMMING_THRESHOLD,
) -> int:
    rows = conn.execute(
        "SELECT id, phash FROM photos "
        "WHERE status='active' AND phash IS NOT NULL "
        "ORDER BY id"
    ).fetchall()

    conn.execute(
        "UPDATE photos SET dup_group=NULL WHERE status='active'"
    )

    if not rows:
        conn.commit()
        return 0

    ids = [r["id"] for r in rows]
    hashes = [_hex_to_int(r["phash"]) for r in rows]
    uf = _UF(len(rows))

    for i in range(len(rows)):
        hi = hashes[i]
        for j in range(i + 1, len(rows)):
            if _hamming(hi, hashes[j]) <= threshold:
                uf.union(i, j)

    components: dict[int, list[int]] = {}
    for idx in range(len(rows)):
        root = uf.find(idx)
        components.setdefault(root, []).append(idx)

    ordered_roots = sorted(
        (root for root, members in components.items() if len(members) >= 2),
        key=lambda r: min(ids[i] for i in components[r]),
    )

    placed = 0
    for group_id, root in enumerate(ordered_roots, start=1):
        for idx in components[root]:
            conn.execute(
                "UPDATE photos SET dup_group=? WHERE id=?",
                (group_id, ids[idx]),
            )
            placed += 1
    conn.commit()
    return placed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_similar.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/analyze/similar.py tests/test_similar.py
git commit -m "feat(analyze): union-find similarity grouping"
```

---

### Task 7: Blur detector

**Files:**
- Create: `src/picpic/analyze/blur.py`
- Create: `tests/test_blur.py`

**Interfaces:**
- Consumes: `active` rows (uses `path`).
- Produces:
  - `laplacian_variance(path: pathlib.Path) -> float` — reads image with OpenCV, converts to grayscale, returns variance of Laplacian.
  - `run_blur_pass(conn: sqlite3.Connection) -> int` — for every `active` row where `blur_score IS NULL`, writes score. Returns rows updated. Files that fail to load get `blur_score = 0.0` and are still counted.

- [ ] **Step 1: Write the failing test**

Create `tests/test_blur.py`:

```python
import pathlib

import cv2
import numpy as np
from PIL import Image, ImageFilter

from picpic.analyze.blur import laplacian_variance, run_blur_pass
from picpic.db import open_db
from picpic.scan import scan_library


def _make_sharp(path, size=(200, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[::4, :, :] = 255  # sharp horizontal stripes
    Image.fromarray(arr).save(path, "JPEG", quality=95)


def _make_blurry(path, size=(200, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[::4, :, :] = 255
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(radius=8))
    img.save(path, "JPEG", quality=95)


def test_laplacian_variance_higher_for_sharp(tmp_path):
    sharp = tmp_path / "sharp.jpg"
    blurry = tmp_path / "blur.jpg"
    _make_sharp(sharp)
    _make_blurry(blurry)
    assert laplacian_variance(sharp) > laplacian_variance(blurry)


def test_run_blur_pass_writes_scores(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_sharp(lib / "s.jpg")
    _make_blurry(lib / "b.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        n = run_blur_pass(conn)
        rows = conn.execute(
            "SELECT path, blur_score FROM photos ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    assert n == 2
    assert all(r["blur_score"] is not None for r in rows)
    scores = {pathlib.Path(r["path"]).name: r["blur_score"] for r in rows}
    assert scores["s.jpg"] > scores["b.jpg"]


def test_run_blur_pass_idempotent(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_sharp(lib / "a.jpg")
    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        first = run_blur_pass(conn)
        second = run_blur_pass(conn)
    finally:
        conn.close()
    assert first == 1
    assert second == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_blur.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/analyze/blur.py`**

```python
from __future__ import annotations

import pathlib
import sqlite3

import cv2
import numpy as np


def laplacian_variance(path: pathlib.Path) -> float:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cannot decode image: {path}")
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def run_blur_pass(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, path FROM photos "
        "WHERE status='active' AND blur_score IS NULL"
    ).fetchall()
    updated = 0
    for row in rows:
        try:
            score = laplacian_variance(pathlib.Path(row["path"]))
        except Exception:
            score = 0.0
        conn.execute(
            "UPDATE photos SET blur_score=? WHERE id=?", (score, row["id"])
        )
        updated += 1
    conn.commit()
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blur.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/analyze/blur.py tests/test_blur.py
git commit -m "feat(analyze): laplacian-variance blur score"
```

---

### Task 8: Analyze runner

**Files:**
- Create: `src/picpic/analyze/runner.py`
- Create: `tests/test_analyze_runner.py`

**Interfaces:**
- Consumes: `run_exif_pass` (Task 4), `run_hash_pass` (Task 5), `run_similarity_pass` (Task 6), `run_blur_pass` (Task 7).
- Produces:
  - `@dataclass AnalyzeReport: exif: int; hashes: int; similar: int; blur: int`
  - `analyze_all(conn: sqlite3.Connection) -> AnalyzeReport` — runs the four passes in this order: exif → hashes → similar → blur. Similar depends on hashes, so ordering matters. Returns per-pass counts.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analyze_runner.py`:

```python
import pathlib

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
        report = analyze_all(conn)
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
        analyze_all(conn)
        second = analyze_all(conn)
    finally:
        conn.close()

    assert second.exif == 0
    assert second.hashes == 0
    assert second.blur == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_analyze_runner.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/analyze/runner.py`**

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .blur import run_blur_pass
from .exif import run_exif_pass
from .hashes import run_hash_pass
from .similar import run_similarity_pass


@dataclass
class AnalyzeReport:
    exif: int
    hashes: int
    similar: int
    blur: int


def analyze_all(conn: sqlite3.Connection) -> AnalyzeReport:
    exif = run_exif_pass(conn)
    hashes = run_hash_pass(conn)
    similar = run_similarity_pass(conn)
    blur = run_blur_pass(conn)
    return AnalyzeReport(exif=exif, hashes=hashes, similar=similar, blur=blur)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_analyze_runner.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/analyze/runner.py tests/test_analyze_runner.py
git commit -m "feat(analyze): orchestrate detector passes"
```

---

### Task 9: CLI (scan / analyze / rules / serve)

**Files:**
- Create: `src/picpic/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `open_db` (Task 2), `scan_library` (Task 3), `analyze_all` (Task 8), `apply_rules` (Task 10 — forward reference; import inside command handler to avoid circular import at module load), `serve` (Task 13).
- Produces:
  - `main(argv: list[str] | None = None) -> int` — argparse entry point. Subcommands:
    - `picpic scan <library>` — runs `scan_library`, prints report.
    - `picpic analyze <library>` — runs `analyze_all`, prints report.
    - `picpic rules <library>` — runs `apply_rules`, prints report.
    - `picpic all <library>` — runs scan → analyze → rules in one shot.
    - `picpic serve <library> [--host 127.0.0.1] [--port 8765] [--no-open]` — starts the web server (see Task 13); by default opens the browser.
  - `<library>` is the root folder. DB path is `<library>/picpic.db`.
  - Return code: 0 on success, non-zero on error.

Since `apply_rules` and `serve` don't exist yet, the CLI test in this task will only exercise `scan` and `analyze` end-to-end. `rules` and `serve` will be covered by their own task tests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/cli.py`**

```python
from __future__ import annotations

import argparse
import pathlib
import sys

from .db import open_db


def _db_path(library: pathlib.Path) -> pathlib.Path:
    return library / "picpic.db"


def _cmd_scan(args) -> int:
    from .scan import scan_library
    library = pathlib.Path(args.library).resolve()
    conn = open_db(_db_path(library))
    try:
        report = scan_library(library, conn)
    finally:
        conn.close()
    print(
        f"scan: added={report.added} "
        f"already_present={report.already_present} skipped={report.skipped}"
    )
    return 0


def _cmd_analyze(args) -> int:
    from .analyze.runner import analyze_all
    library = pathlib.Path(args.library).resolve()
    conn = open_db(_db_path(library))
    try:
        report = analyze_all(conn)
    finally:
        conn.close()
    print(
        f"analyze: exif={report.exif} hashes={report.hashes} "
        f"similar={report.similar} blur={report.blur}"
    )
    return 0


def _cmd_rules(args) -> int:
    from .rules import apply_rules
    library = pathlib.Path(args.library).resolve()
    conn = open_db(_db_path(library))
    try:
        report = apply_rules(conn)
    finally:
        conn.close()
    print(
        f"rules: kept={report.kept} candidates={report.candidates} "
        f"reasons={report.by_reason}"
    )
    return 0


def _cmd_all(args) -> int:
    for step in (_cmd_scan, _cmd_analyze, _cmd_rules):
        code = step(args)
        if code != 0:
            return code
    return 0


def _cmd_serve(args) -> int:
    from .web.app import serve
    library = pathlib.Path(args.library).resolve()
    serve(library, host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="picpic")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn in (
        ("scan", _cmd_scan),
        ("analyze", _cmd_analyze),
        ("rules", _cmd_rules),
        ("all", _cmd_all),
    ):
        p = sub.add_parser(name)
        p.add_argument("library")
        p.set_defaults(fn=fn)

    p = sub.add_parser("serve")
    p.add_argument("library")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=_cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: 2 passed. (The `rules` and `serve` subcommands are wired but not exercised — they'll be covered in later tasks.)

- [ ] **Step 5: Commit**

```
git add src/picpic/cli.py tests/test_cli.py
git commit -m "feat(cli): argparse entry with scan/analyze/rules/all/serve"
```

---

### Task 10: Rules engine (verdicts)

**Files:**
- Create: `src/picpic/rules.py`
- Create: `tests/test_rules.py`

**Interfaces:**
- Consumes: detector columns filled by Tasks 4/5/6/7.
- Produces:
  - `DEFAULT_BLUR_THRESHOLD: float = 100.0` — Laplacian variance below this ⇒ blurry (starting default; tunable in UI later).
  - `@dataclass RulesReport: kept: int; candidates: int; by_reason: dict[str, int]`
  - `apply_rules(conn: sqlite3.Connection, blur_threshold: float = DEFAULT_BLUR_THRESHOLD) -> RulesReport`
    - Only touches `active` rows.
    - Resets `verdict` and `verdict_reason` to NULL, then writes fresh values (idempotent).
    - Rules (evaluated in this priority — first match wins):
      1. `is_screenshot = 1` → `verdict='trash_candidate'`, `reason='screenshot'`
      2. `blur_score IS NOT NULL AND blur_score < blur_threshold` → `trash_candidate`, `reason='blurry'`
      3. Rows sharing `file_hash` (exact byte-identical duplicates): keep the smallest `id`, mark the rest `trash_candidate`, `reason='exact_dup'`.
      4. Otherwise → `verdict='keep'`.
    - **Similar-image groups (`dup_group`) are NEVER auto-marked** — spec is explicit; those go to the manual review tab only.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rules.py`:

```python
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


def _make_blurry(path):
    from PIL import ImageFilter
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (400, 400), (200, 30, 30)).filter(
        ImageFilter.GaussianBlur(radius=12)
    )
    img.save(path, "JPEG", quality=95)


def test_screenshot_becomes_candidate(tmp_path, tmp_db_path):
    lib = tmp_path / "lib"
    _make_screenshot(lib / "s.jpg")

    conn = open_db(tmp_db_path)
    try:
        scan_library(lib, conn)
        analyze_all(conn)
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
        analyze_all(conn)
        # give both photos an EXIF camera model to escape screenshot rule:
        conn.execute("UPDATE photos SET camera_model='Canon', is_screenshot=0")
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
        analyze_all(conn)
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
        analyze_all(conn)
        first = apply_rules(conn)
        second = apply_rules(conn)
    finally:
        conn.close()

    assert first.candidates == second.candidates == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_rules.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/rules.py`**

```python
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field


DEFAULT_BLUR_THRESHOLD = 100.0


@dataclass
class RulesReport:
    kept: int = 0
    candidates: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)


def apply_rules(
    conn: sqlite3.Connection,
    blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
) -> RulesReport:
    conn.execute(
        "UPDATE photos SET verdict=NULL, verdict_reason=NULL "
        "WHERE status='active'"
    )

    rows = conn.execute(
        "SELECT id, is_screenshot, blur_score, file_hash "
        "FROM photos WHERE status='active' ORDER BY id"
    ).fetchall()

    hash_first_id: dict[str, int] = {}
    for r in rows:
        fh = r["file_hash"]
        if fh and fh not in hash_first_id:
            hash_first_id[fh] = r["id"]

    counts: dict[str, int] = defaultdict(int)
    kept = candidates = 0

    for r in rows:
        rid = r["id"]
        reason: str | None = None

        if r["is_screenshot"] == 1:
            reason = "screenshot"
        elif r["blur_score"] is not None and r["blur_score"] < blur_threshold:
            reason = "blurry"
        elif r["file_hash"] and hash_first_id[r["file_hash"]] != rid:
            reason = "exact_dup"

        if reason is None:
            conn.execute(
                "UPDATE photos SET verdict='keep', verdict_reason=NULL "
                "WHERE id=?",
                (rid,),
            )
            kept += 1
        else:
            conn.execute(
                "UPDATE photos SET verdict='trash_candidate', "
                "verdict_reason=? WHERE id=?",
                (reason, rid),
            )
            candidates += 1
            counts[reason] += 1

    conn.commit()
    return RulesReport(kept=kept, candidates=candidates, by_reason=dict(counts))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_rules.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/rules.py tests/test_rules.py
git commit -m "feat(rules): compute per-photo verdicts"
```

---

### Task 11: Trash operations (move / restore / purge)

**Files:**
- Create: `src/picpic/trash.py`
- Create: `tests/test_trash.py`

**Interfaces:**
- Consumes: `active` rows, `path` column.
- Produces:
  - `TRASH_DIRNAME: str = "_picpic_trash"` — module constant.
  - `trash_photos(conn: sqlite3.Connection, library: pathlib.Path, ids: list[int]) -> int`
    - For each id: moves the file from its `path` to `<library>/_picpic_trash/<id>__<original-name>`; sets `status='trashed'`, `trashed_at=<iso now passed in>`. Returns count moved.
    - Actually: to keep tests deterministic, accepts an optional `now: str | None = None`; when None, uses `datetime.utcnow().isoformat()`.
    - Skips ids that are already `trashed`.
    - **Never** overwrites an existing file in the trash (if collision, appends `-2`, `-3`, ...).
  - `restore_photos(conn: sqlite3.Connection, library: pathlib.Path, ids: list[int]) -> int`
    - For each id: moves file back to its stored `path`; sets `status='active'`, `trashed_at=NULL`. Returns count restored. If the original path is now occupied by a different file, restores next to it as `<name>.restored<ext>`.
  - `purge_trash(conn: sqlite3.Connection, library: pathlib.Path) -> int`
    - Physically deletes every file currently in `<library>/_picpic_trash/`, then removes trashed rows from the DB. Returns files deleted. **This is the only real-delete path in the entire system.**

- [ ] **Step 1: Write the failing test**

Create `tests/test_trash.py`:

```python
import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library
from picpic.trash import (
    TRASH_DIRNAME, purge_trash, restore_photos, trash_photos,
)


def _make(path, color=(50, 50, 50)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path, "JPEG")


def _ids(conn):
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM photos ORDER BY id"
        ).fetchall()
    ]


def test_trash_photos_moves_and_marks(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(200, 30, 30))
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        moved = trash_photos(conn, lib, [ids[0]], now="2026-07-06T00:00:00")
        row = conn.execute(
            "SELECT status, trashed_at FROM photos WHERE id=?", (ids[0],)
        ).fetchone()
    finally:
        conn.close()

    assert moved == 1
    assert row["status"] == "trashed"
    assert row["trashed_at"] == "2026-07-06T00:00:00"
    assert not (lib / "a.jpg").exists()
    trash_dir = lib / TRASH_DIRNAME
    assert trash_dir.exists()
    moved_files = list(trash_dir.iterdir())
    assert len(moved_files) == 1
    assert moved_files[0].name.startswith(f"{ids[0]}__")


def test_trash_skips_already_trashed(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        again = trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
    finally:
        conn.close()
    assert again == 0


def test_restore_moves_back(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        restored = restore_photos(conn, lib, ids)
        row = conn.execute(
            "SELECT status, trashed_at FROM photos WHERE id=?", (ids[0],)
        ).fetchone()
    finally:
        conn.close()

    assert restored == 1
    assert row["status"] == "active"
    assert row["trashed_at"] is None
    assert (lib / "a.jpg").exists()


def test_purge_deletes_files_and_rows(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg", color=(10, 200, 10))
    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        ids = _ids(conn)
        trash_photos(conn, lib, ids, now="2026-07-06T00:00:00")
        n = purge_trash(conn, lib)
        remaining = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    finally:
        conn.close()

    assert n == 2
    assert remaining == 0
    trash_dir = lib / TRASH_DIRNAME
    assert list(trash_dir.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_trash.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/trash.py`**

```python
from __future__ import annotations

import pathlib
import shutil
import sqlite3
from datetime import datetime


TRASH_DIRNAME = "_picpic_trash"


def _trash_dir(library: pathlib.Path) -> pathlib.Path:
    d = library / TRASH_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_dest(dest: pathlib.Path) -> pathlib.Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    parent = dest.parent
    i = 2
    while True:
        cand = parent / f"{stem}-{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def trash_photos(
    conn: sqlite3.Connection,
    library: pathlib.Path,
    ids: list[int],
    now: str | None = None,
) -> int:
    if not ids:
        return 0
    now = now or datetime.utcnow().isoformat(timespec="seconds")
    trash = _trash_dir(library)
    moved = 0
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, path, status FROM photos WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    for r in rows:
        if r["status"] == "trashed":
            continue
        src = pathlib.Path(r["path"])
        if not src.exists():
            conn.execute(
                "UPDATE photos SET status='trashed', trashed_at=? WHERE id=?",
                (now, r["id"]),
            )
            continue
        dest = _unique_dest(trash / f"{r['id']}__{src.name}")
        shutil.move(str(src), str(dest))
        conn.execute(
            "UPDATE photos SET status='trashed', trashed_at=? WHERE id=?",
            (now, r["id"]),
        )
        moved += 1
    conn.commit()
    return moved


def _find_in_trash(library: pathlib.Path, photo_id: int) -> pathlib.Path | None:
    trash = library / TRASH_DIRNAME
    if not trash.exists():
        return None
    prefix = f"{photo_id}__"
    for entry in trash.iterdir():
        if entry.name.startswith(prefix) or entry.name.startswith(
            f"{photo_id}-"
        ):
            return entry
    return None


def restore_photos(
    conn: sqlite3.Connection,
    library: pathlib.Path,
    ids: list[int],
) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, path, status FROM photos WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    restored = 0
    for r in rows:
        if r["status"] != "trashed":
            continue
        src = _find_in_trash(library, r["id"])
        original = pathlib.Path(r["path"])
        if src is None:
            conn.execute(
                "UPDATE photos SET status='active', trashed_at=NULL "
                "WHERE id=?",
                (r["id"],),
            )
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        if original.exists():
            dest = original.with_name(
                f"{original.stem}.restored{original.suffix}"
            )
        else:
            dest = original
        shutil.move(str(src), str(dest))
        conn.execute(
            "UPDATE photos SET status='active', trashed_at=NULL, path=? "
            "WHERE id=?",
            (str(dest), r["id"]),
        )
        restored += 1
    conn.commit()
    return restored


def purge_trash(
    conn: sqlite3.Connection,
    library: pathlib.Path,
) -> int:
    trash = library / TRASH_DIRNAME
    deleted = 0
    if trash.exists():
        for entry in list(trash.iterdir()):
            if entry.is_file():
                entry.unlink()
                deleted += 1
    conn.execute("DELETE FROM photos WHERE status='trashed'")
    conn.commit()
    return deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_trash.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/trash.py tests/test_trash.py
git commit -m "feat(trash): reversible trash + purge (only real-delete path)"
```

---

### Task 12: Thumbnail cache

**Files:**
- Create: `src/picpic/thumbs.py`
- Create: `tests/test_thumbs.py`

**Interfaces:**
- Consumes: `path` and `id` of photo rows.
- Produces:
  - `THUMB_DIRNAME: str = ".picpic_thumbs"`
  - `THUMB_MAX: tuple[int, int] = (256, 256)`
  - `thumb_path(library: pathlib.Path, photo_id: int) -> pathlib.Path` — deterministic path `<library>/.picpic_thumbs/<id>.jpg`.
  - `ensure_thumb(library: pathlib.Path, photo_id: int, source: pathlib.Path) -> pathlib.Path` — creates the thumbnail if missing (JPEG, longest side ≤ 256), returns its path. Idempotent.
  - `iter_missing_thumbs(conn: sqlite3.Connection, library: pathlib.Path) -> Iterable[tuple[int, pathlib.Path]]` — yields `(id, source_path)` pairs for `active` rows whose thumb is missing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_thumbs.py`:

```python
import pathlib

from PIL import Image

from picpic.db import open_db
from picpic.scan import scan_library
from picpic.thumbs import (
    THUMB_DIRNAME, THUMB_MAX, ensure_thumb, iter_missing_thumbs, thumb_path,
)


def _make(path, size=(1024, 1024)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (100, 150, 200)).save(path, "JPEG")


def test_ensure_thumb_creates_scaled_jpeg(tmp_path):
    lib = tmp_path / "lib"
    src = lib / "big.jpg"
    _make(src, size=(1024, 768))
    out = ensure_thumb(lib, 1, src)
    assert out == thumb_path(lib, 1)
    assert out.exists()
    with Image.open(out) as img:
        w, h = img.size
    assert max(w, h) <= max(THUMB_MAX)
    assert (lib / THUMB_DIRNAME).exists()


def test_ensure_thumb_is_idempotent(tmp_path):
    lib = tmp_path / "lib"
    src = lib / "big.jpg"
    _make(src)
    a = ensure_thumb(lib, 1, src)
    stat_a = a.stat().st_mtime_ns
    b = ensure_thumb(lib, 1, src)
    assert a == b
    assert b.stat().st_mtime_ns == stat_a  # not rewritten


def test_iter_missing_thumbs(tmp_path):
    lib = tmp_path / "lib"
    _make(lib / "a.jpg")
    _make(lib / "b.jpg")

    conn = open_db(lib / "picpic.db")
    try:
        scan_library(lib, conn)
        # generate thumb for one of them
        row = conn.execute(
            "SELECT id, path FROM photos ORDER BY id LIMIT 1"
        ).fetchone()
        ensure_thumb(lib, row["id"], pathlib.Path(row["path"]))
        missing = list(iter_missing_thumbs(conn, lib))
    finally:
        conn.close()

    assert len(missing) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_thumbs.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Write `src/picpic/thumbs.py`**

```python
from __future__ import annotations

import pathlib
import sqlite3
from typing import Iterable

from PIL import Image


THUMB_DIRNAME = ".picpic_thumbs"
THUMB_MAX = (256, 256)


def thumb_path(library: pathlib.Path, photo_id: int) -> pathlib.Path:
    return library / THUMB_DIRNAME / f"{photo_id}.jpg"


def ensure_thumb(
    library: pathlib.Path,
    photo_id: int,
    source: pathlib.Path,
) -> pathlib.Path:
    dest = thumb_path(library, photo_id)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.convert("RGB")
        img.thumbnail(THUMB_MAX)
        img.save(dest, "JPEG", quality=80)
    return dest


def iter_missing_thumbs(
    conn: sqlite3.Connection,
    library: pathlib.Path,
) -> Iterable[tuple[int, pathlib.Path]]:
    rows = conn.execute(
        "SELECT id, path FROM photos WHERE status='active' ORDER BY id"
    ).fetchall()
    for r in rows:
        if not thumb_path(library, r["id"]).exists():
            yield r["id"], pathlib.Path(r["path"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_thumbs.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/picpic/thumbs.py tests/test_thumbs.py
git commit -m "feat(thumbs): jpeg thumbnail cache"
```

---

### Task 13: Web backend (FastAPI)

**Files:**
- Create: `src/picpic/web/__init__.py` (empty)
- Create: `src/picpic/web/app.py`
- Create: `tests/test_web.py`

**Interfaces:**
- Consumes: `open_db` (Task 2), `apply_rules` (Task 10), `trash_photos`/`restore_photos`/`purge_trash` (Task 11), `ensure_thumb` (Task 12).
- Produces:
  - `create_app(library: pathlib.Path) -> FastAPI` — factory (used by tests via `TestClient`).
  - `serve(library, host="127.0.0.1", port=8765, open_browser=True) -> None` — starts uvicorn; if `open_browser`, opens `http://host:port/` via `webbrowser.open`.
  - Routes (all JSON except the last two):
    - `GET /api/photos?tab=candidates|similar|trashed&min_blur=<float?>` — returns `{ "photos": [ {id,path,verdict,verdict_reason,dup_group,blur_score,is_screenshot,width,height} ... ] }`. `candidates` = `status='active' AND verdict='trash_candidate'` (blur filter applied when reason is `blurry`); `similar` = `status='active' AND dup_group IS NOT NULL`, ordered by `dup_group`, then `id`; `trashed` = `status='trashed'`.
    - `POST /api/trash` body `{"ids":[...]}` → `{"moved": n}`.
    - `POST /api/restore` body `{"ids":[...]}` → `{"restored": n}`.
    - `POST /api/purge` body `{}` → `{"deleted": n}`. **Server does NOT confirm** — the frontend must gate this behind a modal.
    - `POST /api/rules` body `{"blur_threshold": <float?>}` → runs `apply_rules` with the given threshold (default `DEFAULT_BLUR_THRESHOLD`), returns the report.
    - `GET /thumb/{photo_id}` → JPEG bytes of the thumbnail (creates it on-demand from the row's `path` if missing). 404 if the photo id doesn't exist or the source is missing.
    - `GET /photo/{photo_id}` → the original file bytes (on-demand, streamed with `FileResponse`). Same 404 rules.
    - `GET /` → serves `web/static/index.html`.
    - Static files at `/static/*` → `web/static/`.
  - CORS: allow only `http://127.0.0.1:*` and `http://localhost:*` (belt-and-braces; typically same-origin).

- [ ] **Step 1: Write the failing test**

Create `tests/test_web.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: `ImportError` — `picpic.web.app` does not exist yet.

- [ ] **Step 3: Write `src/picpic/web/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Write `src/picpic/web/app.py`**

```python
from __future__ import annotations

import pathlib
import webbrowser
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..db import open_db
from ..rules import DEFAULT_BLUR_THRESHOLD, apply_rules
from ..thumbs import ensure_thumb, thumb_path
from ..trash import purge_trash, restore_photos, trash_photos


_STATIC_DIR = pathlib.Path(__file__).parent / "static"


def _photo_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "path": row["path"],
        "verdict": row["verdict"],
        "verdict_reason": row["verdict_reason"],
        "dup_group": row["dup_group"],
        "blur_score": row["blur_score"],
        "is_screenshot": row["is_screenshot"],
        "width": row["width"],
        "height": row["height"],
    }


def create_app(library: pathlib.Path) -> FastAPI:
    library = library.resolve()
    db_path = library / "picpic.db"

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if _STATIC_DIR.exists():
        app.mount(
            "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
        )

    @app.get("/")
    def index():
        idx = _STATIC_DIR / "index.html"
        if not idx.exists():
            return JSONResponse({"error": "ui missing"}, status_code=500)
        return FileResponse(str(idx))

    @app.get("/api/photos")
    def list_photos(
        tab: str = Query("candidates"),
        min_blur: float | None = Query(None),
    ):
        conn = open_db(db_path)
        try:
            if tab == "candidates":
                sql = (
                    "SELECT * FROM photos "
                    "WHERE status='active' AND verdict='trash_candidate'"
                )
                params: list[Any] = []
                if min_blur is not None:
                    sql += (
                        " AND (verdict_reason<>'blurry' OR blur_score<?)"
                    )
                    params.append(min_blur)
                sql += " ORDER BY id"
                rows = conn.execute(sql, params).fetchall()
            elif tab == "similar":
                rows = conn.execute(
                    "SELECT * FROM photos "
                    "WHERE status='active' AND dup_group IS NOT NULL "
                    "ORDER BY dup_group, id"
                ).fetchall()
            elif tab == "trashed":
                rows = conn.execute(
                    "SELECT * FROM photos WHERE status='trashed' "
                    "ORDER BY trashed_at DESC, id"
                ).fetchall()
            else:
                raise HTTPException(400, f"unknown tab: {tab}")
            return {"photos": [_photo_dict(r) for r in rows]}
        finally:
            conn.close()

    @app.post("/api/trash")
    def api_trash(payload: dict = Body(...)):
        ids = list(payload.get("ids") or [])
        conn = open_db(db_path)
        try:
            n = trash_photos(conn, library, ids)
        finally:
            conn.close()
        return {"moved": n}

    @app.post("/api/restore")
    def api_restore(payload: dict = Body(...)):
        ids = list(payload.get("ids") or [])
        conn = open_db(db_path)
        try:
            n = restore_photos(conn, library, ids)
        finally:
            conn.close()
        return {"restored": n}

    @app.post("/api/purge")
    def api_purge(payload: dict = Body(default={})):
        conn = open_db(db_path)
        try:
            n = purge_trash(conn, library)
        finally:
            conn.close()
        return {"deleted": n}

    @app.post("/api/rules")
    def api_rules(payload: dict = Body(default={})):
        threshold = float(
            payload.get("blur_threshold", DEFAULT_BLUR_THRESHOLD)
        )
        conn = open_db(db_path)
        try:
            report = apply_rules(conn, blur_threshold=threshold)
        finally:
            conn.close()
        return {
            "kept": report.kept,
            "candidates": report.candidates,
            "by_reason": report.by_reason,
        }

    def _photo_row(photo_id: int):
        conn = open_db(db_path)
        try:
            row = conn.execute(
                "SELECT id, path, status FROM photos WHERE id=?",
                (photo_id,),
            ).fetchone()
        finally:
            conn.close()
        return row

    @app.get("/thumb/{photo_id}")
    def get_thumb(photo_id: int):
        row = _photo_row(photo_id)
        if row is None:
            raise HTTPException(404, "no such photo")
        source = pathlib.Path(row["path"])
        if row["status"] == "trashed":
            # look inside trash for the moved file
            from ..trash import TRASH_DIRNAME
            trash = library / TRASH_DIRNAME
            for entry in trash.iterdir() if trash.exists() else []:
                if entry.name.startswith(f"{photo_id}__"):
                    source = entry
                    break
        if not source.exists():
            raise HTTPException(404, "source missing")
        thumb = ensure_thumb(library, photo_id, source)
        return FileResponse(str(thumb), media_type="image/jpeg")

    @app.get("/photo/{photo_id}")
    def get_photo(photo_id: int):
        row = _photo_row(photo_id)
        if row is None or not pathlib.Path(row["path"]).exists():
            raise HTTPException(404, "no such photo")
        return FileResponse(row["path"])

    return app


def serve(
    library: pathlib.Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    import uvicorn
    app = create_app(library)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_web.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```
git add src/picpic/web/__init__.py src/picpic/web/app.py tests/test_web.py
git commit -m "feat(web): fastapi backend for review UI"
```

---

### Task 14: Frontend (single-page UI)

**Files:**
- Create: `src/picpic/web/static/index.html`
- Create: `src/picpic/web/static/app.js`
- Create: `src/picpic/web/static/style.css`

**Interfaces:**
- Consumes: routes from Task 13 (`GET /api/photos`, `POST /api/trash`, `POST /api/restore`, `POST /api/purge`, `POST /api/rules`, `GET /thumb/{id}`, `GET /photo/{id}`).
- Produces: a working browser UI matching spec §6:
  - Three tabs: **待删候选** / **相似图组** / **回收区**.
  - Candidate tab: reason filter checkboxes (`screenshot`, `blurry`, `exact_dup`), a blur-threshold slider that reruns `POST /api/rules`, a grid of thumbnails with a corner badge showing the reason, click to enlarge (fetches `/photo/{id}`), multi-select, "移入回收区" button.
  - Similar tab: photos rendered grouped by `dup_group`, each group as a horizontal row.
  - Trash tab: shows trashed rows; "还原" per-selection; "清空回收区" button gated by a JS `confirm()` modal (spec: this is the ONLY real-delete gate on the client).
  - Selection state maintained per-tab.
  - Uses `fetch()` and vanilla DOM — no build step, no npm.

There is no unit-testable code in this task; verification is manual (Step 5). Keep it small.

- [ ] **Step 1: Write `src/picpic/web/static/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>picpic</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <nav id="tabs">
      <button class="tab active" data-tab="candidates">待删候选</button>
      <button class="tab" data-tab="similar">相似图组</button>
      <button class="tab" data-tab="trashed">回收区</button>
    </nav>
    <div id="counts"></div>
  </header>

  <section id="controls">
    <div id="reason-filters">
      <label><input type="checkbox" value="screenshot" checked> 截图</label>
      <label><input type="checkbox" value="blurry" checked> 模糊</label>
      <label><input type="checkbox" value="exact_dup" checked> 完全重复</label>
    </div>
    <div id="blur-control">
      模糊阈值:
      <input type="range" id="blur-threshold" min="0" max="500" value="100">
      <span id="blur-value">100</span>
      <button id="rerun-rules">重跑规则</button>
    </div>
  </section>

  <main id="grid"></main>

  <footer>
    <span id="selected-count">已选 0 张</span>
    <button id="btn-primary">移入回收区</button>
    <button id="btn-secondary" hidden>清空回收区</button>
    <button id="btn-select-all">全选</button>
    <button id="btn-clear">取消</button>
  </footer>

  <div id="lightbox" hidden><img id="lightbox-img"></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `src/picpic/web/static/style.css`**

```css
* { box-sizing: border-box; }
body {
  margin: 0; font-family: system-ui, sans-serif;
  background: #111; color: #eee;
}
header, footer, section#controls {
  padding: 8px 16px; background: #1a1a1a;
  border-bottom: 1px solid #333;
  display: flex; align-items: center; gap: 12px;
}
footer { border-top: 1px solid #333; border-bottom: 0; }
nav#tabs { display: flex; gap: 4px; }
.tab {
  background: #222; color: #ccc; border: 1px solid #333;
  padding: 6px 12px; cursor: pointer;
}
.tab.active { background: #444; color: #fff; }
button { cursor: pointer; }

main#grid {
  display: grid; gap: 6px;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  padding: 12px;
}

.card {
  position: relative; aspect-ratio: 1;
  background: #000; border: 2px solid transparent;
  overflow: hidden; cursor: pointer;
}
.card.selected { border-color: #4af; }
.card img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card .badge {
  position: absolute; top: 4px; left: 4px;
  background: rgba(0,0,0,0.75); color: #fff;
  padding: 2px 6px; font-size: 11px; border-radius: 3px;
}

.group { grid-column: 1 / -1; display: flex; gap: 6px; overflow-x: auto; padding: 8px 0; border-bottom: 1px solid #333; }
.group .card { min-width: 140px; }

#lightbox {
  position: fixed; inset: 0; background: rgba(0,0,0,0.9);
  display: flex; align-items: center; justify-content: center; z-index: 10;
}
#lightbox img { max-width: 95vw; max-height: 95vh; }
```

- [ ] **Step 3: Write `src/picpic/web/static/app.js`**

```javascript
const state = {
  tab: 'candidates',
  photos: [],
  selected: new Set(),
  reasons: new Set(['screenshot', 'blurry', 'exact_dup']),
  blurThreshold: 100,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function load() {
  const params = new URLSearchParams({ tab: state.tab });
  const { photos } = await api(`/api/photos?${params}`);
  state.photos = photos;
  state.selected.clear();
  render();
}

function render() {
  const grid = $('#grid');
  grid.innerHTML = '';

  const filtered = state.tab === 'candidates'
    ? state.photos.filter(p => state.reasons.has(p.verdict_reason))
    : state.photos;

  if (state.tab === 'similar') {
    const groups = new Map();
    for (const p of filtered) {
      if (!groups.has(p.dup_group)) groups.set(p.dup_group, []);
      groups.get(p.dup_group).push(p);
    }
    for (const [gid, members] of groups) {
      const row = document.createElement('div');
      row.className = 'group';
      row.dataset.group = gid;
      for (const p of members) row.appendChild(cardFor(p));
      grid.appendChild(row);
    }
  } else {
    for (const p of filtered) grid.appendChild(cardFor(p));
  }

  $('#selected-count').textContent = `已选 ${state.selected.size} 张`;
  const primary = $('#btn-primary');
  const secondary = $('#btn-secondary');
  if (state.tab === 'trashed') {
    primary.textContent = '还原选中';
    secondary.hidden = false;
    secondary.textContent = '清空回收区';
  } else {
    primary.textContent = '移入回收区';
    secondary.hidden = true;
  }
}

function cardFor(p) {
  const el = document.createElement('div');
  el.className = 'card' + (state.selected.has(p.id) ? ' selected' : '');
  el.dataset.id = p.id;
  el.innerHTML = `
    <img loading="lazy" src="/thumb/${p.id}" alt="">
    ${p.verdict_reason ? `<div class="badge">${p.verdict_reason}</div>` : ''}
  `;
  el.addEventListener('click', (ev) => {
    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) {
      openLightbox(p.id);
    } else {
      toggleSelect(p.id);
    }
  });
  return el;
}

function toggleSelect(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  render();
}

function openLightbox(id) {
  $('#lightbox-img').src = `/photo/${id}`;
  $('#lightbox').hidden = false;
}
$('#lightbox').addEventListener('click', () => $('#lightbox').hidden = true);

$$('#tabs .tab').forEach(btn => btn.addEventListener('click', () => {
  $$('#tabs .tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  state.tab = btn.dataset.tab;
  load();
}));

$$('#reason-filters input').forEach(cb => cb.addEventListener('change', () => {
  if (cb.checked) state.reasons.add(cb.value);
  else state.reasons.delete(cb.value);
  render();
}));

$('#blur-threshold').addEventListener('input', (e) => {
  state.blurThreshold = Number(e.target.value);
  $('#blur-value').textContent = state.blurThreshold;
});

$('#rerun-rules').addEventListener('click', async () => {
  await api('/api/rules', {
    method: 'POST',
    body: JSON.stringify({ blur_threshold: state.blurThreshold }),
  });
  load();
});

$('#btn-primary').addEventListener('click', async () => {
  if (!state.selected.size) return;
  const ids = Array.from(state.selected);
  const path = state.tab === 'trashed' ? '/api/restore' : '/api/trash';
  await api(path, { method: 'POST', body: JSON.stringify({ ids }) });
  load();
});

$('#btn-secondary').addEventListener('click', async () => {
  if (!confirm('清空回收区将永久删除这些文件,不可恢复。确定?')) return;
  await api('/api/purge', { method: 'POST', body: JSON.stringify({}) });
  load();
});

$('#btn-select-all').addEventListener('click', () => {
  const filtered = state.tab === 'candidates'
    ? state.photos.filter(p => state.reasons.has(p.verdict_reason))
    : state.photos;
  for (const p of filtered) state.selected.add(p.id);
  render();
});

$('#btn-clear').addEventListener('click', () => {
  state.selected.clear();
  render();
});

load();
```

- [ ] **Step 4: End-to-end sanity check (manual)**

Prepare a test library and run the server:

```
mkdir -p /tmp/picpic-e2e
cp path/to/some/photos/*.jpg /tmp/picpic-e2e/  # or use test fixtures
.venv/bin/picpic all /tmp/picpic-e2e
.venv/bin/picpic serve /tmp/picpic-e2e --no-open
```

Expected:
- Terminal prints scan/analyze/rules reports.
- Browser at `http://127.0.0.1:8765/` shows three tabs.
- Candidate tab shows any screenshot/blurry/dup photos with reason badges.
- Clicking selects; "移入回收区" moves them to trash tab.
- Trash tab shows moved items; "还原选中" moves them back; "清空回收区" prompts a confirm and only then deletes.

If any of the above fails, fix inline before committing.

- [ ] **Step 5: Commit**

```
git add src/picpic/web/static/
git commit -m "feat(web): single-page review UI (3 tabs, thumbnails, trash flow)"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §3 Architecture: scan / analyze / rules / UI as independent steps | Tasks 3, 8, 10, 13, 14 (via CLI Task 9) |
| §4 Data model: `photos` table with all named columns + indexes | Task 2 |
| §5 Detectors: exact-dup (file_hash), similar (phash+union-find), blur (Laplacian), screenshot (EXIF+resolutions) | Tasks 4, 5, 6, 7 |
| §5 Similar images NEVER auto-marked | Task 10 rule 3 explicitly excludes `dup_group` |
| §5 Blur threshold configurable, not hard-coded verdict | Task 10 param + Task 13 `/api/rules` + Task 14 slider |
| §5 Screenshot judgement includes web-saved images (no camera_model) | Task 4 `is_screenshot` short-circuits on `camera_model is None` |
| §6 UI: 3 tabs, reason badges, click-to-enlarge, multi-select, similar-group review, trash+restore, purge with confirm | Tasks 13, 14 |
| §6 Thumbnails (not raw originals in grid) | Task 12, wired in `/thumb/{id}` |
| §7 Rules as data (independent step, cheap to rerun) | Task 10 (`apply_rules` idempotent, resets `verdict` first) |
| §8 Safety: originals read-only; delete = move; purge is separate | Task 11 is the only mover; Task 13's purge route + Task 14's confirm modal |
| §9 Phase 1 = MVP w/o CLIP | This whole plan; no CLIP module |
| §11 Tech stack: Python, SQLite, Pillow, opencv, imagehash, FastAPI | Task 1 dependencies |

No spec section unaddressed.

**2. Placeholder scan**

- No "TODO" / "TBD" / "implement later" in any step.
- Every code step contains actual runnable code.
- Every command step contains the actual command and expected output.
- Task 3 Step 3 initially had a dead-code line I called out and provided the cleaned-up version to write; the "cleaned-up version" block is what the engineer should actually write. This is explicit, not a placeholder.

**3. Type / name consistency**

Cross-checked names used across tasks:

- `open_db(path)` → used by every task that touches SQLite. ✓
- `scan_library(root, conn) → ScanReport` (Task 3) → called by CLI Task 9. ✓
- `run_exif_pass` / `run_hash_pass` / `run_similarity_pass` / `run_blur_pass` (Tasks 4–7) → all called by `analyze_all` in Task 8. ✓
- `analyze_all(conn) → AnalyzeReport` → called by CLI Task 9. ✓
- `apply_rules(conn, blur_threshold=...)`, `DEFAULT_BLUR_THRESHOLD`, `RulesReport` (Task 10) → called by CLI Task 9 and `/api/rules` in Task 13. ✓
- `trash_photos` / `restore_photos` / `purge_trash` (Task 11) → called by web routes in Task 13. ✓
- `ensure_thumb`, `thumb_path` (Task 12) → called in `/thumb/{id}` in Task 13. ✓
- `create_app(library) → FastAPI`, `serve(library, host, port, open_browser)` (Task 13) → `serve` called by CLI Task 9. ✓
- Verdict values `keep` / `trash_candidate`, statuses `active` / `trashed`, reasons `screenshot` / `blurry` / `exact_dup` → same strings used in Global Constraints, DB CHECK constraint (Task 2), `apply_rules` (Task 10), and web filters (Task 13). ✓
- `TRASH_DIRNAME = "_picpic_trash"` (Task 11) — matches ignored dir in `scan_library` (Task 3). ✓
- `THUMB_DIRNAME = ".picpic_thumbs"` (Task 12) — matches ignored dir in `scan_library` (Task 3). ✓

No inconsistencies found.

---

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-06-picpic-mvp.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?



