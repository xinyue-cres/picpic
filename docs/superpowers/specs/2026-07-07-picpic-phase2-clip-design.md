# picpic Phase 2 — CLIP 语义分类 设计文档

日期:2026-07-07
状态:已确认,待进入实现计划
上游:`docs/superpowers/specs/2026-07-06-picpic-design.md`

---

## 1. 背景与目标

Phase 1 已交付 MVP:scan / exif 截图判断 / 感知哈希去重与相似分组 / 模糊检测 / 规则引擎 / 网页确认删除 / 回收区还原与清空。用户在跑完 Phase 1 后能清掉截图、模糊废片、完全重复的一大块,但**"以后自己界定"的语义分类**(收据、食物、宠物、风景等)Phase 1 没覆盖。

Phase 2 引入本地 CLIP 零样本分类,让用户在 `categories.yml` 里用自然语言写类别,pipeline 给每张图打标签;界面新增"标签"页供用户按类别浏览、勾选、移入回收区。

**核心不变量(从 Phase 1 继承):**
- 原图**全生命周期只读**。任何代码路径不得写、改名、删原图。
- 仅 `src/picpic/trash.py` 允许移动文件,`purge_trash` 是**唯一**允许物理删除的函数。
- SQLite 是唯一真相源。UI 不扫文件系统读照片状态。
- **全本地运行**,无网络调用、无遥测(唯一例外是首次运行 CLIP 时从 HuggingFace 下载模型权重)。
- Path traversal 防御:`/photo/{id}`、`/thumb/{id}` 必须校验路径位于 library 根目录内。
- CLI 打开 DB 前必须校验 `library.exists() and is_dir()`。

**Phase 2 新原则:**
- CLIP 结果**不参与 `verdict`**。`rules.py` 不动。语义标签只用于"界面手选"。
- CLIP 依赖为**可选** extras(`pip install picpic[clip]`),不装也能跑完 Phase 1 全流程。
- `categories.yml` 是**用户可编辑配置文件**,首次运行自动生成默认模板。

**非目标(YAGNI):**
- 不做类别自动学习/微调。CLIP 权重固定为 openai ViT-B/32。
- 不做多模态搜索("以图搜图"、"文字搜图")。只做类别打标。
- CLIP 不参与自动删除决策——最终删除永远由用户界面确认。

---

## 2. 用户可编辑配置文件 `categories.yml`

位置:`<library>/categories.yml`(与照片同级目录)。首次运行 `picpic analyze` 且未装 `[clip]` 依赖时不生成;装了依赖且文件不存在时**自动生成默认模板**并提示用户可编辑后重跑。

**格式:**

```yaml
version: 1
model: ViT-B-32
pretrained: openai
top_k: 3        # 每张图保留分数最高的前 K 个类别
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
```

**字段规约:**
- `version`:当前固定 `1`。未来 schema 变更时用于兼容判断。
- `model` / `pretrained`:传给 `open_clip.create_model_and_transforms`。用户可改,但改了要 `--force-clip` 重跑。
- `top_k`:每图 CLIP 结果保留前 K 个类别(默认 3)。合法范围 `[1, len(categories)]`。
- `categories[].name`:显示名。可中/英文。**必须唯一**。
- `categories[].prompt`:CLIP 输入,**英文**(open_clip 英文语料训练)。

**校验规则:**
- `version` 必须为 `1`,否则报错。
- `categories` 至少一项。
- `name` 去重,重复报错。
- `prompt` 非空字符串。
- 隐式基线 anchor `"a photo"` 不写入 yml,由代码硬编码追加到文本 embedding 中,用于**减去通用相似度**,防止所有图对所有类别都高分。

---

## 3. CLIP pass 执行细节 (`analyze/clip.py`)

**在 pipeline 中的位置:**`exif → hashes → similar → blur → clip`。CLIP 排在最后,前四步廉价信号先跑完,即使 CLIP 中断也不影响 Phase 1 输出。

**模型加载(懒加载):**
- 首次调用 `run_clip_pass()` 时才 `open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')`。
- device 选择:`cuda` > `mps` > `cpu`,由 `torch.cuda.is_available()` 和 `torch.backends.mps.is_available()` 判断。
- 首次调用会从 HuggingFace 下载 ~350MB 权重到 `~/.cache/huggingface/`。之后走缓存,离线可用。
- 下载失败(网络):抛清晰错误,包含建议(挂代理或 `HF_ENDPOINT=https://hf-mirror.com`)。CLI 退出码非 0。

**文本 embedding(一次性):**
- 读 `categories.yml`,取每个 `prompt` 加基线 `"a photo"`,一起 `model.encode_text` → 归一化 → 常驻内存。
- 一次 CLIP pass 只算一次,所有图片复用。

**图像批处理:**
- 从 DB 查:`SELECT id, path FROM photos WHERE status='active' AND clip_labels IS NULL`(idempotent — 二次跑只处理新图;`--force-clip` 时改成 `status='active'` 全查)。
- Batch size 默认 32(GTX 1650 4GB 显存下 ~1.5GB 峰值,留余量)。
- 每批:`Image.open` → `preprocess` transform → 堆成 tensor → `model.encode_image` → 归一化。
- 图像向量 × 文本向量矩阵乘 → 每张图对每个类别 + 基线的原始相似度。
- 按温度 100 做 softmax → 每图输出概率分布。
- **减去基线** `"a photo"` 的概率:`adjusted_score = category_score - baseline_score`,负值截为 0。
- 按 `adjusted_score` 排序,取 top_k 且分数 > 0 的类别。全部为 0 时写空数组 `"[]"`。

**写入 DB 的 `clip_labels` 格式:**
```json
[{"name": "收据", "score": 0.87}, {"name": "文档", "score": 0.34}]
```
- 数组按分数降序。
- `score` 是 baseline-adjusted 值,范围 `(0, 1]`。
- 单张图 decode 失败(HEIC 坏、文件读不到):`clip_labels = "[]"`,继续下一张。
- 每 batch 写入后 `conn.commit()`,进程被 kill 时已处理的图片不丢。

**进度输出:**
- CLI 打印 `[3200/20000] 16%  eta 2m10s`,每 batch 一次,基于滚动均值估 ETA。
- 2 万张预计 GTX 1650 上 2-3 分钟;CPU 30-60 分钟(可接受但会提示"建议装 CUDA")。

**错误处理:**
- CUDA OOM 极少见(batch 32 ~1.5GB),但捕获后自动降 batch 到 16 重试;仍失败则降到 8;仍失败则报错退出。
- 类别 embedding 计算失败(GPU 挂了):立即报错,不写任何图的 `clip_labels`。

**Idempotency 语义:**
- 默认:只处理 `clip_labels IS NULL` 的图。加了新图后重跑,只算新图。
- `--force-clip`:全部重算。用户改了 `categories.yml` 后应该跑这个。
- `--clip-only`:跳过 exif/hashes/similar/blur,只跑 CLIP。

**HEIC 支持:**
- Phase 1 的 `scan.py` 已识别 `.heic` 扩展名。CLIP pass 里 `Image.open` 时若 `pillow-heif` 已装(通过 `[clip]` extras 引入),自动可读;否则该图 decode 失败走空数组分支。

---

## 4. 网页界面:新增"标签"页

现有三页(待删候选 / 相似图组 / 回收区)**完全不动**。在页签栏加第 4 页"标签"。

**布局:**

```
┌──────────────────────────────────────────────────────────┐
│  [待删候选]  [相似图组]  [标签]  [回收区]      共 2w 张   │
├──────────────────────────────────────────────────────────┤
│  类别: [全部▼] 收据 截图 食物 风景 宠物 未分类 ...        │
│  排序: 分数高→低    最低分数: ▓▓▓░░ 0.25 [滑块]           │
├──────────────────────────────────────────────────────────┤
│  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐                                │
│  │☑ │ │☑ │ │  │ │☑ │ │  │  角标: 收据 0.87                │
│  │0.9│ │0.8│ │0.7│ │0.6│ │0.5│  悬停显示完整 top-k        │
│  └──┘ └──┘ └──┘ └──┘ └──┘                                 │
├──────────────────────────────────────────────────────────┤
│  已选 47 张   [移入回收区]  [全选] [取消]                  │
└──────────────────────────────────────────────────────────┘
```

**交互:**
- 类别下拉默认"全部",按类别分组展示;选具体类别只显示这类图,按分数降序。
- 类别列表实时从 `categories.yml` 读取,末尾追加伪类别 **"未分类"**。
- **未分类定义**:该图 `clip_labels = '[]'`(decode 失败或所有类别分数都 ≤ 0);或所有 top-k 分数都低于 `min_score` 阈值。
- 每图角标显示 top-1 类别名 + 分数,悬停显示完整 top-k 列表。
- 分数滑块过滤低置信度结果(默认 0.25),弱匹配藏起来减噪。
- 勾选 + [移入回收区] 复用现有 `POST /api/trash`。语义标签**不写 `verdict`**,由用户主动挑删。

**空态:**
- CLIP 未跑过(所有 `clip_labels IS NULL`):页面显示 "运行 `picpic analyze --clip` 生成语义标签"。
- 跑过但当前类别无匹配:显示 "该类别下暂无匹配"。

**后端 API 新增:**
- `GET /api/labels` → `{"categories": [{"name": "收据", "count": 12}, ...], "unclassified_count": 340}`
  - 读 `categories.yml` 得类别列表,SQL 聚合各类别命中数(top-1 且分数 > min_score),以及未分类数。
- `GET /api/photos?tab=labeled&label=<name>&min_score=0.25` → 返回该类别下的图片列表,按 top-1 分数降序。
  - `label=未分类` 走特殊分支:`clip_labels = '[]'` 或 top-1 分数 < min_score 的图。
- 现有 `POST /api/trash` / `POST /api/restore` / `POST /api/purge` 不动。

---

## 5. CLI 新增命令与开关

**新增子命令 `picpic categories`:**

```
picpic categories --list       # 列出 categories.yml 里所有类别及 prompt
picpic categories --check      # 校验格式:字段完整、prompt 非空、名称唯一、version 匹配
picpic categories --init       # 若 categories.yml 不存在,写入默认模板(装了 [clip] 才允许)
```

**`analyze` 新增开关:**

```
picpic analyze                 # 全跑:exif + hashes + similar + blur + clip(若装了 [clip])
picpic analyze --no-clip       # 跳过 CLIP,只跑 Phase 1 四步
picpic analyze --clip-only     # 只跑 CLIP,跳过其他四步(改了 yml 后重跑用)
picpic analyze --force-clip    # 强制重算所有图的 CLIP 标签(默认只跑未标过的)
```

**首次运行引导:**
- `picpic analyze` 或 `picpic all` 首次跑,若装了 `[clip]` 且 `categories.yml` 不存在:
  - 自动写默认模板,提示 "已生成 categories.yml,可编辑后重跑 `picpic analyze --clip-only --force-clip`"。
- 未装 `[clip]` extras:CLIP 步骤跳过,提示 "未装 CLIP 依赖,执行 `pip install picpic[clip]` 启用语义分类"。

**其他行为:**
- `picpic all` = `scan + analyze + rules + serve`。装了 CLIP 则包含 CLIP 步骤。
- `picpic serve` 无变化。页面自动检测 CLIP 标签存在性决定"标签"页空态。

---

## 6. 测试策略

**默认单元测试**(不下模型,`pytest` 全跑,CI 用):
- `test_categories.py` — YAML 解析、字段校验、默认模板生成、名称去重、version 检查、`--list/--check/--init` 命令。
- `test_clip_pass.py` — `monkeypatch` 替换 `_load_model` 和 `_encode_image_batch` 为返回固定假向量的 stub,验证:
  - 批处理逻辑(32/16/末批不足)
  - `clip_labels` JSON 写入格式正确
  - Idempotent:二次跑跳过已有 `clip_labels` 的图
  - `--force-clip` 全量重跑
  - 单图 decode 失败不阻断整批,写 `"[]"`
  - baseline 减法 + top-k 过滤 + 分数排序
- `test_web_labels.py` — `/api/labels` 返回类别与命中数、`/api/photos?tab=labeled` 各种过滤组合、未分类分支。
- `test_cli_categories.py` — `picpic categories` 三个子命令。

**慢速集成测试**(默认跳过,`pytest -m slow` 手动跑):
- `test_clip_integration.py` — 装真 `torch + open_clip`,跑 5 张固定小图,断言:模型加载成功、向量输出形状对、"收据"图对 receipt prompt 分数高于 landscape prompt。
- `pyproject.toml` 增加 `[tool.pytest.ini_options] markers = ["slow: model download required"]`。默认 `pytest` 命令通过 `-m "not slow"` 跳过。

**测试固件:**
- `tests/fixtures/` 现有截图/风景/模糊测试图复用。CLIP 集成测试再加 5 张 100x100 的合成图(收据、风景、食物、宠物、人像各一张)。

**覆盖率目标:**新增代码行覆盖 ≥ 85%。`clip.py` 的 `_load_model` / `_encode_image_batch` 内部由集成测试兜底,单元测试不强求覆盖。

**CI 影响:**默认不装 `[clip]` extras,速度维持 Phase 1 水平(~10s)。装了 extras 才能跑 slow 测试。

---

## 7. 依赖与安装

**`pyproject.toml` 变更:**

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx2>=2.5"]
clip = [
    "torch>=2.0",
    "open_clip_torch>=2.24",
    "pillow-heif>=0.15",
    "PyYAML>=6.0",
]
```

用户安装:
- 只跑 Phase 1: `pip install .`
- 加 Phase 2 语义分类: `pip install '.[clip]'`(引入 ~2.5GB PyTorch)

`categories.py` 里 `import yaml` 用 try/except 包住:未装 `[clip]` 时导入失败,CLI 走"未装依赖"分支。

---

## 8. 数据模型:**无变化**

`photos` 表 Phase 1 已有 `clip_labels TEXT` 列。Phase 2 只往里写字符串,不改 schema。`SCHEMA_VERSION` 保持 `1`。

---

## 9. 风险与权衡

1. **首次运行下载 350MB 权重**:非"完全本地"的唯一破例。缓解:清晰提示、支持镜像;下载完之后离线可跑。
2. **CLIP 分类主观**:类别 prompt 好坏影响准确度。缓解:默认模板 prompt 是经验值;用户可迭代 yml 后 `--force-clip` 重跑,成本 2-3 分钟。
3. **CPU 用户体验差**:20k 张 30-60 分钟。缓解:进度条 + 提前提示;`--no-clip` 保底跳过。
4. **HEIC 处理**:依赖 `pillow-heif`。装了才能解;没装的 HEIC 图走 `"[]"` 空标签,不阻断整批。
5. **类别 embedding 与图 embedding 版本必须一致**:改了 `model` / `pretrained` 后不 `--force-clip` 会导致图与文本 embedding 版本不匹配。缓解:文档明确、`categories --check` 提示。

---

## 10. 分阶段交付内的位置

- Phase 1(已完成):MVP,不含 CLIP。
- **Phase 2(本文档)**:CLIP 语义分类 + `categories.yml` + "标签"页。
- Phase 3(后续):规则引擎外化为配置文件,用户自由增删规则(可能涉及把 CLIP 结果纳入规则)。

Phase 2 完成后,用户完整能力:
1. 扫描 → 分析 → 规则(自动挑截图/模糊/完全重复) → 界面确认 → 移入回收区。
2. 相似组人工审查。
3. 按类别浏览打过 CLIP 标签的图,任意勾选删。
4. 回收区还原或清空。
