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
