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
