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
