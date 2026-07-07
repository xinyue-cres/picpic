"""Slow integration tests. Require torch + open_clip installed.

Skipped by default. Run with: pytest -m slow
"""
from __future__ import annotations

import pytest

from picpic.analyze import clip as clip_mod

pytestmark = pytest.mark.slow

if not clip_mod.clip_available():
    pytest.skip("CLIP extras not installed", allow_module_level=True)


def test_load_model_returns_triple() -> None:
    model, preprocess, tokenizer = clip_mod._load_model("ViT-B-32", "openai")
    assert model is not None
    assert preprocess is not None
    assert tokenizer is not None
