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
