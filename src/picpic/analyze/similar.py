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
