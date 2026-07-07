"""CLIP zero-shot classification pass.

Runs last in the analyze pipeline. Reads categories.yml, embeds each
active photo with open_clip, and writes top-k baseline-adjusted labels
into photos.clip_labels as a JSON array.

Model loading and image encoding are isolated behind _load_model /
_encode_image_batch so unit tests can monkeypatch them without touching
torch. clip_available() gates callers when [clip] extras are missing.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from ..categories import Category, load_categories


BASELINE_PROMPT = "a photo"


class ClipUnavailable(Exception):
    """Raised when [clip] extras are not installed."""


@dataclass
class ClipReport:
    total: int
    processed: int
    failed: int
    skipped: int


def clip_available() -> bool:
    return all(
        importlib.util.find_spec(m) is not None
        for m in ("torch", "open_clip")
    )


def _load_model(model: str, pretrained: str) -> tuple:
    """Load open_clip model. Returns (model, preprocess, tokenizer)."""
    import open_clip  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]

    device = (
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        else "cpu"
    )
    m, _, preprocess = open_clip.create_model_and_transforms(
        model, pretrained=pretrained
    )
    m.to(device).eval()
    tokenizer = open_clip.get_tokenizer(model)
    return (m, preprocess, tokenizer)


def _encode_text(model_bundle, prompts: list[str]):
    """Encode text prompts to normalized embeddings."""
    import torch  # type: ignore[import-not-found]

    model, _preprocess, tokenizer = model_bundle
    device = next(model.parameters()).device
    tokens = tokenizer(prompts).to(device)
    with torch.no_grad():
        emb = model.encode_text(tokens)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb


_CACHE: dict[str, Any] = {}


def _encode_image_batch(
    model_bundle, paths: list[str]
) -> list[list[float] | None]:
    """Encode a batch of images and return post-softmax scores per prompt.

    Returns one row per input path. Each row is [baseline_score,
    cat0_score, cat1_score, ...] in the same order the caller passed to
    _encode_text. Rows that failed to decode are None.

    Text embeddings must already be primed via _CACHE["text_emb"].
    Unit tests replace this whole function via monkeypatch and therefore
    do not touch torch or _CACHE.
    """
    import torch  # type: ignore[import-not-found]
    from PIL import Image, UnidentifiedImageError  # type: ignore[import-not-found]

    model, preprocess, _tokenizer = model_bundle
    device = next(model.parameters()).device
    tensors = []
    valid_idx: list[int] = []
    for i, p in enumerate(paths):
        try:
            img = Image.open(p).convert("RGB")
            tensors.append(preprocess(img))
            valid_idx.append(i)
        except (OSError, UnidentifiedImageError, ValueError):
            continue
    out: list[list[float] | None] = [None] * len(paths)
    if not tensors:
        return out
    batch = torch.stack(tensors).to(device)
    with torch.no_grad():
        img_emb = model.encode_image(batch)
        img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
        text_emb = _CACHE.get("text_emb")
        assert text_emb is not None, "text embeddings not primed"
        logits = 100.0 * img_emb @ text_emb.t()
        probs = logits.softmax(dim=-1).cpu().tolist()
    for local_i, global_i in enumerate(valid_idx):
        out[global_i] = probs[local_i]
    return out


def _score_to_labels(
    scores: list[float],
    categories: list[Category],
    top_k: int,
) -> list[dict[str, Any]]:
    """scores[0] is baseline; scores[1:] map to categories in order."""
    baseline = scores[0]
    adjusted = [(cat.name, scores[1 + i] - baseline) for i, cat in enumerate(categories)]
    adjusted = [(n, s) for n, s in adjusted if s > 0]
    adjusted.sort(key=lambda x: x[1], reverse=True)
    top = adjusted[:top_k]
    return [{"name": n, "score": round(float(s), 4)} for n, s in top]


def run_clip_pass(
    conn: sqlite3.Connection,
    library: pathlib.Path,
    *,
    force: bool = False,
    batch_size: int = 32,
    progress: Callable[[int, int], None] | None = None,
) -> ClipReport:
    cfg = load_categories(library)
    where = "status='active'" + ("" if force else " AND clip_labels IS NULL")
    rows = conn.execute(
        f"SELECT id, path FROM photos WHERE {where} ORDER BY id"
    ).fetchall()
    total = len(rows)

    total_active = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE status='active'"
    ).fetchone()[0]

    if total == 0:
        return ClipReport(
            total=0, processed=0, failed=0, skipped=total_active,
        )

    model_bundle = _load_model(cfg.model, cfg.pretrained)
    prompts = [BASELINE_PROMPT] + [c.prompt for c in cfg.categories]
    _CACHE["text_emb"] = _encode_text(model_bundle, prompts)

    processed = 0
    failed = 0
    done = 0
    try:
        for start in range(0, total, batch_size):
            chunk = rows[start : start + batch_size]
            paths = [r["path"] for r in chunk]
            scored = _encode_image_batch(model_bundle, paths)
            for row, s in zip(chunk, scored):
                if s is None:
                    conn.execute(
                        "UPDATE photos SET clip_labels=? WHERE id=?",
                        ("[]", row["id"]),
                    )
                    failed += 1
                else:
                    labels = _score_to_labels(s, cfg.categories, cfg.top_k)
                    conn.execute(
                        "UPDATE photos SET clip_labels=? WHERE id=?",
                        (json.dumps(labels, ensure_ascii=False), row["id"]),
                    )
                    processed += 1
            conn.commit()
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    finally:
        _CACHE.clear()

    skipped = total_active - (processed + failed)
    return ClipReport(
        total=total, processed=processed, failed=failed, skipped=max(0, skipped),
    )
