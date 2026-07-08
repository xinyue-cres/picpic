from __future__ import annotations

import pathlib
import shutil
import sqlite3
import sys
from datetime import datetime, timezone


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
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
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
            conn.commit()
            continue
        dest = _unique_dest(trash / f"{r['id']}__{src.name}")
        shutil.move(str(src), str(dest))
        conn.execute(
            "UPDATE photos SET status='trashed', trashed_at=? WHERE id=?",
            (now, r["id"]),
        )
        conn.commit()
        moved += 1
    return moved


def _find_in_trash(library: pathlib.Path, photo_id: int) -> pathlib.Path | None:
    trash = library / TRASH_DIRNAME
    if not trash.exists():
        return None
    prefix = f"{photo_id}__"
    for entry in trash.iterdir():
        if entry.name.startswith(prefix):
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
            print(
                f"warning: trash entry missing for photo {r['id']} "
                f"({r['path']}), leaving status as trashed",
                file=sys.stderr,
            )
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        if original.exists():
            dest = _unique_dest(original.with_name(
                f"{original.stem}.restored{original.suffix}"
            ))
        else:
            dest = original
        shutil.move(str(src), str(dest))
        conn.execute(
            "UPDATE photos SET status='active', trashed_at=NULL, path=? "
            "WHERE id=?",
            (str(dest), r["id"]),
        )
        conn.commit()
        restored += 1
    return restored


def purge_trash(
    conn: sqlite3.Connection,
    library: pathlib.Path,
) -> int:
    trash = library / TRASH_DIRNAME
    conn.execute("DELETE FROM photos WHERE status='trashed'")
    conn.commit()
    deleted = 0
    if trash.exists():
        for entry in list(trash.iterdir()):
            if entry.is_file():
                entry.unlink()
                deleted += 1
            elif entry.is_dir():
                shutil.rmtree(entry)
    return deleted
