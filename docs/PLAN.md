# 本阶段实施计划

当前阶段：**作者风格自动蒸馏 + 受控 HTML 世界书条目**（两个可独立启用的增强模块）
状态：**已实施**（2026-10-20；Phase E1–E4 完成，验收记录见 `docs/RUN_REPORT.md` §14）
制定日期：2026-10-20
上游依据：`docs/novel-to-tavern-enhancement-plan.md`（2026-10-20 版）、
Nuwa SKILL.md v1.0.0（2026-10-20 检索，仅作方法论参考）

> 本文取代此前的分阶段施工记录。Phase 1–6（ingest→export→verify）已完成，
> 旧记录可从 git 历史查阅。既有管线行为是本次的**兼容基线**：
> 两个新模块默认关闭，全部关闭时导出结果与现状一致。

## 0. 用户修正记录（2026-10-20，相对上一版计划的三处方向性修改）

1. **不使用外部 Nuwa 蒸馏产物**。风格蒸馏由本仓库自己的 LLM 管线完成：
   用户照常对小说原文跑导出，启用 `style.enabled` 后，`n2t export` 会**自动执行**
   风格蒸馏（逐块观察 → 合并 → 编译档案 → 压缩运行时规范），精简结果进
   主卡 Description，完整档案进世界书。Nuwa 仅作为方法论参考写在文档里，
   项目中没有 `style-import`，不导入任何外部产物。
2. **HTML 规则不进 Description**。它作为一条**世界书触发条目**按需加载，
   避免 Description 膨胀。
3. **计划细化到可照做程度**：配置模型、数据 schema、函数签名、提示词契约、
   缓存键、产物布局、测试名全部给出，执行 agent 按 §3–§9 顺序实施即可。

---

## 1. 现状基线（已核对的代码事实，实施时不要重新"发现"它们）

| 事实 | 位置 |
|---|---|
| CLI 子命令注册与 handler 模式；`_resolve_run` 校验 run 目录 | `src/novel_to_tavern/cli.py:51` `build_parser`、`cli.py:37` |
| 配置 Pydantic `extra="forbid"`，未知键报错；「只写会被读取的键」是明文约定 | `src/novel_to_tavern/config.py:32`、`config/config.example.yaml` 头注 |
| `worldbook.allow_html_beautification: Literal[False]` —— 本次删除，由 `rendering.html.enabled` 取代 | `config.py:96` |
| Description 组装点：`build_greetings` 产出后追加 `mode_notice` | `export/runner.py:222` |
| 世界书条目统一 `PlannedEntry` → `EntryDraft` → serializer；内嵌/独立同一 canonical list，parity 校验 | `export/builder.py:412 plan_to_drafts`、`export/runner.py:237` |
| 条目类别封闭 Literal：`EntryCategory`（本次加 `"author_style"`、`"rendering"`） | `timeline/worldbible.py:19` |
| `_assemble_entries` 是条目总装函数（核心规则 + 常驻 + 剧情主线 + 触发） | `export/runner.py:141` |
| 严格起始点路径 `_export_strict`：结构性删除起点后内容 | `export/runner.py:437` |
| LLM 层：`Provider` 协议；`FileProvider` 读 `<chunk_id>.json` 预生成响应（`{"text","model"}` 或裸 JSON）；`build_provider(config, log=...)` 在缺凭据时抛 `ProviderError` | `llm/provider.py:57/65/105` |
| 抽取 runner 模式：manifest 加载、按行区间取原文、缓存读写、隔离区、续跑 | `extract/runner.py:178-260`（本计划的风格观察 runner 照此写） |
| 缓存键模式：模型 + endpoint 指纹 + prompt_version + 模板 sha256 + schema_version + 输入 hash + temperature | `extract/runner.py:132 cache_key` |
| 提示词版本化模式：`PROMPT_VERSION` + `SYSTEM_PROMPT` + `build_user_prompt` + `prompt_template_hash()` | `extract/prompts.py`、`verify/prompts.py` |
| 引文定位：`locate_quote`（去空白逐字检索，最紧行区间）、`MAX_QUOTE_CHARS`、`truncate_quote` | `extract/evidence.py:52/135` |
| `Manifest` 提供 `chunks`（含 `chunk_id/chapter_id/source_id/start_line/end_line/sha256`）、`global_chapter_order()`、`source_display_names()` | `ingest/manifest.py` |
| 导出前硬门禁：`validate_card(strict)` + `validate_worldbook(strict)` + `validate_parity` + 密钥扫描，不过不写文件 | `export/runner.py:233-246` |
| token 粗估：`estimate_tokens`（CJK 1 字 1 token，其余 4 字符 1 token） | `timeline/worldbible.py:96` |
| `test_docs_consistency.py` 强制 README/RUN_REPORT 的测试计数 == 实际收集数 | `tests/test_docs_consistency.py` |
| 测试 fixture 全合成；受版权原文不进 tests/；`runs/` 只读不可覆盖 | `tests/fixtures/`、`test_repo_hygiene.py`、`test_gitignore.py` |

## 2. 范围

### 2.1 做

1. **模块 A — 作者风格自动蒸馏**（仓库内 LLM 管线，默认关闭）：
   - `style-observe`：逐分块 LLM 观察写作风格（带引文证据，代码定位校验）；
   - `style-compile`：分批合并 → 编译 `StyleProfile` → 渲染运行时精简规范
     （≤ `max_runtime_tokens`）→ 代码分组生成 8 组世界书条目 + ≥6 个评估样例；
   - `n2t export` 在 `style.enabled=true` 时**自动**执行上述管线（产物新鲜则跳过，
     过期则重跑，逐段缓存）；精简规范追加进 Description 的【叙事风格规范】分节，
     完整档案以触发式世界书条目进入内嵌与独立世界书。
2. **模块 B — 受控 HTML 世界书条目**（默认关闭）：
   - 配置驱动渲染一段 HTML 使用规范，作为**触发式条目** `wb_rendering_html`
     写入世界书；只允许 `<span>` + `font-size`/`color`/`font-style` + 配置色板/字号；
     不进 Description。

### 2.2 不做

- 不导入/分发 Nuwa 产物或源码；不实现 MVU / EJS（`allow_mvu`/`allow_ejs` 保持 `Literal[False]`）。
- 不放开任意 HTML 美化；不使用 `system_prompt`/`post_history_instructions` 字段
  （统一走 Description 分节与世界书条目，Tavo 对该字段的注入行为未验证，留作后续评估）。
- 风格资料不进 canon：不写 facts/entities/timeline/knowledge；不改既有语义。
- 不声称提示词能强制过滤 Tavo 运行时的模型 HTML 输出（prompt 不是沙箱）。
- 不动 `runs/` 下已有 run；不新增第三方依赖（HTML 解析用标准库 `html.parser`）。

---

## 3. 配置变更（`src/novel_to_tavern/config.py`）

### 3.1 新增模型（放在 `WorldbookConfig` 之后，`Config` 里注册）

```python
class StyleConfig(_Base):
    #: 总开关。开启后 export 会自动执行风格蒸馏（见 style/pipeline.py）。
    enabled: bool = False
    #: 【叙事风格规范】分节的粗估 token 上限（estimate_tokens 口径）。超出先自动压缩，再超报错。
    max_runtime_tokens: int = Field(default=800, gt=0)
    #: 是否把 8 组完整风格档案写进世界书（触发式条目）。
    worldbook_entries: bool = True
    #: 逐块观察的分块数上限；0 = 全部。>0 时等距抽样（确定性，见 select_chunks）。
    observe_max_chunks: int = Field(default=0, ge=0)
    #: 合并阶段每批吃多少份观察。
    merge_batch_size: int = Field(default=30, gt=0)
    #: 可选：用户自持有的作者访谈/创作谈笔记（md/txt），作补充证据。相对仓库根目录。
    supplementary_path: str | None = None


class HtmlRenderingConfig(_Base):
    enabled: bool = False
    mode: Literal["controlled_span"] = "controlled_span"
    allowed_properties: list[Literal["font-size", "color", "font-style"]] = Field(
        default_factory=lambda: ["font-size", "color", "font-style"]
    )
    allowed_font_sizes: list[str] = Field(
        default_factory=lambda: ["0.88em", "1em", "1.08em", "1.12em"]
    )
    color_palette: dict[str, str] = Field(
        default_factory=lambda: {
            "muted": "#9298A3",
            "emphasis": "#B08A38",
            "warning": "#B05A5A",
            "mystery": "#7C8FA6",
        }
    )
    max_suggested_spans_per_reply: int = Field(default=3, ge=0)

    @field_validator("allowed_font_sizes")
    @classmethod
    def _check_sizes(cls, value):
        if not value:
            raise ValueError("allowed_font_sizes 不能为空")
        for item in value:
            if not re.fullmatch(r"\d+(\.\d+)?em", item):
                raise ValueError(f"字号必须是 em 相对单位：{item!r}")
        return value

    @field_validator("color_palette")
    @classmethod
    def _check_palette(cls, value):
        if not value:
            raise ValueError("color_palette 不能为空")
        for name, hex_color in value.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError(f"色板语义名不合法：{name!r}")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
                raise ValueError(f"颜色必须是 #RRGGBB：{hex_color!r}")
        return value


class RenderingConfig(_Base):
    html: HtmlRenderingConfig = Field(default_factory=HtmlRenderingConfig)
```

`Config` 增加 `style: StyleConfig`、`rendering: RenderingConfig` 两个字段。
（需要 `from pydantic import field_validator`、`import re`。）

### 3.2 删除

- `WorldbookConfig.allow_html_beautification`（被 `rendering.html.enabled` 取代）。
  同步删 `config/config.example.yaml` 对应行、`docs/CONFIG_REFERENCE.md` 对应行，
  并全局 grep `allow_html_beautification` 清掉所有引用（含测试）。

### 3.3 同步函数

- `summarize()`：追加 `style.enabled`、`style.max_runtime_tokens`、`rendering.html.enabled`。
- `config_warnings()`：追加两条 —
  - `style.enabled=true` 且 `supplementary_path` 配置了但文件不存在 → 警告（编译时会报错，这里先提示）；
  - `rendering.html.enabled=true` → 「HTML 规则是世界书触发条目，且 Tavo 渲染效果未经实测」。

### 3.4 `config/config.example.yaml` 追加

```yaml
style:
  enabled: false # 开启后 n2t export 自动执行作者风格蒸馏（逐块观察→合并→编译）
  max_runtime_tokens: 800 # 【叙事风格规范】分节粗估上限；超出自动压缩，再超报错
  worldbook_entries: true # 把 8 组完整风格档案写进世界书（触发式，非常驻）
  observe_max_chunks: 0 # 逐块观察上限；0 = 全部。>0 时等距抽样（确定性）
  merge_batch_size: 30 # 合并阶段每批观察份数
  supplementary_path: null # 可选：作者访谈/创作谈笔记（md/txt），补充证据

rendering:
  html:
    enabled: false # 开启后世界书多一条「输出格式：受控 HTML 规范」触发条目
    mode: controlled_span # 唯一取值
    allowed_properties: [font-size, color, font-style] # 只能取这三个值的子集
    allowed_font_sizes: ["0.88em", "1em", "1.08em", "1.12em"] # 必须 em 相对单位
    color_palette:
      muted: "#9298A3"
      emphasis: "#B08A38"
      warning: "#B05A5A"
      mystery: "#7C8FA6"
    max_suggested_spans_per_reply: 3 # 写进规范文本的软建议
```

---

## 4. 数据 schema（`src/novel_to_tavern/style/schema.py`）

两层：模型直接产出的 `Raw*`（只给引文）与代码校验后的 `*`（引文已定位）。
与 `extract/schema.py` 的 Raw/Record 分层同理。

```python
OBSERVATION_SCHEMA_VERSION = 1
PROFILE_SCHEMA_VERSION = "style_profile_v1"

# --- 观察层（逐分块） ---

class RawStyleEvidence(_Base):           # 模型产出，只给引文，不信行号
    aspect: str                          # 属于哪个维度（自由短词，如 sentence_rhythm）
    quote: str                           # ≤ MAX_QUOTE_CHARS，须逐字来自原文

class RawStyleObservation(_Base):        # 模型对单个分块的产出
    narrative_voice: str = "unknown"
    sentence_rhythm: str = "unknown"
    description_patterns: str = "unknown"
    figurative_language: str = "unknown"
    dialogue_patterns: str = "unknown"
    psychological_narration: str = "unknown"
    scene_pacing: str = "unknown"
    notable_motifs: list[str] = Field(default_factory=list)
    anti_patterns_observed: list[str] = Field(default_factory=list)
    evidence: list[RawStyleEvidence] = Field(default_factory=list)

class StyleEvidence(RawStyleEvidence):   # 代码定位成功后补充行号
    start_line: int
    end_line: int

class StyleObservation(RawStyleObservation):
    schema_version: int = OBSERVATION_SCHEMA_VERSION
    chunk_id: str
    chapter_index: int                   # 全局章节序号（global_chapter_order）
    source_id: str
    evidence: list[StyleEvidence] = Field(default_factory=list)
    quotes_dropped: int = 0              # 定位失败被丢弃的引文数（审计用）
    model: str = ""
    prompt_version: str = ""
    input_sha256: str = ""
    output_sha256: str = ""

# --- 档案层（编译产物） ---

class StyleDimension(_Base):
    summary: str = "unknown"
    rules: list[str] = Field(default_factory=list)     # 行为式规则，非形容词堆砌
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"

class SourceManifestEntry(_Base):
    kind: Literal["novel", "interview", "essay", "note", "other"]
    locator: str                          # 文件名/URL/说明
    detail: str = ""                      # 可信度与用途说明

class StyleEvalCase(_Base):
    case_id: str
    scenario_type: str                    # 场景铺陈/人物对话/内心活动/冲突/情绪克制爆发/场景收束
    instruction: str                      # 让模型写一段什么
    expected_traits: list[str]            # 应符合的风格规律（抽象描述，非原文）
    anti_patterns: list[str] = Field(default_factory=list)

class StyleProfile(_Base):
    schema_version: str = PROFILE_SCHEMA_VERSION
    profile_id: str
    author_label: str
    works_in_scope: list[str]
    created_at: str
    source_manifest: list[SourceManifestEntry]
    narrative_voice: StyleDimension
    sentence_rhythm: StyleDimension
    description_patterns: StyleDimension
    figurative_language: StyleDimension
    dialogue_patterns: StyleDimension
    psychological_narration: StyleDimension
    scene_pacing: StyleDimension
    genre_tone: StyleDimension
    anti_patterns: list[str] = Field(default_factory=list)
    contextual_variants: list[str] = Field(default_factory=list)   # 不同场景的风格差异
    limitations: list[str] = Field(default_factory=list)
    human_review_items: list[str] = Field(default_factory=list)
    runtime_rules: str = ""               # 精简运行时规范正文（编译产物，见 §6.3）
    eval_cases: list[StyleEvalCase] = Field(default_factory=list)
    inputs_fingerprint: str = ""          # 见 §7.2，export  freshness 判定依据
```

规则：维度证据不足时 `summary="unknown"`、`confidence="unknown"`，**不强行填值**；
`extra="forbid"` 沿用 `_Base`（`from ..config import _Base` 或直接继承
`pydantic.BaseModel` + `ConfigDict(extra="forbid")`，与 config 模块写法一致）。

---

## 5. 提示词契约（`src/novel_to_tavern/style/prompts.py`）

四个版本化提示词。文件末尾提供 `prompt_template_hash()`：对四个模板文本 +
四个版本号拼接后 sha256（仿 `extract/runner.py:94`）。

### 5.1 观察 `PROMPT_VERSION_OBSERVE = "style-observe-v1"`

- SYSTEM：你是文学风格分析器。只分析给定章节正文的**写作风格**，不复述剧情、
  不提取人物/事件事实、不评价好坏。对七个维度（`RawStyleObservation` 字段）各给
  1–3 条可操作规律；证据不足的维度填 `"unknown"`，禁止编造。每条规律尽量附 1 条
  ≤40 字的**逐字**引文（进 `evidence`，`aspect` 填维度名）。引文必须逐字来自正文，
  不得改写。输出严格 JSON，字段名与给定 schema 一致，不多字段。
- USER：`作品：{book_title}\n章节：第{n}章{title}\n\n正文：\n{chunk_text}`
  （`chunk_text` 按 manifest 行区间取原文，方式同 `extract/runner.py:254`）。
- 产出契约：`RawStyleObservation` JSON。代码侧用 `locate_quote` 逐条定位引文，
  定位失败的引文**丢弃**并计 `quotes_dropped`（观察本身保留）。

### 5.2 合并 `PROMPT_VERSION_MERGE = "style-merge-v1"`

- SYSTEM：输入是同一份作品的若干份章节级风格观察。合并同类规律、去重、
  保留分歧（卷间/场景差异写入 `contextual_variants`），不得新造观察里没有的规律。
  每个维度输出 `{summary, rules, confidence}`，证据互相矛盾或样本太薄时降 confidence。
- USER：本批观察 JSON 数组（只取七个维度 + motifs + anti_patterns + confidence 相关
  字段，不带 chunk 元数据与引文，控制长度）。
- 产出契约：`{"dimensions": {七个维度: StyleDimension}, "contextual_variants": [...],
  "anti_patterns": [...], "motifs": [...]}`。

### 5.3 编译 `PROMPT_VERSION_COMPILE = "style-compile-v1"`

- SYSTEM：把分批风格笔记整理成一份**小说叙事风格档案**（StyleProfile）。
  硬性要求：小说文本观察是主要证据；补充资料（若有）是外部证据，作者自述不得
  自动升格为作品风格事实，需在 `limitations` 注明交叉检查结论；
  `anti_patterns` 写「与本作风格不相容的生成倾向 + 理由」；不写具体剧情事实、
  不复制原著句子；同时产出 —
  1. `runtime_rules`：注入角色卡的**精简**运行时风格规范。用行为规则
     （如何组织段落/控制揭露节奏/描写情绪），不用形容词清单；旁白风格与
     NPC 台词风格分开；不重复世界运行规则与人物事实；附一句「不生搬统计指标，
     优先保留情境功能」；目标 ≤ 给定 token 预算。
  2. `eval_cases`：≥6 个，覆盖场景铺陈/人物对话/内心活动/冲突/情绪克制爆发/
     场景收束；`expected_traits` 写抽象规律，不得用原文逐字匹配。
- USER：全部批次笔记 + 章节摘要清单（来自 extraction 的 digests，仅标题+一句话，
  供语境）+ 可选 supplementary 文本 + `max_runtime_tokens`。
- 产出契约：完整 `StyleProfile` JSON（`inputs_fingerprint` 由代码填，模型留空）。

### 5.4 压缩 `PROMPT_VERSION_COMPRESS = "style-compress-v1"`

- SYSTEM：把给定运行时风格规范压缩到 ≤N token（CJK 1 字 1 token）。
  优先保留高置信度、可执行、具情境功能的规则；输出
  `{"runtime_rules": "...", "dropped": ["被删规律及理由"]}`。删高置信度规律必须给理由。

---

## 6. 模块实现规格

### 6.1 `src/novel_to_tavern/style/observe.py`（新建，仿 `extract/runner.py`）

```python
class StyleObserveError(RuntimeError): ...

def select_chunks(manifest, max_chunks: int) -> list:
    """max_chunks<=0 → 全部 chunk；否则等距抽样（排序后取 floor(i*(n-1)/(k-1)) 位），
    首尾必含，结果确定性（同输入同输出，保证缓存稳定）。"""

def run_style_observation(config, run_dir, provider, *, resume=True, limit=None, log=None) -> dict
```

行为（逐项照 extract runner 写）：

- 读 `run_dir/manifest.json` → `Manifest.model_validate`；缺失抛 `StyleObserveError`。
- 输出目录 `run_dir/author_style/observations/`，隔离区其下 `_errors/`，
  索引 `_index.json`（已完成 chunk_id 列表，供续跑）。
- 逐 chunk：`text = "".join(lines[chunk.start_line:chunk.end_line])`；
  缓存键（§7.1）命中则跳过引擎；调用
  `provider.complete(chunk_id=chunk.chunk_id, system_prompt=..., user_prompt=...)`；
  解析失败 → 重试 1 次 → 仍失败写 `_errors/<chunk_id>.json`（含原文响应与原因）并
  计入 `failed`，不写成成功。
- 引文逐条 `locate_quote`：成功补 `start_line/end_line`；失败丢弃、`quotes_dropped+=1`。
- 成功产物写 `observations/<chunk_id>.json`（`StyleObservation`）。
- 返回 `{done, skipped, failed, ok}`；`failed` 非空时 `ok=False`（CLI 退出码 1）。
- 日志不出现原文；原文不进普通日志。

### 6.2 `src/novel_to_tavern/style/compiler.py`（新建）

```python
class StyleCompileError(RuntimeError): ...

def compute_inputs_fingerprint(run_path, config, *, endpoint_fingerprint: str = "") -> str
def run_style_compile(run_dir, config, provider, *, log=None) -> StyleProfile
def render_profile_md(profile: StyleProfile) -> str
def render_runtime_prompt(profile: StyleProfile) -> str
```

`run_style_compile` 步骤：

1. 读全部 `observations/*.json`（跳过 `_` 开头）；为空 → `StyleCompileError`（先跑 observe）。
2. 按 `merge_batch_size` 分批，逐批调 merge 提示词
   （`chunk_id = f"style_merge_batch_{i:03d}"`），产物的 `dimensions` 写
   `author_style/merged/batch_{i:03d}.json`。各批独立缓存（§7.1）。
3. 汇总批次笔记 + digests（从 `run_dir/extraction/*.json` 取 `chapter_index/chapter_title/
   summary`，同 `export/runner.py:121 _collect_digests`）+ supplementary
   （`supplementary_path` 非空则读入；配置了但文件不存在 → `StyleCompileError`）
   → 调 compile 提示词（`chunk_id = "style_compile"`）→ 解析为 `StyleProfile`
   （schema 校验失败按坏响应处理：重试 1 次 → 隔离 → 报错）。
4. 代码填充：`profile_id`（`"style-" + fingerprint[:12]`）、`created_at`（UTC ISO）、
   `works_in_scope`（manifest 来源文件名）、`source_manifest`（小说来源 kind="novel" +
   supplementary kind="note"）、`inputs_fingerprint = compute_inputs_fingerprint(...)`。
5. 预算检查：`estimate_tokens(profile.runtime_rules) > max_runtime_tokens` →
   调 compress（`chunk_id = "style_compress"`）→ 更新 `runtime_rules` 并记录
   `dropped`；仍超 → `StyleCompileError`，`audit.md` 写明丢弃项，**不静默截断**。
6. 落盘 6 份产物（§8）：`style_profile.json`（`model_dump(mode="json")`）、
   `style_profile.md`（`render_profile_md`）、`runtime_style_prompt.md`
   （`render_runtime_prompt`：标题 + `runtime_rules`）、
   `style_worldbook_entries.json`（`build_style_entries` 后
   `[e.model_dump(mode="json") for e in entries]`）、
   `style_eval_cases.json`（profile.eval_cases）、`audit.md`
   （观察覆盖：观察块数/总块数、quotes_dropped 合计、维度置信度分布、压缩丢弃项、
   局限与人工复核项、supplementary 使用情况）。

### 6.3 `src/novel_to_tavern/style/worldbook.py`（新建）

```python
STYLE_ENTRY_GROUPS: list[tuple[str, str, list[str]]] = [
    ("wb_style_overview",     "作者风格：总体叙事原则",   ["narrative_voice", "genre_tone"]),
    ("wb_style_rhythm",       "作者风格：句式与段落节奏", ["sentence_rhythm"]),
    ("wb_style_dialogue",     "作者风格：对话与潜台词",   ["dialogue_patterns"]),
    ("wb_style_psychology",   "作者风格：心理描写",       ["psychological_narration"]),
    ("wb_style_description",  "作者风格：环境与感官描写", ["description_patterns"]),
    ("wb_style_figurative",   "作者风格：意象与修辞",     ["figurative_language"]),
    ("wb_style_pacing",       "作者风格：场景节奏与高潮", ["scene_pacing"]),
    ("wb_style_anti",         "作者风格：反模式与风格边界", []),  # anti_patterns + contextual_variants
]
# 触发词（组合词，避免单字命中）：
STYLE_ENTRY_KEYS = ["作者风格", "叙事风格", "语言风格", "文风特点", "写作风格"]
# 禁用句探测（这些句子不得命中任何风格条目）：
STYLE_ENTRY_MUST_NOT_TRIGGER = ("这个剧情怎么发展？", "他的文风如何",
                                "这个角色风格独特", "今天天气不错")

def build_style_entries(profile: StyleProfile) -> list[PlannedEntry]
def write_style_entries(path: Path, entries: list[PlannedEntry]) -> None
def load_style_entries(path: Path) -> list[PlannedEntry]
def check_style_no_plot_leak(entries: list[PlannedEntry], upto_chapter: int) -> None
```

- 每组正文 = 组内维度的 `summary` + `rules` 逐条列出（`unknown` 维度整节省略；
  全组 unknown → 该组不生成条目，审计记录）。`category="author_style"`、
  `always_on=False`、`priority=40`、`chapter_gated=False`、
  `valid_from_chapter=None`、`estimated_tokens=estimate_tokens(body)`、
  `quality_flags=["非 canon：作者风格资料，由自动蒸馏生成"]`、正文末尾统一附一行
  「以上为非原著事实的写作风格规则」。
- `check_style_no_plot_leak`：对每条 `content_runtime` 用正则 `第\s*(\d+)\s*章`
  提取章节号，`N - 1 > upto_chapter` → 抛 `StyleLeakError`（列条目与章节号）。

### 6.4 `src/novel_to_tavern/style/pipeline.py`（新建）

```python
@dataclass
class StyleArtifacts:
    profile: StyleProfile
    runtime_text: str                 # runtime_style_prompt.md 内容
    entries: list[PlannedEntry]       # 世界书条目（可能为空列表）

def style_artifacts_fresh(run_dir, config, *, endpoint_fingerprint: str = "") -> bool
def ensure_style_artifacts(run_dir, config, provider=None, *, log=None) -> StyleArtifacts
```

- `style_artifacts_fresh`：`style_profile.json` 与 `runtime_style_prompt.md` 存在，
  且 `profile.inputs_fingerprint == compute_inputs_fingerprint(...)`。
- `ensure_style_artifacts`：fresh → 直接加载返回；否则 `provider is None` →
  抛 `StyleError("风格产物不存在或已过期，需要 LLM 引擎自动蒸馏")`；
  有 provider → `run_style_observation(resume=True)` → `run_style_compile()` →
  加载返回。`config.style.worldbook_entries=False` 时 `entries=[]`。

### 6.5 `src/novel_to_tavern/render/html_policy.py`（新建）

```python
class HtmlPolicyError(RuntimeError): ...

@dataclass(frozen=True)
class HtmlPolicy:
    allowed_properties: tuple[str, ...]
    allowed_font_sizes: tuple[str, ...]
    color_palette: dict[str, str]
    max_suggested_spans_per_reply: int
    @classmethod
    def from_config(cls, cfg) -> "HtmlPolicy"  # 读 HtmlRenderingConfig；非法值抛 HtmlPolicyError

def build_html_rules_text(policy: HtmlPolicy) -> str
def build_html_entry(policy: HtmlPolicy) -> PlannedEntry
def validate_html_sample(text: str, policy: HtmlPolicy) -> list[str]  # 违规原因，空=通过
```

- `build_html_rules_text` 内容要点（全部从 policy 渲染，不写死值）：
  默认纯文本/Markdown；仅在确有视觉收益时（章节切换、关键揭示、内心独白、
  书信/密令/档案）使用；只用 `<span style="...">`；只允许
  `allowed_properties`；字号只能取 `allowed_font_sizes`；颜色只能取色板
  （列出 `语义名: #hex` 对照表与用途建议，如 muted=时间地点标注、emphasis=关键线索、
  warning=警示、mystery=悬念）；单条回复通常 0–N 个片段；禁止 script/iframe/
  事件属性/外部资源/其他标签/任意 class/id；不改变叙事内容与事实；不确定就不用。
- `build_html_entry`：`entry_id="wb_rendering_html"`、`title="输出格式：受控 HTML 规范"`、
  `category="rendering"`、`always_on=False`、`priority=30`、
  `keys=["输出格式规范", "排版规则", "HTML格式", "视觉样式", "字号颜色"]`、
  `quality_flags=["非 canon：输出呈现规则"]`，正文末尾附「本条目是格式约定，不是世界设定」。
- `validate_html_sample`：用标准库 `html.parser.HTMLParser` 解析；
  规则 —— 只允许 `span` 标签；只允许 `style` 属性；style 内只允许白名单属性；
  `font-size` 值 ∈ 白名单；`color` 值 ∈ 色板 hex 集合；`font-style` 值只能 `italic`；
  无嵌套 span；无其他标签/属性 → 返回违规原因列表。**仅用于测试本项目生成的
  文本与静态 fixture，不是 Tavo 运行时过滤器。**

### 6.6 `style/__init__.py` / `render/__init__.py`

导出：`run_style_observation`、`run_style_compile`、`ensure_style_artifacts`、
`style_artifacts_fresh`、`StyleArtifacts`、`StyleProfile`、`StyleObservation`、
`build_style_entries`、`check_style_no_plot_leak`、`StyleError`（统一放
`style/__init__.py`，`StyleObserveError/StyleCompileError/StyleLeakError` 继承它）；
`HtmlPolicy`、`build_html_entry`、`build_html_rules_text`、`validate_html_sample`、
`HtmlPolicyError`。

---

## 7. 缓存与指纹

### 7.1 缓存键（写 `config.pipeline.cache_dir`，仿 `extract/runner.py:132`）

```python
payload = {
    "kind": kind,                          # "style_observe" | "style_merge" | "style_compile" | "style_compress"
    "model": config.llm.extraction_model,
    "endpoint_fingerprint": provider.endpoint_fingerprint,
    "prompt_version": 对应阶段版本号,
    "prompt_template_sha256": prompt_template_hash(),
    "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
    "profile_schema_version": PROFILE_SCHEMA_VERSION,
    "input_sha256": 输入内容 sha256（chunk 文本 / 批次笔记 JSON / 编译输入 JSON / 待压缩文本）,
    "temperature": config.llm.temperature_extract,
    # observe 额外带 chunk_sha256；compile 额外带 max_runtime_tokens 与 supplementary sha256
}
key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
```

### 7.2 `compute_inputs_fingerprint`（产物新鲜度判定）

组成：`kind="style_pipeline"`、四个 prompt 版本号、`prompt_template_hash()`、
两个 schema 版本、`config.llm.extraction_model`、endpoint 指纹（调用方给，
没有则空串）、manifest 全部来源 `sha256` 列表、`observe_max_chunks`、
`merge_batch_size`、`max_runtime_tokens`、supplementary 文件 sha256（无则 null）。
拼接 JSON `sort_keys` 后 sha256。写入 `profile.inputs_fingerprint`。

**export 的懒装配逻辑**（`_cmd_export`）：

```python
provider = None
if config.style.enabled:
    from ..style.pipeline import style_artifacts_fresh
    if not style_artifacts_fresh(run_dir, config):
        try:
            provider = build_provider(config, log=log)
        except ProviderError as exc:
            print(f"风格产物不存在/已过期且无法装配引擎：{exc}", file=sys.stderr)
            return 1
```

`export()` 内部 `ensure_style_artifacts(run_dir, config, provider=provider)`：
fresh 时不需要 provider（无凭据也能导出）；stale 且无 provider → `StyleError`
→ CLI 捕获打印「需要 LLM 引擎：请配置凭据，或先用 file provider 预生成，或关闭
style.enabled」。

---

## 8. 产物布局

```text
runs/<run_id>/author_style/
  observations/<chunk_id>.json        # StyleObservation
  observations/_errors/<chunk_id>.json
  observations/_index.json            # {"done": [...], "failed": [...]}
  merged/batch_000.json …             # 合并中间产物
  style_profile.json                  # StyleProfile（含 inputs_fingerprint）
  style_profile.md                    # 人工阅读版
  runtime_style_prompt.md             # 注入 Description 的唯一风格主体
  style_worldbook_entries.json        # 8 组 PlannedEntry（export 读取此文件）
  style_eval_cases.json               # ≥6 个评估样例
  audit.md                            # 覆盖率/丢弃项/局限/复核项
```

---

## 9. 导出集成（精确到改动点）

### 9.1 `timeline/worldbible.py`

`EntryCategory` Literal 增加 `"author_style"`、`"rendering"`。

### 9.2 `export/runner.py`

1. 签名：`def export(run_dir, config, *, start_chapter=None, provider=None, log=None)`。
2. 读完 manifest 后：
   ```python
   style_artifacts = None
   if config.style.enabled:
       from ..style.pipeline import ensure_style_artifacts
       style_artifacts = ensure_style_artifacts(run_path, config, provider, log=log)
   ```
3. Description（`runner.py:222` mode_notice 之后）：
   ```python
   if style_artifacts is not None:
       greetings.description += "\n\n【叙事风格规范】\n" + style_artifacts.runtime_text
   ```
   严格档 `_export_strict` 同样追加（风格规则与章节无关）。
4. `_assemble_entries(..., extra_entries: list | None = None)`：在 `entries.extend(triggered)`
   后追加 `entries.extend(extra_entries or ())`。
5. `extra_entries` 组装（默认档与严格档共用）：
   ```python
   extra = list(style_artifacts.entries) if style_artifacts else []
   if config.rendering.html.enabled:
       from ..render.html_policy import HtmlPolicy, build_html_entry
       extra.append(build_html_entry(HtmlPolicy.from_config(config.rendering.html)))
   ```
6. 严格档在 `_assemble_entries` 前：
   `check_style_no_plot_leak(extra, start_chapter)`（泄漏 → `StyleLeakError` →
   包装成 `ExportError`，不产出严格档）。
7. `export_manifest.json` 增加：
   ```json
   "style": {"enabled": ..., "profile_id": ..., "inputs_fingerprint": ...,
             "runtime_tokens_est": ..., "worldbook_entries": <条数>},
   "rendering": {"html_enabled": ..., "mode": "controlled_span",
                 "note": "提示词约束，无 Tavo 运行时过滤"}
   ```
   未启用时对应段写 `{"enabled": false}`。
8. `audit.md` 增加两节：风格（启用状态、fingerprint、观察覆盖率、runtime 粗估
   token、条目数、压缩丢弃项数、supplementary 是否使用）；HTML（启用状态、
   色板/字号摘要、明确写「无运行时过滤，Tavo 渲染效果以实测为准」）。

### 9.3 `cli.py`

- 新增子命令（argparse 块仿 `verify_parser`）：
  - `style-observe`：`--run-id`（必填）、`--no-resume`、`--limit N`；
    handler 仿 `_cmd_extract`（load_config → `_resolve_run` → `build_provider` →
    `run_style_observation` → 打印 done/skipped/failed 与报告路径；`ok=False` 返回 1）。
  - `style-compile`：`--run-id`（必填）、`--no-resume`（透传为强制重编译：
    调 compile 前清掉 `author_style/` 下除 `observations/` 外的产物）；
    handler 同上，打印 profile_id、runtime 粗估 token、条目数、audit 路径。
- `_cmd_export`：按 §7.2 懒装配 provider；`export(..., provider=provider, log=log)`；
  `except (ExportError, StyleError)` 统一友好报错。
- `main()` 里注册两个新分支。

---

## 10. 测试规格（全部离线；LLM 一律 `FileProvider` + 预生成响应）

预生成响应目录命名（`FileProvider._path_for` = `<chunk_id>.json`）：
观察用真实 chunk_id；合并 `style_merge_batch_000.json` …；
编译 `style_compile.json`；压缩 `style_compress.json`。
fixture 全部合成（迷你小说 3 章，禁止用真实原文）；可复用 `tests/conftest.py`
既有 run 构建件（先读 conftest 再写）。

| 测试文件 | 用例（名称 → 断言要点） |
|---|---|
| `tests/test_style_schema.py` | `test_profile_roundtrip`（构造→dump→validate 相等）；`test_unknown_field_rejected`；`test_dimension_defaults_unknown`；`test_eval_case_min_fields` |
| `tests/test_style_observe.py` | `test_writes_per_chunk_json`；`test_quote_located_and_bad_quote_dropped`（一定位成功一编造，后者进 quotes_dropped）；`test_bad_json_quarantined_then_raises`；`test_cache_hit_skips_engine`（二次运行引擎调用数不增）；`test_cache_invalidation_on_chunk_change`；`test_resume_skips_done`；`test_select_chunks_all_when_zero`；`test_select_chunks_spread_deterministic`（首尾必含、两次调用结果相同） |
| `tests/test_style_compiler.py` | `test_produces_six_artifacts`；`test_profile_schema_enforced`（缺字段→报错且进隔离）；`test_merge_batch_count`（65 份观察、batch 30 → 3 批）；`test_runtime_over_budget_triggers_compress`（预生成压缩后文本 → 成功且 audit 含 dropped）；`test_compress_still_over_budget_fails`（报错 + audit 记录，不截断）；`test_fingerprint_changes`（改来源 hash / 改预算 / 加 supplementary → fingerprint 变）；`test_second_run_cache_hit`；`test_supplementary_missing_raises` |
| `tests/test_style_worldbook.py` | `test_eight_groups_ids_titles`；`test_all_triggered_not_always_on`；`test_unknown_dimension_group_skipped`；`test_keys_do_not_match_probes`（§6.3 禁用句逐条过触发匹配逻辑）；`test_entries_json_roundtrip`；`test_leak_check_raises_on_future_chapter` / `test_leak_check_passes_within_range` |
| `tests/test_render_html.py` | `test_bad_color_rejected` / `test_bad_size_rejected` / `test_unknown_property_rejected` / `test_empty_palette_rejected`（均走 `load_config` 或 `HtmlPolicy.from_config`）；`test_rules_text_whitelist_only`（对渲染文本里的全部示例跑 `validate_html_sample` → 无违规；文本不含 script/iframe/事件属性）；`test_validate_sample_matrix`（合法单属性/多属性/纯文本通过；script、onclick、div、越权 CSS 属性、`font-style: oblique`、白名单外字号/颜色、嵌套 span → 各有对应违规原因）；`test_entry_triggered_not_always_on_and_keys`；`test_export_entry_present_when_enabled_absent_when_disabled` |
| `tests/test_style_export_integration.py` | `test_disabled_is_baseline`（默认配置导出：Description 无【叙事风格规范】、无 author_style/rendering 条目）；`test_enabled_fresh_artifacts_no_provider`（预置产物 → 不传 provider 导出成功，Description 含分节且只出现一次）；`test_enabled_missing_artifacts_auto_runs`（file provider 预生成全套 → export 自动跑 observe+compile 并产出 6 文件）；`test_stale_artifacts_rerun`（改 fingerprint 组件 → 重跑）；`test_parity_with_style_entries`（内嵌/独立 parity 通过）；`test_strict_export_leak_check`（伪造含未来章节的风格条目 → ExportError）；`test_canon_isolation`（风格运行前后 facts/entities/timeline.json 字节不变） |
| `tests/test_config.py`（改） | 新段默认值、`summarize` 新键、两条新 warning；`allow_html_beautification` 相关断言删除/改为「该键已移除，写入报 unknown 字段」 |
| `tests/test_config_wiring.py`（改） | 新键「定义→消费→测试」接线断言 |
| `tests/test_docs_consistency.py` | 无需改代码；README/RUN_REPORT 的测试计数数字要同步（见 §11） |

---

## 11. 文档更新清单（Phase E4 逐项执行）

| 文件 | 改动 |
|---|---|
| `README.md` | 功能列表加「可选：作者风格自动蒸馏」「可选：受控 HTML 世界书条目」；非目标中「不做 HTML 美化」改为「不支持任意 HTML 美化（受控 span 子集以世界书条目形式可选提供）」，MVU/EJS 表述不变；CLI 列表加 `style-observe`/`style-compile`；验证等级表加两行（风格管线=单元测试级；HTML=静态校验级，Tavo 渲染未实测）；离线测试计数同步 |
| `docs/ARCHITECTURE.md` | 总体流程图加旁路风格管线；§2.B 修订注明：「导出阶段不调 LLM」新增一个例外 —— `style.enabled=true` 时导出会触发风格蒸馏（产出风格资料，非 canon 事实）；三层模型注明 `author_style`/`rendering` 条目属 Runtime 层、非 canon |
| `docs/CONFIG_REFERENCE.md` | 新增 `style.*` 6 键、`rendering.html.*` 6 键的「定义 → 消费 → 测试」行；删 `allow_html_beautification` 行 |
| `docs/TAVO_IMPORT_CHECKLIST.md` | 加 HTML 小节：世界书条目存在性、关键词触发、浅色/深色下色板可读性、字号、斜体、纯文本回退、无裸露标签；加风格小节：Description 分节存在、风格条目触发验证。全部标「待实测」 |
| `docs/RUN_REPORT.md` | 测试计数同步；新模块状态行 |
| `docs/THIRD_PARTY_NOTICES.md` | 加 Nuwa（MIT）条目：仅作方法论参考，本仓库不分发其代码/文件 |
| `docs/AUTHOR_STYLE_PIPELINE.md`（新） | Nuwa 方法论 → 本仓库三段式管线的映射（表达 DNA→观察维度、反模式→anti_patterns、诚实边界→limitations；心智模型/Agentic Protocol 等咨询型内容不采用）；操作手册：如何启用、如何离线预生成、缓存与指纹、局限 |
| `docs/HTML_RENDERING.md`（新） | 白名单、配置、色板语义、触发条目机制、「提示词非运行时沙箱」声明、Tavo 人工验证清单 |
| `docs/IMPLEMENTATION_PLAN.md` | 末尾追加一节指向本文件 |
| `config/config.example.yaml` | 见 §3.4 |

---

## 12. 分阶段执行

### Phase E0 — 开工确认

- [x] 全量测试绿：`.venv/bin/python -m pytest`（基线 605 项）。
- [x] git working tree 干净；从独立分支开工（`feat/style-distillation-and-html-entry`）。
- [x] 通读本文件 §1 基线表中的每个位置，确认无漂移。

验收：无既有功能被删改；本计划经用户确认。

### Phase E1 — schema + 逐块观察

- 实施 §4、§5.1、§6.1；`style-observe` CLI（§9.3 第一条）。
- 测试：test_style_schema.py、test_style_observe.py 全绿。

验收：fixture 离线跑通；引文定位失败被丢弃并计数；坏 JSON 隔离且报错；
缓存/续跑/抽样确定性全过；不需要 API。

### Phase E2 — 编译 + 导出自动蒸馏

- 实施 §5.2–5.4、§6.2–6.4、§7、§8、§9.1–9.3。
- 测试：test_style_compiler.py、test_style_worldbook.py、
  test_style_export_integration.py 全绿。

验收：export 在 fresh 时无引擎可导出；缺失/过期时自动蒸馏（file provider 预生成）；
预算超限走压缩、再超报错不截断；parity 通过；严格档泄漏拦截生效；canon 文件字节不变。

### Phase E3 — 受控 HTML 条目

- 实施 §3.1（RenderingConfig）、§3.2–3.4、§6.5、§9.2 第 5 条。
- 测试：test_render_html.py 全绿；config 相关测试同步。

验收：非法配置 `config-check` 报错；开启/关闭互不影响（且都不影响模块 A）；
条目为触发式；规则文本只含白名单；样例矩阵全过。

### Phase E4 — 文档、评估与实测

- 执行 §11 全部；跑通 import→…→export 全链路（可用 file provider）。
- 用 `style_eval_cases.json` 组织一次风格一致性评估（人工或 agent），结论写
  `docs/RUN_REPORT.md`；Tavo 验证按更新后的 checklist 逐项标「实测/未实测」。

验收：测试计数三处一致；README 验证等级不超前声称；报告区分
单元测试 / 静态 JSON 校验 / Tavo 实际导入 / 真实对话行为四档。

---

## 13. 风险

1. **观察成本**：全部 156 块各一次调用。`observe_max_chunks` 提供确定性等距抽样；
   报告必须写明观察覆盖率，抽样结果不冒充全量。
2. **编译编造「作者习惯」**：提示词要求 unknown、schema 要 evidence；`audit.md`
   列置信度分布与人工复核项；测试断言低证据维度不高置信。
3. **风格条目触发误命中**：组合词 + 禁用句探测（§6.3），沿用剧情主线条目前例。
4. **严格档剧透**：风格条目不含章节指涉是编译提示词要求，导出时
   `check_style_no_plot_leak` 结构性拦截（双保险）。
5. **Description 膨胀**：只有【叙事风格规范】一个分节进 Description（HTML 已移入
   世界书）；`max_runtime_tokens` 硬约束 + audit 报 Description 粗估总长。
6. **Tavo 渲染不可保证**：HTML 只是提示词约束；文档与 audit 一律写明无运行时过滤。
7. **导出语义变化**：`style.enabled` 时 export 可能发起 LLM 调用。文档（README、
   ARCHITECTURE）明确此例外；默认关闭不受影响；fresh 产物不需要凭据。
8. **配置迁移**：删 `allow_html_beautification` 后旧配置报 unknown 字段 ——
   报错即迁移指引，CONFIG_REFERENCE 写明替代键。

---

## 14. 交付报告要求（每个 Phase 完成后）

1. 实际变更文件及目的；2. 新 CLI/config 接口与示例；3. 测试命令与真实结果；
4. 风格观察覆盖率、runtime token 粗估、世界书条目数、导出差异；
5. Tavo 实测做了什么、没做什么；6. 当前限制与下一步建议。

不得以「提示词要求模型遵守」为由声称 HTML 白名单获得运行时保证；
不得以风格档案生成成功为由声称与作者风格完全一致。
