from __future__ import annotations

import pathlib
import sqlite3
import sys
from dataclasses import dataclass

from ..categories import (
    CATEGORIES_FILENAME,
    CategoriesError,
    write_default,
    yaml_available,
)
from . import clip as clip_mod
from .blur import run_blur_pass
from .clip import ClipUnavailable
from .exif import run_exif_pass
from .hashes import run_hash_pass
from .similar import run_similarity_pass


@dataclass
class AnalyzeReport:
    exif: int
    hashes: int
    similar: int
    blur: int
    clip: clip_mod.ClipReport | None = None


def _ensure_categories(library: pathlib.Path) -> bool:
    """Return True if categories.yml is ready to use, False otherwise.

    Auto-writes the default template on first run. Any error prints a
    stderr hint and returns False so the caller can skip CLIP cleanly.
    """
    if not yaml_available():
        print(
            "error: PyYAML not installed. Install with: pip install '.[clip]'",
            file=sys.stderr,
        )
        return False
    target = library / CATEGORIES_FILENAME
    if not target.exists():
        try:
            write_default(library)
            print(
                "已生成 categories.yml，可编辑后重跑 "
                "'picpic analyze <library> --clip-only --force-clip'",
                file=sys.stderr,
            )
        except (OSError, CategoriesError) as exc:
            print(
                f"note: could not write {CATEGORIES_FILENAME}: {exc}",
                file=sys.stderr,
            )
            return False
    return True


def _progress(done: int, total: int) -> None:
    pct = 100 * done // total if total else 100
    print(f"clip: [{done}/{total}] {pct}%", file=sys.stderr)


def analyze_all(
    conn: sqlite3.Connection,
    library: pathlib.Path,
    *,
    run_clip: bool = True,
    force_clip: bool = False,
    clip_only: bool = False,
) -> AnalyzeReport:
    if clip_only:
        exif = hashes = similar = blur = 0
    else:
        exif = run_exif_pass(conn)
        hashes = run_hash_pass(conn)
        similar = run_similarity_pass(conn)
        blur = run_blur_pass(conn)

    clip_report: clip_mod.ClipReport | None = None
    if run_clip:
        if clip_mod.clip_available():
            if _ensure_categories(library):
                try:
                    clip_report = clip_mod.run_clip_pass(
                        conn, library, force=force_clip, progress=_progress
                    )
                except (
                    CategoriesError,
                    ClipUnavailable,
                    FileNotFoundError,
                    OSError,
                    RuntimeError,
                    AssertionError,
                ) as exc:
                    print(
                        f"CLIP 步骤失败,Phase 1 结果已保存: {exc}",
                        file=sys.stderr,
                    )
                    clip_report = None
        else:
            print(
                "error: PyYAML not installed. Install with: pip install '.[clip]'",
                file=sys.stderr,
            )

    return AnalyzeReport(
        exif=exif, hashes=hashes, similar=similar, blur=blur, clip=clip_report
    )
