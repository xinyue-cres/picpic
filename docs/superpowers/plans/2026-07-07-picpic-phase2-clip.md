# picpic Phase 2 — CLIP 语义分类 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 picpic 增加本地 CLIP 零样本语义分类,让用户在 `categories.yml` 里用自然语言写类别,pipeline 打标签,网页新增"标签"页供人工浏览挑删。

**Architecture:** CLIP 作为 pipeline 第 5 步跑在 exif/hashes/similar/blur 之后,结果写入已有的 `clip_labels` 列。分类结果**不参与 `verdict`**,`rules.py` 与 `trash.py` 完全不动。`open_clip` + PyTorch 是**可选 extras**,不装也能跑 Phase 1 全流程。所有 ML 内部函数(模型加载、批推理)通过命名 seam (`_load_model` / `_encode_image_batch`) 隔离,单元测试用 `monkeypatch` 替换;真模型测试单独 slow marker。

**Tech Stack:** Python 3.12+, PyYAML(可选)、`open_clip_torch`(可选)、`torch`(可选)、`pillow-heif`(可选)、pytest 8.x with markers。

## Global Constraints

- Python `>=3.12`,原图**全生命周期只读**,任何代码路径不得写、改名、删原图。
- 仅 `src/picpic/trash.py` 允许移动文件;`purge_trash` 是唯一物理删除函数。**Phase 2 不改这些不变量**。
- SQLite 是唯一真相源,UI 不扫文件系统;`SCHEMA_VERSION` 保持 `1`,**不改 schema**,只往已有的 `clip_labels TEXT` 列写。
- CLIP 结果**不写 `verdict`**;`rules.py` 与 `trash.py` **本 Phase 2 计划中不得修改**。
- 全本地运行,无网络调用、无遥测。唯一例外是首次运行 CLIP 时从 HuggingFace 下载模型权重。
- Path traversal 防御继承 Phase 1:`/photo/{id}`、`/thumb/{id}` 已用 `_within_library()` 校验。**新路由不得引入未校验的文件返回**(本 plan 新增的 `/api/labels` 与 `/api/photos?tab=labeled` 都不返回文件,不涉及)。
- CLI 打开 DB 前必须 `_require_library()` 校验 `library.exists() and is_dir()`。
- `categories.yml` 位置固定:`<library>/categories.yml`。
- CLIP 模型固定 `open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')`;基线 anchor 硬编码 `"a photo"`,不写入 yml。
- `clip_labels` 存 JSON 字符串,数组按 baseline-adjusted score 降序;空数组用字符串 `"[]"`。
- `[clip]` extras 未装时,`analyze` 跳过 CLIP 步骤但不报错,给用户 stderr 提示;`categories` 命令未装时报错退出。
- 测试:默认 `pytest` 不下模型;标 `@pytest.mark.slow` 的集成测试通过 `pytest -m slow` 手动跑。

---

## Task 1: `pyproject.toml` — 添加 `[clip]` extras 与 pytest markers

**Files:**
- Modify: `pyproject.toml`(整个文件)
- Test: 无独立测试(纯配置变更,靠 Task 2/3 的 test 隐式验证)

**Interfaces:**
- Consumes: 无
- Produces:
  - `pip install '.[clip]'` 拉入 `torch>=2.0`, `open_clip_torch>=2.24`, `pillow-heif>=0.15`, `PyYAML>=6.0`
  - pytest 识别 `slow` marker,不再对未注册 marker 报警

- [ ] **Step 1: 重写 `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "picpic"
version = "0.1.0"
description = "Local, privacy-preserving photo triage tool"
requires-python = ">=3.12"
dependencies = [
  "Pillow>=10.0",
  "imagehash>=4.3",
  "opencv-python-headless>=4.8",
  "fastapi>=0.110",
  "uvicorn>=0.29",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx2>=2.5"]
clip = [
  "torch>=2.0",
  "open_clip_torch>=2.24",
  "pillow-heif>=0.15",
  "PyYAML>=6.0",
]

[project.scripts]
picpic = "picpic.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
picpic = ["web/static/*"]

[tool.pytest.ini_options]
markers = [
  "slow: requires downloading CLIP model weights (~350MB); run with -m slow",
]
```

- [ ] **Step 2: 校验 pyproject.toml 语法**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`
Expected: 无输出、退出码 0

- [ ] **Step 3: 校验 pytest 识别 marker**

Run: `pytest --collect-only -q 2>&1 | tail -3`
Expected: 收集到 Phase 1 全部测试(52+),无 marker 警告

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add [clip] extras and slow pytest marker

Optional CLIP extras (torch, open_clip_torch, pillow-heif, PyYAML) for
Phase 2 semantic classification. New 'slow' marker isolates model-download
integration tests from default suite.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 2: `categories.py` — YAML 配置模块

**Files:**
- Create: `src/picpic/categories.py`
- Test: `tests/test_categories.py`

**Interfaces:**
- Consumes: `pyproject.toml` 里 `[clip]` extras 提供 `yaml` 包(可能未装)
- Produces:
  - `CATEGORIES_FILENAME = "categories.yml"`(常量)
  - `DEFAULT_TEMPLATE: str`(默认 yml 文本)
  - `class CategoriesError(Exception)`
  - `@dataclass class Category(name: str, prompt: str)`
  - `@dataclass class CategoriesConfig(version: int, model: str, pretrained: str, top_k: int, categories: list[Category])`
  - `def yaml_available() -> bool`
  - `def load_categories(library: pathlib.Path) -> CategoriesConfig` — 文件不存在抛 `FileNotFoundError`;格式错抛 `CategoriesError`;PyYAML 未装抛 `CategoriesError`
  - `def write_default(library: pathlib.Path) -> pathlib.Path` — 已存在抛 `FileExistsError`;PyYAML 未装抛 `CategoriesError`
  - `def check_categories(library: pathlib.Path) -> list[str]` — 空 list = 无问题

- [ ] **Step 1: 写失败测试 `tests/test_categories.py`**

```python
from __future__ import annotations

import pathlib

import pytest

from picpic.categories import (
    CATEGORIES_FILENAME,
    CategoriesError,
    check_categories,
    load_categories,
    write_default,
    yaml_available,
)

pytestmark = pytest.mark.skipif(
    not yaml_available(), reason="PyYAML not installed"
)


def test_write_default_creates_file(tmp_path: pathlib.Path) -> None:
    path = write_default(tmp_path)
    assert path == tmp_path / CATEGORIES_FILENAME
    assert path.exists()


def test_write_default_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    with pytest.raises(FileExistsError):
        write_default(tmp_path)


def test_load_default_template(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    cfg = load_categories(tmp_path)
    assert cfg.version == 1
    assert cfg.model == "ViT-B-32"
    assert cfg.pretrained == "openai"
    assert cfg.top_k == 3
    assert len(cfg.categories) >= 3
    names = [c.name for c in cfg.categories]
    assert len(names) == len(set(names))  # unique


def test_load_missing_file_raises(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_categories(tmp_path)


def _write(tmp_path: pathlib.Path, body: str) -> None:
    (tmp_path / CATEGORIES_FILENAME).write_text(body, encoding="utf-8")


def test_load_rejects_wrong_version(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 2\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n  - {name: a, prompt: b}\n")
    with pytest.raises(CategoriesError, match="version"):
        load_categories(tmp_path)


def test_load_rejects_empty_categories(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories: []\n")
    with pytest.raises(CategoriesError, match="categories"):
        load_categories(tmp_path)


def test_load_rejects_duplicate_names(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {name: a, prompt: p1}\n"
        "  - {name: a, prompt: p2}\n",
    )
    with pytest.raises(CategoriesError, match="duplicate"):
        load_categories(tmp_path)


def test_load_rejects_empty_prompt(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {name: a, prompt: ''}\n",
    )
    with pytest.raises(CategoriesError, match="prompt"):
        load_categories(tmp_path)


def test_load_rejects_missing_name(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 1\ncategories:\n"
        "  - {prompt: hello}\n",
    )
    with pytest.raises(CategoriesError, match="name"):
        load_categories(tmp_path)


def test_load_rejects_top_k_out_of_range(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "version: 1\nmodel: x\npretrained: y\ntop_k: 5\ncategories:\n"
        "  - {name: a, prompt: p}\n"
        "  - {name: b, prompt: q}\n",
    )
    with pytest.raises(CategoriesError, match="top_k"):
        load_categories(tmp_path)


def test_check_ok_on_default(tmp_path: pathlib.Path) -> None:
    write_default(tmp_path)
    assert check_categories(tmp_path) == []


def test_check_lists_problems(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, "version: 2\ncategories: []\n")
    problems = check_categories(tmp_path)
    assert problems  # non-empty
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/test_categories.py -v`
Expected: FAIL(`ModuleNotFoundError: picpic.categories`)

- [ ] **Step 3: 创建 `src/picpic/categories.py`**

```python
"""User-editable CLIP categories config.

Reads <library>/categories.yml. YAML support is optional — if PyYAML is
missing, callers should check yaml_available() first. All validation errors
raise CategoriesError with a short, actionable message.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

try:
    import yaml  # type: ignore[import-not-found]
    _YAML = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    _YAML = False


CATEGORIES_FILENAME = "categories.yml"


class CategoriesError(Exception):
    """Raised for any validation or parse error in categories.yml."""


@dataclass
class Category:
    name: str
    prompt: str


@dataclass
class CategoriesConfig:
    version: int
    model: str
    pretrained: str
    top_k: int
    categories: list[Category] = field(default_factory=list)


DEFAULT_TEMPLATE = """\
# picpic 语义分类配置。改完可跑:
#   picpic analyze <library> --clip-only --force-clip
version: 1
model: ViT-B-32
pretrained: openai
top_k: 3
categories:
  - name: 收据
    prompt: "a photo of a receipt or invoice"
  - name: 截图
    prompt: "a screenshot of a mobile phone or computer screen"
  - name: 食物
    prompt: "a photo of food or a meal"
  - name: 风景
    prompt: "a landscape photograph, outdoor scenery"
  - name: 宠物
    prompt: "a photo of a pet, a cat or a dog"
  - name: 人像
    prompt: "a portrait photo of a person"
  - name: 文档
    prompt: "a photo of a document or paper page"
"""


def yaml_available() -> bool:
    return _YAML


def _path(library: pathlib.Path) -> pathlib.Path:
    return library / CATEGORIES_FILENAME


def write_default(library: pathlib.Path) -> pathlib.Path:
    if not _YAML:
        raise CategoriesError(
            "PyYAML not installed. Install with: pip install '.[clip]'"
        )
    target = _path(library)
    if target.exists():
        raise FileExistsError(str(target))
    library.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target


def load_categories(library: pathlib.Path) -> CategoriesConfig:
    if not _YAML:
        raise CategoriesError(
            "PyYAML not installed. Install with: pip install '.[clip]'"
        )
    target = _path(library)
    if not target.exists():
        raise FileNotFoundError(str(target))
    return _parse(target.read_text(encoding="utf-8"))


def _parse(text: str) -> CategoriesConfig:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CategoriesError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise CategoriesError("top-level must be a mapping")
    version = raw.get("version")
    if version != 1:
        raise CategoriesError(f"unsupported version: {version!r} (expected 1)")
    for key in ("model", "pretrained"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise CategoriesError(f"{key} must be a non-empty string")
    top_k = raw.get("top_k")
    if not isinstance(top_k, int) or top_k < 1:
        raise CategoriesError(f"top_k must be a positive int, got {top_k!r}")
    cats_raw = raw.get("categories")
    if not isinstance(cats_raw, list) or not cats_raw:
        raise CategoriesError("categories must be a non-empty list")
    cats: list[Category] = []
    seen: set[str] = set()
    for i, item in enumerate(cats_raw):
        if not isinstance(item, dict):
            raise CategoriesError(f"categories[{i}] must be a mapping")
        name = item.get("name")
        prompt = item.get("prompt")
        if not isinstance(name, str) or not name:
            raise CategoriesError(f"categories[{i}]: name must be a non-empty string")
        if not isinstance(prompt, str) or not prompt.strip():
            raise CategoriesError(f"categories[{i}]: prompt must be a non-empty string")
        if name in seen:
            raise CategoriesError(f"duplicate category name: {name!r}")
        seen.add(name)
        cats.append(Category(name=name, prompt=prompt))
    if top_k > len(cats):
        raise CategoriesError(
            f"top_k={top_k} exceeds number of categories ({len(cats)})"
        )
    return CategoriesConfig(
        version=version,
        model=raw["model"],
        pretrained=raw["pretrained"],
        top_k=top_k,
        categories=cats,
    )


def check_categories(library: pathlib.Path) -> list[str]:
    try:
        load_categories(library)
        return []
    except FileNotFoundError:
        return [f"{CATEGORIES_FILENAME} not found"]
    except CategoriesError as exc:
        return [str(exc)]
```

- [ ] **Step 4: Run tests, expect green**

Run: `pytest tests/test_categories.py -v`
Expected: 12 passed(若 PyYAML 未装则全 skip)

- [ ] **Step 5: Commit**

```bash
git add src/picpic/categories.py tests/test_categories.py
git commit -m "feat(categories): YAML-driven categories config

New categories.py module for reading <library>/categories.yml. Provides
load/write_default/check APIs plus schema validation with clear errors.
PyYAML is an optional dep — module gates on yaml_available() so Phase 1
users without [clip] extras aren't affected.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 3: `analyze/clip.py` — CLIP pass 逻辑(monkeypatched 单元测试 + slow 集成测试)

**Files:**
- Create: `src/picpic/analyze/clip.py`
- Test: `tests/test_clip_pass.py`
- Test: `tests/test_clip_integration.py`(slow marker)

**Interfaces:**
- Consumes:
  - `picpic.categories.load_categories(library) -> CategoriesConfig`
  - `picpic.categories.Category(name, prompt)`
  - `picpic.categories.yaml_available() -> bool`
  - SQLite `photos` table columns: `id`, `path`, `status`, `clip_labels`
- Produces:
  - `BASELINE_PROMPT = "a photo"`(硬编码基线)
  - `class ClipUnavailable(Exception)`
  - `@dataclass class ClipReport(total: int, processed: int, failed: int, skipped: int)`
  - `def clip_available() -> bool`
  - `def _load_model(model: str, pretrained: str) -> tuple`(测试 monkeypatch 用)
  - `def _encode_text(model_bundle, prompts: list[str])`(测试 monkeypatch 用)
  - `def _encode_image_batch(model_bundle, _preprocess_unused, paths: list[str]) -> list[list[float] | None]`
    - 返回 per-image per-prompt scores(baseline 在下标 0,categories 依原顺序);decode 失败返回 None
    - 测试 monkeypatch 用;真实实现读 `_CACHE["text_emb"]` 做矩阵乘
  - `def run_clip_pass(conn, library, *, force=False, batch_size=32, progress=None) -> ClipReport`

- [ ] **Step 1: 写失败测试 `tests/test_clip_pass.py`**

```python
from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest

from picpic.categories import CategoriesConfig, Category, yaml_available
from picpic.db import open_db

if not yaml_available():
    pytest.skip("PyYAML not installed", allow_module_level=True)

from picpic.analyze import clip as clip_mod  # noqa: E402


def _seed_photos(conn: sqlite3.Connection, library: pathlib.Path, n: int) -> list[int]:
    ids: list[int] = []
    for i in range(n):
        p = library / f"img_{i}.jpg"
        p.write_bytes(b"stub")
        cur = conn.execute(
            "INSERT INTO photos(path, status) VALUES(?, 'active')", (str(p),)
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def _fixed_cfg() -> CategoriesConfig:
    return CategoriesConfig(
        version=1,
        model="ViT-B-32",
        pretrained="openai",
        top_k=2,
        categories=[
            Category("cat_a", "prompt a"),
            Category("cat_b", "prompt b"),
            Category("cat_c", "prompt c"),
        ],
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cfg: CategoriesConfig | None = None,
    image_scores: list[list[float]] | None = None,
    decode_fail_at: set[int] | None = None,
):
    call_state = {"decode_count": 0}
    scores = image_scores or []
    fail = decode_fail_at or set()

    def fake_load_categories(_library):
        return cfg or _fixed_cfg()

    def fake_load_model(_model, _pretrained):
        return ("FAKE_MODEL", "FAKE_PREPROC", "FAKE_TOKENIZER")

    def fake_encode_text(_bundle, _prompts):
        return "FAKE_TEXT_EMB"

    def fake_encode_image_batch(_bundle, _preproc, paths):
        out: list[list[float] | None] = []
        for _ in paths:
            idx = call_state["decode_count"]
            call_state["decode_count"] += 1
            if idx in fail:
                out.append(None)
            else:
                out.append(scores[idx])
        return out

    monkeypatch.setattr(clip_mod, "load_categories", fake_load_categories)
    monkeypatch.setattr(clip_mod, "_load_model", fake_load_model)
    monkeypatch.setattr(clip_mod, "_encode_text", fake_encode_text)
    monkeypatch.setattr(clip_mod, "_encode_image_batch", fake_encode_image_batch)


def test_run_clip_pass_writes_labels(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    _install_fakes(
        monkeypatch,
        image_scores=[
            [0.10, 0.60, 0.20, 0.10],  # cat_a wins
            [0.20, 0.15, 0.55, 0.10],  # cat_b wins
        ],
    )
    report = clip_mod.run_clip_pass(conn, tmp_path)
    assert report.total == 2
    assert report.processed == 2
    assert report.failed == 0
    row0 = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    labels0 = json.loads(row0["clip_labels"])
    assert labels0[0]["name"] == "cat_a"
    assert labels0[0]["score"] > 0
    assert len(labels0) <= 2


def test_run_clip_pass_is_idempotent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 1)
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r1 = clip_mod.run_clip_pass(conn, tmp_path)
    assert r1.processed == 1
    r2 = clip_mod.run_clip_pass(conn, tmp_path)
    assert r2.processed == 0
    assert r2.skipped == 1


def test_run_clip_pass_force_reruns(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 1)
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    clip_mod.run_clip_pass(conn, tmp_path)
    # second call with force=True; fakes reset call_state at install time,
    # but the test only creates one row so index 0 is used again
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r = clip_mod.run_clip_pass(conn, tmp_path, force=True)
    assert r.processed == 1
    assert r.skipped == 0


def test_run_clip_pass_decode_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    _install_fakes(
        monkeypatch,
        image_scores=[[0.1, 0.6, 0.2, 0.1], [0.2, 0.3, 0.4, 0.1]],
        decode_fail_at={0},
    )
    report = clip_mod.run_clip_pass(conn, tmp_path)
    assert report.processed == 1
    assert report.failed == 1
    bad = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    assert bad["clip_labels"] == "[]"
    good = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[1],)).fetchone()
    labels = json.loads(good["clip_labels"])
    assert labels


def test_run_clip_pass_all_below_baseline(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 1)
    _install_fakes(
        monkeypatch,
        image_scores=[[0.9, 0.02, 0.03, 0.05]],  # baseline dominates
    )
    clip_mod.run_clip_pass(conn, tmp_path)
    row = conn.execute("SELECT clip_labels FROM photos WHERE id=?", (ids[0],)).fetchone()
    assert row["clip_labels"] == "[]"


def test_run_clip_pass_batching(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    _seed_photos(conn, tmp_path, 5)
    scores = [[0.1, 0.6, 0.2, 0.1]] * 5
    _install_fakes(monkeypatch, image_scores=scores)
    progress_calls: list[tuple[int, int]] = []
    r = clip_mod.run_clip_pass(
        conn, tmp_path, batch_size=2,
        progress=lambda d, t: progress_calls.append((d, t)),
    )
    assert r.processed == 5
    assert len(progress_calls) == 3  # 2 + 2 + 1
    assert progress_calls[-1] == (5, 5)


def test_run_clip_pass_skips_trashed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = open_db(tmp_path / "picpic.db")
    ids = _seed_photos(conn, tmp_path, 2)
    conn.execute("UPDATE photos SET status='trashed' WHERE id=?", (ids[1],))
    conn.commit()
    _install_fakes(monkeypatch, image_scores=[[0.1, 0.6, 0.2, 0.1]])
    r = clip_mod.run_clip_pass(conn, tmp_path)
    assert r.total == 1
    assert r.processed == 1
    trashed = conn.execute(
        "SELECT clip_labels FROM photos WHERE id=?", (ids[1],)
    ).fetchone()
    assert trashed["clip_labels"] is None


def test_clip_available_flag() -> None:
    assert isinstance(clip_mod.clip_available(), bool)
```

- [ ] **Step 2: 写失败集成测试 `tests/test_clip_integration.py`**

```python
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
```

- [ ] **Step 3: Run, expect FAIL**

Run: `pytest tests/test_clip_pass.py -v`
Expected: FAIL(`ModuleNotFoundError: picpic.analyze.clip`)

- [ ] **Step 4: 创建 `src/picpic/analyze/clip.py`**

```python
"""CLIP zero-shot classification pass.

Runs last in the analyze pipeline. Reads categories.yml, embeds each
active photo with open_clip, and writes top-k baseline-adjusted labels
into photos.clip_labels as a JSON array.

Model loading and image encoding are isolated behind _load_model /
_encode_image_batch so unit tests can monkeypatch them without touching
torch. clip_available() gates callers when [clip] extras are missing.
"""

from __future__ import annotations

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
    try:
        import torch  # noqa: F401
        import open_clip  # noqa: F401
    except ImportError:
        return False
    return True


def _load_model(model: str, pretrained: str):
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
    model_bundle, _preprocess_unused, paths: list[str]
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
            scored = _encode_image_batch(model_bundle, None, paths)
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
```

- [ ] **Step 5: Run unit tests, expect green**

Run: `pytest tests/test_clip_pass.py -v`
Expected: 8 passed(若 PyYAML 未装则整个模块 skip)

- [ ] **Step 6: Run slow integration test — expect skip**

Run: `pytest tests/test_clip_integration.py -v`
Expected: skipped(默认不带 `-m slow`,module-level `pytest.skip` 兜底)

- [ ] **Step 7: Full test suite still green**

Run: `pytest`
Expected: Phase 1 全部测试 + 新的 Phase 2 单元测试通过

- [ ] **Step 8: Commit**

```bash
git add src/picpic/analyze/clip.py tests/test_clip_pass.py tests/test_clip_integration.py
git commit -m "feat(analyze): CLIP zero-shot classification pass

analyze/clip.py runs open_clip ViT-B/32 on active photos and writes
top-k baseline-adjusted labels to clip_labels as JSON. Idempotent by
default (skips already-labeled photos); force=True reruns all. Model
load and image encode isolated behind _load_model / _encode_image_batch
seams so unit tests monkeypatch them without touching torch. Real-model
integration test gated behind pytest -m slow.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 4: `analyze/runner.py` 与 CLI — 集成 CLIP + `--no-clip` / `--clip-only` / `--force-clip`

**Files:**
- Modify: `src/picpic/analyze/runner.py`(全文重写)
- Modify: `src/picpic/cli.py`(`_cmd_analyze` 与 `main()` parser)
- Test: `tests/test_analyze_runner.py`(追加)
- Test: `tests/test_cli.py`(追加)

**Interfaces:**
- Consumes:
  - `picpic.analyze.clip.run_clip_pass(conn, library, *, force, batch_size, progress) -> ClipReport`
  - `picpic.analyze.clip.clip_available() -> bool`
  - `picpic.analyze.clip.ClipReport`
  - `picpic.categories.yaml_available()`, `picpic.categories.write_default(library)`, `picpic.categories.CATEGORIES_FILENAME`, `picpic.categories.CategoriesError`
- Produces:
  - `AnalyzeReport` 新增字段 `clip: ClipReport | None`
  - `def analyze_all(conn, library: pathlib.Path, *, run_clip: bool = True, force_clip: bool = False, clip_only: bool = False) -> AnalyzeReport`
  - CLI: `picpic analyze <lib> [--no-clip] [--clip-only] [--force-clip]`;`picpic all` 也接受同样的 flags

- [ ] **Step 1: 追加失败测试到 `tests/test_analyze_runner.py`**

```python
# --- appended to end of file ---
import pytest

from picpic.analyze import clip as clip_mod
from picpic.analyze.clip import ClipReport
from picpic.analyze.runner import analyze_all
from picpic.categories import yaml_available
from picpic.db import open_db


def _install_clip_stub(monkeypatch, *, available=True, report=None):
    monkeypatch.setattr(clip_mod, "clip_available", lambda: available)

    def fake_run(conn, library, *, force=False, batch_size=32, progress=None):
        return report or ClipReport(total=0, processed=0, failed=0, skipped=0)

    monkeypatch.setattr(clip_mod, "run_clip_pass", fake_run)


def test_analyze_all_includes_clip_when_available(tmp_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True, report=ClipReport(1, 1, 0, 0))
    report = analyze_all(conn, tmp_path)
    assert report.clip is not None
    assert report.clip.processed == 1


def test_analyze_all_skips_clip_when_unavailable(tmp_path, monkeypatch):
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=False)
    report = analyze_all(conn, tmp_path)
    assert report.clip is None


def test_analyze_all_no_clip_flag(tmp_path, monkeypatch):
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True)
    report = analyze_all(conn, tmp_path, run_clip=False)
    assert report.clip is None


def test_analyze_all_clip_only_skips_others(tmp_path, monkeypatch):
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    conn = open_db(tmp_path / "picpic.db")
    _install_clip_stub(monkeypatch, available=True, report=ClipReport(3, 3, 0, 0))
    report = analyze_all(conn, tmp_path, clip_only=True)
    assert report.exif == 0
    assert report.hashes == 0
    assert report.similar == 0
    assert report.blur == 0
    assert report.clip.processed == 3
```

- [ ] **Step 2: 追加失败 CLI 测试到 `tests/test_cli.py`**

```python
# --- appended to end of file ---
import pytest


def test_cli_analyze_no_clip_flag(tmp_path, monkeypatch):
    from picpic.analyze import clip as clip_mod
    from picpic.analyze.clip import ClipReport
    called = {"n": 0}

    def fake_run(*a, **kw):
        called["n"] += 1
        return ClipReport(0, 0, 0, 0)

    monkeypatch.setattr(clip_mod, "clip_available", lambda: True)
    monkeypatch.setattr(clip_mod, "run_clip_pass", fake_run)
    from picpic.cli import main
    rc = main(["analyze", str(tmp_path), "--no-clip"])
    assert rc == 0
    assert called["n"] == 0


def test_cli_analyze_clip_only_flag(tmp_path, monkeypatch):
    from picpic.categories import yaml_available
    if not yaml_available():
        pytest.skip("PyYAML not installed")
    from picpic.analyze import clip as clip_mod, exif as exif_mod
    from picpic.analyze.clip import ClipReport
    exif_calls = {"n": 0}

    def fake_exif(_conn):
        exif_calls["n"] += 1
        return 0

    monkeypatch.setattr(clip_mod, "clip_available", lambda: True)
    monkeypatch.setattr(
        clip_mod, "run_clip_pass",
        lambda *a, **kw: ClipReport(0, 0, 0, 0),
    )
    monkeypatch.setattr(exif_mod, "run_exif_pass", fake_exif)
    from picpic.cli import main
    rc = main(["analyze", str(tmp_path), "--clip-only"])
    assert rc == 0
    assert exif_calls["n"] == 0
```

- [ ] **Step 3: Run tests, expect FAIL**

Run: `pytest tests/test_analyze_runner.py tests/test_cli.py -v`
Expected: 新增测试 FAIL(`analyze_all` 缺 `library` 参数 / `--no-clip` 未知)

- [ ] **Step 4: 重写 `src/picpic/analyze/runner.py`**

```python
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
            "note: PyYAML not installed; CLIP skipped. "
            "Install extras: pip install '.[clip]'",
            file=sys.stderr,
        )
        return False
    target = library / CATEGORIES_FILENAME
    if not target.exists():
        try:
            write_default(library)
            print(
                f"note: wrote default {CATEGORIES_FILENAME}. "
                f"Edit it, then re-run: picpic analyze <lib> --clip-only --force-clip",
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
                except CategoriesError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    clip_report = None
        else:
            print(
                "note: CLIP extras not installed; skipping semantic classification. "
                "Install with: pip install '.[clip]'",
                file=sys.stderr,
            )

    return AnalyzeReport(
        exif=exif, hashes=hashes, similar=similar, blur=blur, clip=clip_report
    )
```

- [ ] **Step 5: 修改 `src/picpic/cli.py`**

将 `_cmd_analyze` 整个函数替换为:

```python
def _cmd_analyze(args) -> int:
    from .analyze.runner import analyze_all
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    conn = open_db(_db_path(library))
    try:
        report = analyze_all(
            conn,
            library,
            run_clip=not args.no_clip,
            force_clip=args.force_clip,
            clip_only=args.clip_only,
        )
    finally:
        conn.close()
    clip_line = ""
    if report.clip is not None:
        c = report.clip
        clip_line = (
            f" clip=processed:{c.processed}/failed:{c.failed}/skipped:{c.skipped}"
        )
    print(
        f"analyze: exif={report.exif} hashes={report.hashes} "
        f"similar={report.similar} blur={report.blur}{clip_line}"
    )
    return 0
```

将 `main()` 中 `for name, fn in ((...)):` 循环块整个替换为分开注册:

```python
    p = sub.add_parser("scan")
    p.add_argument("library")
    p.set_defaults(fn=_cmd_scan)

    p = sub.add_parser("analyze")
    p.add_argument("library")
    p.add_argument("--no-clip", action="store_true", help="skip CLIP pass")
    p.add_argument("--clip-only", action="store_true", help="run only CLIP")
    p.add_argument("--force-clip", action="store_true",
                   help="rerun CLIP on all photos, not just unlabeled")
    p.set_defaults(fn=_cmd_analyze)

    p = sub.add_parser("rules")
    p.add_argument("library")
    p.set_defaults(fn=_cmd_rules)

    p = sub.add_parser("all")
    p.add_argument("library")
    p.add_argument("--no-clip", action="store_true")
    p.add_argument("--clip-only", action="store_true")
    p.add_argument("--force-clip", action="store_true")
    p.set_defaults(fn=_cmd_all)
```

`_cmd_scan` / `_cmd_rules` 不读 clip flags,`_cmd_all` 中 `for step in (_cmd_scan, _cmd_analyze, _cmd_rules)` 传入的 `args` 有这三个字段但前者忽略,不影响。

- [ ] **Step 6: Run tests, expect green**

Run: `pytest tests/test_analyze_runner.py tests/test_cli.py -v`
Expected: 全绿

- [ ] **Step 7: Full suite**

Run: `pytest`
Expected: 全绿

- [ ] **Step 8: Commit**

```bash
git add src/picpic/analyze/runner.py src/picpic/cli.py tests/test_analyze_runner.py tests/test_cli.py
git commit -m "feat(analyze,cli): wire CLIP into pipeline with control flags

analyze_all now takes library path and runs CLIP as the 5th pipeline
step when extras are installed. Auto-writes default categories.yml on
first run. CLI adds --no-clip / --clip-only / --force-clip; missing
extras print a helpful stderr hint but do not fail the pipeline.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 5: `picpic categories` 子命令

**Files:**
- Modify: `src/picpic/cli.py`(新增 `_cmd_categories` + parser)
- Test: `tests/test_cli_categories.py`

**Interfaces:**
- Consumes: `picpic.categories.{load_categories, write_default, check_categories, yaml_available, CATEGORIES_FILENAME, CategoriesError}`
- Produces: `picpic categories <library> [--list|--check|--init]`,三选一互斥

- [ ] **Step 1: 写失败测试 `tests/test_cli_categories.py`**

```python
from __future__ import annotations

import pathlib

import pytest

from picpic.categories import CATEGORIES_FILENAME, yaml_available
from picpic.cli import main

pytestmark = pytest.mark.skipif(
    not yaml_available(), reason="PyYAML not installed"
)


def test_categories_init_writes_file(tmp_path: pathlib.Path) -> None:
    rc = main(["categories", str(tmp_path), "--init"])
    assert rc == 0
    assert (tmp_path / CATEGORIES_FILENAME).exists()


def test_categories_init_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    main(["categories", str(tmp_path), "--init"])
    rc = main(["categories", str(tmp_path), "--init"])
    assert rc != 0


def test_categories_list_prints_entries(tmp_path: pathlib.Path, capsys) -> None:
    main(["categories", str(tmp_path), "--init"])
    capsys.readouterr()  # clear
    rc = main(["categories", str(tmp_path), "--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "收据" in out


def test_categories_check_reports_ok(tmp_path: pathlib.Path, capsys) -> None:
    main(["categories", str(tmp_path), "--init"])
    capsys.readouterr()
    rc = main(["categories", str(tmp_path), "--check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()


def test_categories_check_reports_missing(tmp_path: pathlib.Path, capsys) -> None:
    rc = main(["categories", str(tmp_path), "--check"])
    assert rc != 0
    captured = capsys.readouterr()
    haystack = (captured.out + captured.err).lower()
    assert "not found" in haystack or CATEGORIES_FILENAME.lower() in haystack


def test_categories_requires_one_flag(tmp_path: pathlib.Path) -> None:
    rc = main(["categories", str(tmp_path)])
    assert rc != 0
```

- [ ] **Step 2: Run, expect FAIL**

Run: `pytest tests/test_cli_categories.py -v`
Expected: FAIL(未知子命令)

- [ ] **Step 3: 在 `src/picpic/cli.py` 中新增 `_cmd_categories`**

在 `_cmd_serve` 之前插入:

```python
def _cmd_categories(args) -> int:
    from .categories import (
        CATEGORIES_FILENAME,
        CategoriesError,
        check_categories,
        load_categories,
        write_default,
        yaml_available,
    )
    if not yaml_available():
        print(
            "error: PyYAML not installed. Install with: pip install '.[clip]'",
            file=sys.stderr,
        )
        return 2
    library = pathlib.Path(args.library).resolve()
    if (err := _require_library(library)) is not None:
        return err
    if args.init:
        try:
            path = write_default(library)
        except FileExistsError:
            print(
                f"error: {CATEGORIES_FILENAME} already exists in {library}",
                file=sys.stderr,
            )
            return 1
        except CategoriesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {path}")
        return 0
    if args.check:
        problems = check_categories(library)
        if not problems:
            print("ok")
            return 0
        for msg in problems:
            print(f"problem: {msg}", file=sys.stderr)
        return 1
    if args.list:
        try:
            cfg = load_categories(library)
        except FileNotFoundError:
            print(
                f"error: {CATEGORIES_FILENAME} not found in {library}. "
                f"Run: picpic categories {library} --init",
                file=sys.stderr,
            )
            return 1
        except CategoriesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"version={cfg.version} model={cfg.model} "
            f"pretrained={cfg.pretrained} top_k={cfg.top_k}"
        )
        for c in cfg.categories:
            print(f"  - {c.name}: {c.prompt}")
        return 0
    print("error: pick one of --list, --check, --init", file=sys.stderr)
    return 2
```

在 `main()` 里新增 parser(接在 `_cmd_serve` parser 之后,`args = parser.parse_args(argv)` 之前):

```python
    p = sub.add_parser("categories")
    p.add_argument("library")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--list", action="store_true")
    grp.add_argument("--check", action="store_true")
    grp.add_argument("--init", action="store_true")
    p.set_defaults(fn=_cmd_categories)
```

- [ ] **Step 4: Run tests, expect green**

Run: `pytest tests/test_cli_categories.py -v`
Expected: 6 passed(若 PyYAML 未装则整体 skip)

- [ ] **Step 5: Full suite**

Run: `pytest`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/picpic/cli.py tests/test_cli_categories.py
git commit -m "feat(cli): add 'picpic categories' subcommand

Three mutually exclusive flags: --list prints all configured categories,
--check reports validation problems (exit 0 iff clean), --init writes
the default template. Requires PyYAML from [clip] extras — clear error
otherwise.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 6: 后端 API — `GET /api/labels` + `?tab=labeled`

**Files:**
- Modify: `src/picpic/web/app.py`(新增路由 + 扩展 `list_photos` + `_photo_dict`)
- Modify: `tests/conftest.py`(追加 anyio_backend fixture)
- Test: `tests/test_web_labels.py`(新增)

**Interfaces:**
- Consumes: `picpic.categories.{load_categories, yaml_available, CATEGORIES_FILENAME, CategoriesError}`
- Produces:
  - `_photo_dict(row)` 新增 `clip_labels: list`(解析后的)与 `top_label: dict | None`
  - `GET /api/labels?min_score=0.25` → `{"available": bool, "categories": [{"name": str, "count": int}, ...], "unclassified_count": int}`
    - 若 PyYAML 未装或 `categories.yml` 不存在或解析失败,返回 `{"available": false, "categories": [], "unclassified_count": 0}`
  - `GET /api/photos?tab=labeled[&label=<name>&min_score=<n>]`
    - `label` 缺省时返回所有已有 `clip_labels IS NOT NULL` 的活跃图,不排序过滤
    - `label` 为具体类别名:top-1 name 匹配且 top-1 score ≥ min_score 的图,按 top-1 score 降序
    - `label="未分类"`:`clip_labels="[]"` 或 top-1 score < min_score 的图,按 id 升序

- [ ] **Step 1: 在 `tests/conftest.py` 追加 anyio 后端配置**

```python
# --- appended to tests/conftest.py ---
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: 新建 `tests/test_web_labels.py`**

```python
from __future__ import annotations

import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from picpic.db import open_db
from picpic.web.app import create_app


UNCLASSIFIED = "未分类"


def _seed(conn, path, labels):
    cur = conn.execute(
        "INSERT INTO photos(path, status, clip_labels) VALUES(?, 'active', ?)",
        (path, json.dumps(labels)),
    )
    return cur.lastrowid


async def _get(app, url):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as ac:
        return await ac.get(url)


@pytest.mark.anyio
async def test_labels_no_categories_yml(tmp_path: pathlib.Path) -> None:
    open_db(tmp_path / "picpic.db").close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/labels")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False


@pytest.mark.anyio
async def test_labels_counts_top1_per_category(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    _seed(conn, str(tmp_path / "b.jpg"),
          [{"name": "收据", "score": 0.5}, {"name": "文档", "score": 0.4}])
    _seed(conn, str(tmp_path / "c.jpg"), [])
    _seed(conn, str(tmp_path / "d.jpg"), [{"name": "食物", "score": 0.15}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/labels?min_score=0.25")
    body = r.json()
    assert body["available"] is True
    counts = {c["name"]: c["count"] for c in body["categories"]}
    assert counts["收据"] == 2
    assert counts.get("食物", 0) == 0
    assert body["unclassified_count"] == 2  # c + d


@pytest.mark.anyio
async def test_photos_labeled_filter(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    id_a = _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    id_b = _seed(conn, str(tmp_path / "b.jpg"), [{"name": "收据", "score": 0.5}])
    _seed(conn, str(tmp_path / "c.jpg"), [{"name": "食物", "score": 0.7}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/photos?tab=labeled&label=收据&min_score=0.25")
    ids = [p["id"] for p in r.json()["photos"]]
    assert ids == [id_a, id_b]


@pytest.mark.anyio
async def test_photos_labeled_unclassified(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    id_b = _seed(conn, str(tmp_path / "b.jpg"), [])
    id_c = _seed(conn, str(tmp_path / "c.jpg"), [{"name": "食物", "score": 0.1}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(
        app, f"/api/photos?tab=labeled&label={UNCLASSIFIED}&min_score=0.25"
    )
    ids = {p["id"] for p in r.json()["photos"]}
    assert ids == {id_b, id_c}


@pytest.mark.anyio
async def test_photos_dict_includes_clip_labels(tmp_path: pathlib.Path) -> None:
    from picpic.categories import write_default, yaml_available
    if not yaml_available():
        pytest.skip("PyYAML missing")
    write_default(tmp_path)
    conn = open_db(tmp_path / "picpic.db")
    _seed(conn, str(tmp_path / "a.jpg"), [{"name": "收据", "score": 0.9}])
    conn.close()
    app = create_app(tmp_path)
    r = await _get(app, "/api/photos?tab=labeled&label=收据&min_score=0.25")
    p = r.json()["photos"][0]
    assert p["top_label"]["name"] == "收据"
    assert p["clip_labels"][0]["score"] == 0.9
```

- [ ] **Step 3: 确保测试用 anyio 已可用**

Run: `python -c "import anyio" 2>&1 || pip install anyio`
Expected: 已装或成功装入(anyio 是 httpx2/starlette 的传递依赖,通常已在环境里)

- [ ] **Step 4: Run tests, expect FAIL**

Run: `pytest tests/test_web_labels.py -v`
Expected: FAIL(路由 404 / 字段缺失)

- [ ] **Step 5: 修改 `src/picpic/web/app.py`**

在文件顶部 imports 追加 `import json`。

将 `_photo_dict` 整个函数替换为:

```python
def _photo_dict(row) -> dict[str, Any]:
    raw = row["clip_labels"]
    parsed: list[dict[str, Any]] = []
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                parsed = data
        except (json.JSONDecodeError, TypeError):
            parsed = []
    return {
        "id": row["id"],
        "path": row["path"],
        "verdict": row["verdict"],
        "verdict_reason": row["verdict_reason"],
        "dup_group": row["dup_group"],
        "blur_score": row["blur_score"],
        "is_screenshot": row["is_screenshot"],
        "width": row["width"],
        "height": row["height"],
        "clip_labels": parsed,
        "top_label": parsed[0] if parsed else None,
    }
```

将 `list_photos` 整个函数替换为(增加 `label` / `min_score` 参数 + `labeled` 分支):

```python
    @app.get("/api/photos")
    def list_photos(
        tab: str = Query("candidates"),
        min_blur: float | None = Query(None),
        label: str | None = Query(None),
        min_score: float = Query(0.25),
    ):
        conn = open_db(db_path)
        try:
            if tab == "candidates":
                sql = (
                    "SELECT * FROM photos "
                    "WHERE status='active' AND verdict='trash_candidate'"
                )
                params: list[Any] = []
                if min_blur is not None:
                    sql += " AND (verdict_reason<>'blurry' OR blur_score<?)"
                    params.append(min_blur)
                sql += " ORDER BY id"
                rows = conn.execute(sql, params).fetchall()
            elif tab == "similar":
                rows = conn.execute(
                    "SELECT * FROM photos "
                    "WHERE status='active' AND dup_group IS NOT NULL "
                    "ORDER BY dup_group, id"
                ).fetchall()
            elif tab == "trashed":
                rows = conn.execute(
                    "SELECT * FROM photos WHERE status='trashed' "
                    "ORDER BY trashed_at DESC, id"
                ).fetchall()
            elif tab == "labeled":
                rows = conn.execute(
                    "SELECT * FROM photos "
                    "WHERE status='active' AND clip_labels IS NOT NULL "
                    "ORDER BY id"
                ).fetchall()
                photos = [_photo_dict(r) for r in rows]
                if label is None:
                    return {"photos": photos}
                unclassified_name = "未分类"
                if label == unclassified_name:
                    filtered = [
                        p for p in photos
                        if not p["top_label"] or p["top_label"]["score"] < min_score
                    ]
                    filtered.sort(key=lambda p: p["id"])
                    return {"photos": filtered}
                filtered = [
                    p for p in photos
                    if p["top_label"]
                    and p["top_label"]["name"] == label
                    and p["top_label"]["score"] >= min_score
                ]
                filtered.sort(key=lambda p: -p["top_label"]["score"])
                return {"photos": filtered}
            else:
                raise HTTPException(400, f"unknown tab: {tab}")
            return {"photos": [_photo_dict(r) for r in rows]}
        finally:
            conn.close()
```

在 `list_photos` 之后新增 `/api/labels` 路由:

```python
    @app.get("/api/labels")
    def api_labels(min_score: float = Query(0.25)):
        from ..categories import (
            CATEGORIES_FILENAME,
            CategoriesError,
            load_categories,
            yaml_available,
        )
        if not yaml_available() or not (library / CATEGORIES_FILENAME).exists():
            return {"available": False, "categories": [], "unclassified_count": 0}
        try:
            cfg = load_categories(library)
        except CategoriesError:
            return {"available": False, "categories": [], "unclassified_count": 0}
        conn = open_db(db_path)
        try:
            rows = conn.execute(
                "SELECT clip_labels FROM photos "
                "WHERE status='active' AND clip_labels IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        counts: dict[str, int] = {c.name: 0 for c in cfg.categories}
        unclassified = 0
        for r in rows:
            try:
                arr = json.loads(r["clip_labels"])
            except (json.JSONDecodeError, TypeError):
                arr = []
            if arr and isinstance(arr, list) and arr[0].get("score", 0) >= min_score:
                name = arr[0].get("name")
                if name in counts:
                    counts[name] += 1
                else:
                    unclassified += 1
            else:
                unclassified += 1
        return {
            "available": True,
            "categories": [
                {"name": name, "count": counts[name]}
                for name in [c.name for c in cfg.categories]
            ],
            "unclassified_count": unclassified,
        }
```

- [ ] **Step 6: Run tests, expect green**

Run: `pytest tests/test_web_labels.py -v`
Expected: 5 passed(PyYAML 未装则大部分 skip)

- [ ] **Step 7: Full suite**

Run: `pytest`
Expected: 全绿

- [ ] **Step 8: Commit**

```bash
git add src/picpic/web/app.py tests/test_web_labels.py tests/conftest.py
git commit -m "feat(web): GET /api/labels and ?tab=labeled

/api/labels reads categories.yml and counts top-1 matches per category
plus unclassified (empty labels or top-1 below min_score). /api/photos
gains 'labeled' tab with label + min_score filters, including the
special '未分类' bucket. Photos payload now includes parsed clip_labels
and top_label for the frontend to render badges.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## Task 7: 前端"标签"页

**Files:**
- Modify: `src/picpic/web/static/index.html`
- Modify: `src/picpic/web/static/app.js`
- Modify: `src/picpic/web/static/style.css`
- Test: `tests/test_web_labels.py`(追加静态资源冒烟测试)

**Interfaces:**
- Consumes: `GET /api/labels`, `GET /api/photos?tab=labeled&label=<name>&min_score=<n>`, 现有 `POST /api/trash`
- Produces: 第 4 个页签 "标签",配套下拉 + 分数滑块,勾选后复用现有 trash 逻辑

- [ ] **Step 1: 追加冒烟测试到 `tests/test_web_labels.py`**

```python
# --- appended ---
def test_labels_tab_button_in_html() -> None:
    from picpic.web.app import _STATIC_DIR
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="labeled"' in html
    assert "标签" in html


def test_labels_controls_in_html() -> None:
    from picpic.web.app import _STATIC_DIR
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="label-select"' in html
    assert 'id="min-score"' in html
```

- [ ] **Step 2: Run, expect FAIL**

Run: `pytest tests/test_web_labels.py::test_labels_tab_button_in_html tests/test_web_labels.py::test_labels_controls_in_html -v`
Expected: 两个都 FAIL

- [ ] **Step 3: 编辑 `src/picpic/web/static/index.html`**

先读文件确认 tab 与 controls 区域的实际结构(编辑者读一遍):

Run: `sed -n '1,80p' src/picpic/web/static/index.html`
用途:定位 `<nav id="tabs">` 与 `<section id="controls">` 或等价的容器,以便精确插入新元素。

在 `<nav id="tabs">` 里的 `data-tab="similar"` 按钮与 `data-tab="trashed"` 按钮之间插入:

```html
      <button class="tab" data-tab="labeled">标签</button>
```

在现有的 controls 容器(即 blur 滑块与 reason 筛选所在的 section)末尾、`</section>` 或等价闭合标签之前追加:

```html
    <div id="label-control" hidden>
      类别:
      <select id="label-select"></select>
      最低分数:
      <input type="range" id="min-score" min="0" max="1" step="0.05" value="0.25">
      <span id="min-score-value">0.25</span>
    </div>
```

同时给 blur 滑块和 reason 筛选容器加 `id`,方便 JS 切换显示(若尚未有):

- reason 筛选容器加 `id="reason-filters"` (如已存在则跳过)
- blur 滑块容器加 `id="blur-control"`(包裹整个 label + input + span)

若原来的 `#blur-threshold` 直接坐在 controls section 里没有独立容器,把它连同 `<label>` 与 `<span id="blur-value">` 一并包在:

```html
    <div id="blur-control">
      <!-- existing blur slider markup -->
    </div>
```

- [ ] **Step 4: 编辑 `src/picpic/web/static/app.js`**

将 `state` 对象替换为:

```javascript
const state = {
  tab: 'candidates',
  photos: [],
  selected: new Set(),
  reasons: new Set(['screenshot', 'blurry', 'exact_dup']),
  blurThreshold: 100,
  label: null,        // null = "全部"; string = 具体类别 or "未分类"
  minScore: 0.25,
};
```

在文件靠前位置(`api()` 之后、`load()` 之前)新增两个辅助函数,同时替换 `load()`:

```javascript
function toggleControls() {
  const rf = document.querySelector('#reason-filters');
  const bc = document.querySelector('#blur-control');
  const lc = document.querySelector('#label-control');
  if (rf) rf.hidden = state.tab !== 'candidates';
  if (bc) bc.hidden = state.tab !== 'candidates';
  if (lc) lc.hidden = state.tab !== 'labeled';
}

async function refreshLabelSelect() {
  const info = await api(`/api/labels?min_score=${state.minScore}`);
  const sel = $('#label-select');
  const prev = sel.value;
  sel.innerHTML = '';
  if (!info.available) {
    $('#grid').innerHTML =
      '<p class="empty">运行 <code>picpic analyze &lt;lib&gt;</code> 以生成语义标签</p>';
    return false;
  }
  const total = info.categories.reduce((s, c) => s + c.count, 0) + info.unclassified_count;
  const all = document.createElement('option');
  all.value = '';
  all.textContent = `全部 (${total})`;
  sel.appendChild(all);
  for (const c of info.categories) {
    const o = document.createElement('option');
    o.value = c.name;
    o.textContent = `${c.name} (${c.count})`;
    sel.appendChild(o);
  }
  const un = document.createElement('option');
  un.value = '未分类';
  un.textContent = `未分类 (${info.unclassified_count})`;
  sel.appendChild(un);
  sel.value = prev;
  state.label = sel.value || null;
  return true;
}

async function load() {
  toggleControls();
  if (state.tab === 'labeled') {
    const ready = await refreshLabelSelect();
    if (!ready) {
      state.photos = [];
      state.selected.clear();
      render();
      return;
    }
  }
  const params = new URLSearchParams({ tab: state.tab });
  if (state.tab === 'candidates' && state.blurThreshold !== 100) {
    params.set('min_blur', state.blurThreshold);
  }
  if (state.tab === 'labeled') {
    params.set('min_score', state.minScore);
    if (state.label) params.set('label', state.label);
  }
  const { photos } = await api(`/api/photos?${params}`);
  state.photos = photos;
  state.selected.clear();
  render();
}
```

将 `cardFor(p)` 替换为(增加 labeled 分支的角标 + tooltip):

```javascript
function cardFor(p) {
  const el = document.createElement('div');
  el.className = 'card' + (state.selected.has(p.id) ? ' selected' : '');
  el.dataset.id = p.id;
  let badge = '';
  if (state.tab === 'labeled' && p.top_label) {
    badge = `<div class="badge label">${p.top_label.name} ${p.top_label.score.toFixed(2)}</div>`;
    if (p.clip_labels && p.clip_labels.length > 1) {
      el.title = p.clip_labels
        .slice(1)
        .map(l => `${l.name} ${l.score.toFixed(2)}`)
        .join('\n');
    }
  } else if (p.verdict_reason) {
    badge = `<div class="badge">${p.verdict_reason}</div>`;
  }
  el.innerHTML = `<img loading="lazy" src="/thumb/${p.id}" alt="">${badge}`;
  el.addEventListener('click', (ev) => {
    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) {
      openLightbox(p.id);
    } else {
      toggleSelect(p.id);
    }
  });
  return el;
}
```

在文件末尾 `load();` 调用**之前**新增两个事件监听:

```javascript
$('#label-select').addEventListener('change', (e) => {
  state.label = e.target.value || null;
  load();
});

$('#min-score').addEventListener('input', (e) => {
  state.minScore = Number(e.target.value);
  $('#min-score-value').textContent = state.minScore.toFixed(2);
  if (state.tab === 'labeled') load();
});
```

`$('#btn-select-all')` 现有行为:candidates 走 reason 过滤,其他 tab 全选 `state.photos`——labeled tab 命中"其他"分支,行为正确,不改。

- [ ] **Step 5: 编辑 `src/picpic/web/static/style.css`**

在文件末尾追加:

```css
#label-control {
  display: inline-flex;
  gap: 0.5em;
  align-items: center;
  margin-left: 1em;
}

.badge.label {
  background: #2c7be5;
}

.empty {
  padding: 2em;
  color: #666;
  text-align: center;
}
```

- [ ] **Step 6: Run tests, expect green**

Run: `pytest tests/test_web_labels.py -v`
Expected: 全绿(含两个静态资源冒烟测试)

- [ ] **Step 7: Full suite**

Run: `pytest`
Expected: 全绿

- [ ] **Step 8: Manual UI smoke test**

Run:
```bash
mkdir -p /tmp/picpic_smoke
python -m picpic.cli scan /tmp/picpic_smoke
python -m picpic.cli categories /tmp/picpic_smoke --init
python -m picpic.cli serve /tmp/picpic_smoke --no-open --port 8899 &
SERVE_PID=$!
sleep 2
curl -s http://127.0.0.1:8899/api/labels
echo
curl -s "http://127.0.0.1:8899/api/photos?tab=labeled&label=收据&min_score=0.25"
echo
kill $SERVE_PID
```
Expected:
- `/api/labels` 返回 `{"available":true,"categories":[...],"unclassified_count":0}`(装了 PyYAML 时)
- `/api/photos?tab=labeled&...` 返回 `{"photos":[]}`
- 若手边有浏览器:打开 `http://127.0.0.1:8899/`,能看到 4 个 tab 按钮,切到"标签"页时下拉和滑块出现,且因未跑 CLIP 显示空态提示。

- [ ] **Step 9: Commit**

```bash
git add src/picpic/web/static/index.html src/picpic/web/static/app.js src/picpic/web/static/style.css tests/test_web_labels.py
git commit -m "feat(web-ui): '标签' tab with category filter and min-score slider

Fourth tab in the top nav wired to /api/labels + /api/photos?tab=labeled.
Cards in labeled mode show top category name and score in a distinct
blue badge; hovering reveals the full top-k list. Empty state points
users at 'picpic analyze' when no CLIP data yet.

Co-Authored-By: Claude Opus 4 <noreply@anthropic.com>"
```

---

## 收尾

7 个 task 完成后:

- `git log --oneline` 应能看到 7 个新 commit,均在 `phase2-clip` 分支。
- `pytest` 应全绿(约在 Phase 1 的 52 + Phase 2 新增 ~30 之间)。
- `pytest -m slow`:装了 `[clip]` extras 时 `test_load_model_returns_triple` 通过,未装时 slow 集成模块 skip。
- 手工端到端(装 `[clip]` 后,可选):
  1. `pip install '.[clip]'`
  2. `picpic all /path/to/photos`
  3. 浏览器验证"标签"页每个类别下的图肉眼合理。
