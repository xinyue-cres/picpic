"""User-editable CLIP categories config.

Reads <library>/categories.yml. YAML support is optional — if PyYAML is
missing, callers should check yaml_available() first. All validation errors
raise CategoriesError with a short, actionable message.
"""

from __future__ import annotations

import importlib.util
import pathlib
from dataclasses import dataclass, field


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
    return importlib.util.find_spec("yaml") is not None


def _path(library: pathlib.Path) -> pathlib.Path:
    return library / CATEGORIES_FILENAME


def write_default(library: pathlib.Path) -> pathlib.Path:
    if not yaml_available():
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
    if not yaml_available():
        raise CategoriesError(
            "PyYAML not installed. Install with: pip install '.[clip]'"
        )
    target = _path(library)
    if not target.exists():
        raise FileNotFoundError(str(target))
    return _parse(target.read_text(encoding="utf-8"))


def _parse(text: str) -> CategoriesConfig:
    import yaml  # lazy — only reached after yaml_available() gate
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
        if name == "未分类":
            raise CategoriesError(
                "'未分类' is a reserved category name "
                "(used for photos with no confident label)"
            )
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
