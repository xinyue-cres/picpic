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
