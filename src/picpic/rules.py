from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field


DEFAULT_BLUR_THRESHOLD = 100.0


@dataclass
class RulesReport:
    kept: int = 0
    candidates: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    unanalyzed: int = 0


def apply_rules(
    conn: sqlite3.Connection,
    blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
) -> RulesReport:
    # Warn about unanalyzed photos
    unanalyzed = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE status='active' "
        "AND (is_screenshot IS NULL OR blur_score IS NULL OR file_hash IS NULL)"
    ).fetchone()[0]
    if unanalyzed:
        print(
            f"warning: {unanalyzed} photos not fully analyzed — "
            "run 'picpic analyze' first for reliable verdicts",
            file=sys.stderr,
        )

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
    return RulesReport(
        kept=kept,
        candidates=candidates,
        by_reason=dict(counts),
        unanalyzed=unanalyzed,
    )
