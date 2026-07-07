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
