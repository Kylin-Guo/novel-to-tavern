# Novel-to-Tavern：作者风格蒸馏与受控 HTML 输出优化计划

> 面向本地 Agent / Claude Code 的实施计划。请先审阅当前仓库，再按阶段执行。本文件是计划，不代表功能已经实现。
>
> 计划基线：`Kylin-Guo/novel-to-tavern` 当前公开 README、`docs/ARCHITECTURE.md`、`docs/IMPLEMENTATION_PLAN.md` 与 `nuwa-skill` 当前公开 `SKILL.md`。计划整理日期：2026-10-20。

## 0. 给 Agent 的首要指令

**先审查，后修改；先做最小切片，不要直接重构整个项目。**

开始时：

1. 检查当前 Git branch、working tree、近期提交、实际文件树和所有现有测试。
2. 阅读 `AGENTS.md`、`CLAUDE.md`（如存在）、`README.md`、`docs/ARCHITECTURE.md`、`docs/IMPLEMENTATION_PLAN.md`、`docs/DATA_MODEL.md`、当前配置 schema、导出器、prompt 模板、测试与 `docs/THIRD_PARTY_NOTICES.md`（文件存在时）。
3. 阅读 Nuwa 当前版本的 `SKILL.md`、README 和 LICENSE：<https://github.com/alchaincyf/nuwa-skill>。不要依靠旧版摘要猜测当前工作流。
4. 创建 `docs/PLAN.md` 或当前项目规定的阶段计划，记录拟修改文件、测试命令、风险和不在本阶段范围内的内容。
5. 先向用户简要报告当前仓库现状与具体实施计划，再开始编码。若仓库已有同类功能，优先增量完善，不要重复新增。
6. 不得覆盖或清理 `runs/`、小说源文件、已生成卡片或用户现有配置。每个变更都必须可回滚。

## 1. 项目目标和本次范围

项目本身仍然是**小说到 SillyTavern / Tavo 可导入文件的转换工具**，不是新酒馆、Web 应用或 RPG 平台。

本次只加入两类可独立启用的增强：

1. **作者风格蒸馏与运行时风格规范**：复用 Nuwa 的完整蒸馏方法作为研究/分析流程，然后将结果重新组织成适用于小说叙事的结构化风格档案；再生成一份短小的运行时规则注入主角色卡 Description，并将完整风格资料归档在项目中，也可分组写入世界书。
2. **受控 HTML 文本呈现**：在角色卡中加入可选的输出格式规则，使模型仅在确有叙事价值时选择性使用字号、颜色和斜体。第一版不做动态界面和任意 HTML 生成。

### 明确不做

- 不实现 MVU。
- 不实现 EJS。
- 不新增数据库、向量数据库、Web 服务、移动端或新聊天客户端。
- 不把完整 Nuwa 调研原文或完整报告无差别注入每轮请求。
- 不把全部风格档案设置为常驻世界书条目。
- 不允许任意 JavaScript、外部资源、事件处理器、动画或完整 HTML 页面。
- 不改变现有原子事实、实体归一、时间线、知识边界和无剧透导出的基本语义。
- 不因风格蒸馏修改或覆盖原著事实。
- 不默认下载、存储或公开再分发未经授权的小说全文。

## 2. 对当前项目的理解和集成原则

当前 `README.md` 将项目定位为多阶段流程：`ingest → extract → resolve → verify → timeline → export`，并强调来源证据、章节时间边界、导出校验以及可在 Tavo 中导入的 Character Card V2 + 内嵌世界书。README 中当前仍声明不做 MVU / EJS / HTML / CSS 美化，本次实施需要在实现完成后同步更新该描述，不应提前声称功能已经存在。

新功能应作为**可选的旁路资料流**集成：

```text
小说文本 + 可核实的作者资料
          │
          ├── 现有 canon 管线：事实 / 实体 / 时间线 / 世界书规划
          │
          └── 作者风格管线：完整蒸馏资料 → 文学风格档案 → 精简运行时风格规范
                                                     │
现有导出器 ─────────────────────────────────────────┤
                                                     ▼
                      主卡 Description（短、常驻） + 风格世界书条目（完整、按需）
                                                     │
                                                     ▼
                       受控 HTML 输出指令 + Character Card V2 / Worldbook 校验
```

### 关键设计原则

- 作者风格是**旁路的创作风格资料**，不是 canon 事实。不能进入原子事实列表、不能成为角色身份或世界规则，也不能修改已确认的原著设定。
- 原著小说应是文学风格分析的主要证据；作者访谈、公开创作谈、随笔等外部资料是补充证据，不能取代作品自身的写作表现。
- 完整蒸馏与运行时风格规范必须分别存储，具有独立版本和哈希。
- 输出 JSON 继续由现有 serializer 生成，LLM 不可直接手写最终卡片 JSON 后绕过校验。
- 新功能默认关闭或不改变旧行为，用户明确启用后才参与导出；没有风格档案时，现有导出结果应保持兼容。
- 不让风格提示词变成每轮冗长的文学评论：Description 只注入经过编译的精简规则；完整档案放在本地，世界书保存分组版本但不默认全部常驻。
- Tavo 的 HTML 能力需以实际导入与渲染测试为准；JSON 合法不等于聊天内容中的 HTML 一定被渲染。

## 3. 模块 A：使用 Nuwa 方法完整蒸馏作者，再编译成小说风格档案

### 3.1 不要将 Nuwa 视为一个现成的“文学风格分析 API”

Nuwa 当前仓库的定位是从人物/主题资料中提取思维框架、决策启发式、表达特征、反模式和诚实边界，并生成可运行的 Skill。它的多源研究与验证流程值得复用，但它原生产物可能包含人物认知架构、回答流程、公开人物研究等内容，并非所有字段都适合直接用于小说旁白。

因此采用两段式方法：

1. **完整 Nuwa 蒸馏阶段**：尽可能沿用用户安装的 Nuwa Skill 的原始工作流，分析可用小说文本和经过核验的作者公开资料，保存完整产物与来源清单。
2. **Novel-to-Tavern 文学编译阶段**：将完整 Nuwa 产物与小说语料观察结果整理为文学风格档案。过滤掉不适合小说生成的咨询型流程、实时研究流程、面向用户的建议格式等内容；不得因此丢弃可能与文学创作相关的表达规律。

不要求在 Python 程序内部重新实现 Nuwa 的多 Agent 调研。第一版可由用户在兼容的 Agent 环境中运行 Nuwa，然后把完整产物导入 Novel-to-Tavern。项目负责标准化、校验、精简和生成酒馆文件。这样既保留 Nuwa 完整工作流，又避免把外部 Skill 的运行时依赖强塞进核心 CLI。

### 3.2 数据输入要求

至少支持以下输入：

- 已完成的 Nuwa 完整蒸馏结果目录或 Markdown 文件。
- 用户合法持有/有权处理的小说 TXT / Markdown 文档，最好包含章节结构。
- 可选的作者公开访谈、创作随笔、序跋或其他可靠公开资料的链接/笔记。
- 可选的用户补充说明，例如作品版本、译本、目标叙事视角、需不需要兼容多部作品的风格差异。

约束：

- Nuwa 来源研究与小说内部证据分开记录。
- 不得把作者访谈中的自我描述自动当成作品的客观风格事实；需与作品文本交叉检查。
- 不要自动访问或下载侵权全文；仅处理用户提供、合法可访问或获得授权的材料。
- 对不确定的作者归属、译本差异、译者风格和共同创作作品，必须在报告中标明局限。

### 3.3 输出文件

建议建立独立于 canon 数据的目录，实际路径须与当前 run 目录规范一致：

```text
runs/<run_id>/author_style/
  nuwa_full/                      # 外部 Nuwa 原始完整产物，只读保存
  sources.json                    # 资料清单、URL、类型、访问日期、可信度
  style_profile.json              # 结构化文学风格档案
  style_profile.md                # 可供人工阅读的完整整理报告
  runtime_style_prompt.md         # 精简后供角色卡常驻使用
  style_worldbook_entries.json    # 完整档案拆分成若干世界书条目
  style_eval_cases.json           # 风格一致性回归样例
  audit.md                        # 覆盖率、依据、局限与人工复核项
```

如果现有项目对中间产物的命名或目录另有规定，应沿用现有约定，不要为了照搬上面的目录而重复存储同一份文件。

### 3.4 `style_profile.json` 最低数据结构

结构化字段应包括：

- `schema_version`、`profile_id`、`author_label`、`works_in_scope`、`created_at`。
- `source_manifest[]`：来源类型（小说/访谈/随笔/其他）、来源定位、访问时间、可靠性说明。
- `narrative_voice`：叙事视角、叙事距离、旁白立场、视角切换规律。
- `sentence_rhythm`：长短句变化、段落节奏、句式变化在不同场景中的功能；不要只存不带语境的单一平均值。
- `description_patterns`：环境、动作、感官细节、人物外观和空间描写的选择规律。
- `figurative_language`：意象、比喻、象征、重复母题的类型与使用场景。
- `dialogue_patterns`：对话节奏、潜台词、动作与对白的组合方式；与角色各自说话习惯分开。
- `psychological_narration`：内心描写、情绪表达的显隐程度、克制与爆发的节奏。
- `scene_pacing`：铺垫、转折、悬念、冲突升级和收束方式。
- `genre_tone`：适用题材/作品的总体基调与变化范围。
- `anti_patterns[]`：与本作品风格不相容的生成倾向，以及理由。
- `contextual_variants[]`：对白、动作场面、心理戏、环境铺陈、高潮等场景是否使用不同风格规则。
- `evidence_refs[]`：每项重要结论对应的章节/段落/外部来源及短证据或引用定位。
- `confidence`、`limitations[]`、`human_review_items[]`。

不要为每个维度强行填值。如果小说证据不足，记录 `unknown` 或低置信度，而不是编造“作者习惯”。统计数据作为辅助观察，必须结合语境解释，不能把平均句长等数字直接当成写作规则。

### 3.5 版权与证据长度

- 完整档案应优先保存章节定位、行号/段落范围、摘要和短证据，不复制大段小说原文。
- 避免在运行时提示词或世界书中放入大量可替代原著阅读的文本摘录。
- 风格总结应该描述抽象、可操作的表达特征和叙事机制，不要求逐字复现原作的独特句子、长段文字或标志性表达。
- 原文来源只用于核验，不得因为它属于“风格模块”就跳过现有证据和版权保护原则。

### 3.6 运行时精简规则

`runtime_style_prompt.md` 是注入 Description 的唯一风格主体。它应：

- 以行为规则表达风格，而不是给模型一长串形容词。
- 尽量用“如何组织段落/如何控制揭露节奏/如何描写人物情绪”这类可执行规则。
- 将作者旁白风格和 NPC 台词风格明确分离。
- 不重复角色卡已经存在的世界模拟器核心规则。
- 不重复原著人物事实、时间线和世界规则。
- 设定可配置的 Token 上限；默认建议 `max_runtime_tokens` 为 800，实际值以目标模型和提示词预算测试结果调整。
- 如果精简过程删掉了一项重要结论，必须在 audit 中说明；不能静默丢弃高置信度规律。
- 附带“不要生搬统计指标；优先保留情境功能”的原则，防止模型把某些写作特征机械化地应用到每句话。

### 3.7 完整风格内容进入世界书的策略

用户希望完整风格资料也能在世界书中保留，因此生成分组条目，例如：

- `作者风格：总体叙事原则`
- `作者风格：句式与段落节奏`
- `作者风格：对话与潜台词`
- `作者风格：心理描写`
- `作者风格：环境与感官描写`
- `作者风格：意象与修辞`
- `作者风格：场景节奏与高潮`
- `作者风格：反模式与风格边界`

规则：

- 世界书条目应保存完整的**整理后风格规则**，而不是直接把整个 Nuwa SKILL.md 原样复制进去。
- 原始 Nuwa 完整产物保留在本地 `nuwa_full/`；世界书中的风格条目是为角色扮演设计的完整文学档案版本。
- 只有短版全局原则适合放入 Description 常驻。详细风格条目默认不要全部 `constant`，避免 Token 膨胀。
- 对是否设置关键词、次级关键词、`constant`、`position`、`insertion_order` 等参数，由当前 serializer 按现有格式 schema 生成，不要凭空猜测字段或照搬固定值。
- 风格条目不会因为位于世界书就自动影响模型；报告必须区分“被归档”“可以按关键词触发”“本轮实际已注入”。
- 如果某条细节规则对所有轮次都不可或缺，应将其浓缩到运行时风格规范，而不能仅寄希望于关键词命中。

### 3.8 建议的 CLI / 配置接口

先审阅现有 CLI 和 config schema，再以最小改动设计命令。命名可调整，但语义应覆盖：

1. 导入完整 Nuwa 产物（例如 `n2t style-import --run-id ... --input <path>`）。
2. 编译文学风格档案与精简运行时提示词（例如 `n2t style-compile --run-id ...`）。
3. 在导出阶段可选引用已编译档案（例如 `n2t export --run-id ... --style-profile <path>`，或者使用配置指定）。

要求：

- 缺少风格输入时，既有 `export` 完全按原行为工作。
- `style-import` 不覆盖原始输入；重跑输出新版本或显式 `--overwrite`。
- Cache key 至少包括小说相关输入哈希、Nuwa 文件哈希、编译提示词版本、目标模型和参数。
- 完整 Nuwa 运行可在外部 Agent 环境中进行，不要求每次 `n2t` 调用都自动启动 Web research 或多 Agent。

## 4. 模块 B：受控 HTML 输出规范

### 4.1 功能定位

HTML 是用于**视觉呈现**的可选输出能力，不是事实/时间线/世界书的核心数据模型。第一版只支持：

- 文字大小（`font-size`）
- 文字颜色（`color`）
- 斜体（`font-style: italic`）

默认保持普通文本或 Markdown。模型只能在章节切换、关键揭示、角色内心、书信/密令/档案等确有视觉收益的场景选择性使用。不要要求每轮、每段都加 HTML。

### 4.2 安全且可预测的 HTML 子集

第一版默认只允许简单 `<span>` 标签与三种 CSS 属性。示例：

```html
<span style="font-size: 1.12em; font-style: italic;">我们去哪里？漂亮公主，我们去哪里？</span>
<span style="color: #B08A38;">这是一条关键线索。</span>
<span style="font-size: 0.88em; color: #9298A3;">三日后 · 王都</span>
```

明确禁止：

- `<script>`、`<iframe>`、表单、事件属性（如 `onclick`）、任意 JavaScript。
- 外部图片、外部 CSS、远程字体、外部 URL、网络请求。
- 任意 class/id、复杂嵌套或不在白名单中的 HTML 标签（除非未来单独设计并测试）。
- 未在白名单中的 CSS 属性、CSS 函数或可执行内容。
- 为了视觉效果改写事实、强行突出普通句子或连续滥用颜色。

### 4.3 字号与颜色设计

- 使用可配置的字号白名单，初版可包含 `0.88em`、`1em`、`1.08em`、`1.12em`，实际数值可根据 Tavo 测试微调。
- 使用有限的预设色板和语义用途，例如 `muted`、`emphasis`、`warning`、`mystery`。配置映射到具体十六进制颜色，避免模型每次随意编造颜色。
- 颜色要考虑浅色/深色主题可读性。若无法自动检测主题，提供保守的中性色/强调色配置，不声称两种主题都会完美显示。
- 斜体可以用 `font-style: italic`；普通斜体也可用 Markdown，但导出提示词统一说明允许范围。
- 对单条回复中 HTML 标记的数量给出软性建议（例如通常 0–3 个片段），不是不可逾越的硬限制；关键在于有无叙事目的。

### 4.4 提示词注入与配置

新增独立模板，如 `prompts/html_rendering_rules.md`（以当前目录规范为准），由导出器在 HTML 功能启用时加入角色卡合适的指令位置。

提示词至少说明：

- 默认纯文本/Markdown。
- 只有在明确需要视觉强调时才用 HTML。
- 仅用 `<span>` 和白名单属性。
- 不改变叙事内容和事实。
- 不使用 JavaScript、外部资源和其他 HTML 标签。
- 颜色与字号从配置白名单中选择。
- 如果无法确定适合的样式，宁可不用 HTML。

配置建议：

```yaml
rendering:
  html:
    enabled: true
    mode: controlled_span
    allowed_properties:
      - font-size
      - color
      - font-style
    allowed_font_sizes: ["0.88em", "1em", "1.08em", "1.12em"]
    color_palette:
      muted: "#9298A3"
      emphasis: "#B08A38"
      warning: "#B05A5A"
      mystery: "#7C8FA6"
    max_suggested_spans_per_reply: 3
    allow_javascript: false
    allow_external_resources: false
```

这是建议配置形状，不得未经检查直接覆盖当前配置；Agent 应按项目现有的 Pydantic/YAML schema 命名方式合并，并为每个字段增加测试。

### 4.5 重要实现边界：Prompt 不是运行时沙箱

由于 Novel-to-Tavern 导出的是角色卡，而真实模型输出发生在 Tavo 中，导出器只能向模型提出 HTML 约束，不能仅凭提示词保证模型每次都遵守白名单。除非项目以后实现 Tavo 端的后处理器，否则不要声称运行时 HTML 得到了强制安全过滤。

本次至少需要：

- 校验本项目生成的提示词片段与静态 HTML fixture。
- 测试角色卡 JSON 中规则是否正确注入。
- 在 `docs/TAVO_IMPORT_CHECKLIST.md` 中增加手工验证：浅色/深色背景、颜色、字号、斜体、普通文本回退、标签能否正常渲染。
- 明确记录 Tavo 实测和静态测试的区别。

## 5. 与 Description、Worldbook 和原有数据的合并规则

### Description 合并

- 不得覆盖原来的角色卡 Description。应由 serializer 在清晰的分段/模板机制中把“世界模拟器核心规则”和“运行时作者风格规范”合并。
- 风格规则放在明确的分节中，例如 `【叙事风格规范】`，避免与世界事实混淆。
- 注入顺序应以当前提示词组装逻辑为准；需要确认 Description 会实际进入目标请求，不能只因 JSON 字段存在就假定有预期权重。
- 若无 style profile 或配置关闭，输出应与旧版一致（除了明确记录的版本元数据差异）。
- 完整风格档案不要全部常驻 Description。

### Worldbook 合并

- 保留既有角色、地点、组织、事件与规则条目。
- 风格条目应有独立类别/命名空间，避免把作者风格关键词混入普通人物/地点实体。
- 内嵌世界书与独立世界书必须由同一个 canonical list 序列化，保持现有一致性校验。
- 不能因为写入作者风格档案而放宽未来剧情隔离。Strict `--start-chapter N` 导出时，风格信息可以存在，但不得从风格条目泄漏章节 N 之后具体的剧情事实、事件或专有情节。
- 对作者风格中的作品例证只保存短片段/定位，避免将大段原著复制进公开导出文件。

## 6. 测试与验收要求

### 6.1 作者风格模块

- [ ] 未启用风格模块时，现有管线和输出行为保持兼容。
- [ ] 能导入 Nuwa 输出并验证必需/可选字段；缺少信息时给出警告，不能伪造补齐。
- [ ] 完整 Nuwa 原始产物与规范化 `style_profile` 分开保存。
- [ ] 运行时风格规范有可配置 Token 上限，压缩前后字段和高置信度规律有覆盖报告。
- [ ] 小说文本是主要证据，外部资料有来源类型和 URL/定位；未经核实的网页内容不会自动被标为作品事实。
- [ ] 风格档案不会进入现有 canon fact 集合，不改变角色/事件事实。
- [ ] 同一输入与同一提示词版本可缓存；修改原文、Nuwa 输出或编译提示词后缓存失效。
- [ ] 生成风格世界书条目后，内嵌/独立导出一致。
- [ ] 严格章节导出不会将后续章节中的专有剧情事实塞进风格条目。
- [ ] 提供至少 6 个风格评估案例：场景铺陈、人物对话、内心活动、冲突、情绪克制/爆发、场景收束。评估抽象规律与节奏，不用长段原文逐字匹配。

### 6.2 HTML 模块

- [ ] 功能可配置启用/关闭。
- [ ] 关闭时输出不添加 HTML 提示词。
- [ ] 启用时只注入一次格式规范，不重复堆叠。
- [ ] 色板、字号与 CSS 属性使用允许列表；配置非法值会在 `config-check` 中报错。
- [ ] JSON 转义及 Character Card V2 结构校验仍通过。
- [ ] 不引入 JavaScript 执行或外部资源。
- [ ] HTML 样例覆盖单属性、多个允许属性、标签闭合、普通文本和非法属性。
- [ ] 在 Tavo 中实际测试颜色/字号/斜体显示；未测试的客户端行为如实标注。
- [ ] 不因 HTML 关闭而影响作者风格模块，反之亦然。

### 6.3 回归测试

- [ ] 现有所有离线测试继续通过。
- [ ] 默认导出、严格章节导出、内嵌/独立世界书一致性测试继续通过。
- [ ] 密钥扫描、原文只读、旧 run 不覆盖等既有安全约束继续通过。
- [ ] `README.md`、`docs/ARCHITECTURE.md`、`docs/IMPLEMENTATION_PLAN.md`、配置示例和用户手册同步更新。
- [ ] 报告明确区分：单元测试通过、静态 JSON 验证、Tavo 实际导入、真实对话行为验证。

## 7. 分阶段执行顺序

### Phase 0 — 仓库基线与方案

- 检查当前分支、文件、测试和提示词拼装逻辑。
- 调研 Nuwa 当前版本的输出结构与运行方式。
- 创建 `docs/PLAN.md`，确认模块接口和拟修改文件。
- 不新增运行依赖，不调用真实 API。

验收：有可执行实施计划；无现有功能被删除；Nuwa 的原始输出与目标 literary profile 的映射有文档。

### Phase 1 — 风格档案 schema 与 Nuwa 导入

- 定义/实现版本化 `StyleProfile` schema。
- 导入 Nuwa 完整输出，并保存来源和原始产物。
- 生成规范化 Markdown/JSON 风格档案及审计报告。
- 支持资料不足、不同来源冲突和风格证据不确定的情况。

验收：可以使用本地 fixture 离线测试，不需要 API；任何提取结果都不冒充 Nuwa 原始结果。

### Phase 2 — 运行时风格编译与酒馆导出集成

- 编译短版 `runtime_style_prompt.md`，支持 token 预算和编译 prompt 版本。
- 生成分组 `style_worldbook_entries.json`。
- 扩展现有导出器：可选把短版规范添加到 Description，把整理后的完整风格条目添加到内嵌/独立世界书。
- 无风格配置时保持旧行为；严格章节导出时审查风格条目可能包含的剧情事实。

验收：短版预算、Worldbook 一致性、canon 隔离和缓存失效测试通过。

### Phase 3 — 受控 HTML 规则与校验

- 新增独立 HTML 规则模板与配置 schema。
- 将规则可选注入角色卡；只允许 `font-size`、`color`、`font-style` 三类属性与有限色板。
- 新增静态 HTML fixture 验证与非法配置测试。
- 不实现 MVU/EJS/JavaScript/动态 HTML。

验收：开启/关闭互不影响，输出合法 JSON，越权属性被测试检测，Tavo 人工检查清单已更新。

### Phase 4 — 文档、实际模型评估与 Tavo 实测

- 更新 README 的功能列表和“非目标”，明确 HTML 已作为可选增强支持，MVU/EJS 仍未实现。
- 更新 `ARCHITECTURE.md`、`IMPLEMENTATION_PLAN.md`、`config.example.yaml`、`TAVO_IMPORT_CHECKLIST.md`。
- 运行完整离线测试，不花免费 API 额度。
- 用小型用户有权使用的样本文本跑风格编译和导出；在 Tavo 中验证渲染效果。
- 记录 Token 用量（可获取时）、输出风格检查结果、缺陷和后续建议。

验收：所有报告都有明确的运行日期、命令和状态；未实测的行为不标为已通过。

## 8. 建议的文件变化清单

实际命名以当前仓库结构为准。Agent 必须先检查后决定是否沿用/合并既有文件，禁止机械照抄列表新建重复模块。

可能新增：

- `docs/AUTHOR_STYLE_PIPELINE.md`：Nuwa 完整蒸馏与文学编译工作流。
- `docs/HTML_RENDERING.md`：允许格式、配置、限制和 Tavo 实测清单。
- `prompts/author_style_compile.md`：将 Nuwa 完整材料整理为文学风格档案的提示词。
- `prompts/runtime_style_template.md`：精简运行时风格规范模板。
- `prompts/html_rendering_rules.md`：受控 HTML 输出规范。
- `src/.../style_profile.py` 或同等模块：风格档案 schema/解析器。
- `src/.../style_compiler.py` 或同等模块：运行时精简与风格世界书条目整理。
- `src/.../html_policy.py` 或同等模块：配置校验与静态样例检查；不要宣称它能过滤 Tavo 运行时的真实模型输出。
- `tests/fixtures/style_profile/`、`tests/fixtures/html/`：完全合成的测试数据。

可能修改：

- CLI 命令注册与帮助信息。
- 现有 config schema、`config/config.example.yaml`。
- Character Card V2 serializer 与 Worldbook serializer。
- 导出报告/audit。
- `README.md`、`docs/ARCHITECTURE.md`、`docs/IMPLEMENTATION_PLAN.md`、`docs/TAVO_IMPORT_CHECKLIST.md`。
- `docs/THIRD_PARTY_NOTICES.md`（若项目开始分发 Nuwa 文件或代码）。

## 9. 第三方许可证和来源处理

Nuwa 仓库声明 MIT 许可证。可以按照许可证使用、修改和整合，但若复制/分发其代码或文件，应保留原有版权与许可证声明。不要把“可以修改”误解为无需保留 MIT notice。

建议第一版只要求用户在外部 Agent 环境运行 Nuwa，再导入其生成的产物；不将 Nuwa 全部源码复制进本仓库。若未来决定 vendoring Nuwa Skill，应将原 LICENSE 与 THIRD_PARTY_NOTICES 一并保留，并说明修改范围。

作者风格研究优先使用用户提供或有权处理的小说文件以及可合法访问的公开材料。保留必要来源清单，但不要把完整小说文本、长段原文、API 密钥或敏感个人资料写入公开测试文件和日志。

## 10. 完成后的交付报告要求

Agent 完成每个 Phase 后必须报告：

1. 实际变更文件及目的。
2. 实现的 CLI/config 接口和示例。
3. 运行的测试命令与真实结果。
4. 运行时风格预算、世界书条目数与导出差异。
5. Tavo 实测做了什么、未做什么。
6. 当前限制与下一阶段建议。

不得以“提示词要求模型遵守”为由声称 HTML 白名单获得硬性运行时保证；也不得以风格规则抽取成功为由声称已经保证与任何作者完全一致。

---

## 参考资料

- Novel-to-Tavern 当前项目：<https://github.com/Kylin-Guo/novel-to-tavern>
- 当前 README：<https://raw.githubusercontent.com/Kylin-Guo/novel-to-tavern/master/README.md>
- 当前目标架构：<https://raw.githubusercontent.com/Kylin-Guo/novel-to-tavern/master/docs/ARCHITECTURE.md>
- 当前实施路线图：<https://raw.githubusercontent.com/Kylin-Guo/novel-to-tavern/master/docs/IMPLEMENTATION_PLAN.md>
- Nuwa Skill：<https://github.com/alchaincyf/nuwa-skill>
- Nuwa 当前 Skill 指令：<https://raw.githubusercontent.com/alchaincyf/nuwa-skill/main/SKILL.md>
- Nuwa LICENSE：<https://raw.githubusercontent.com/alchaincyf/nuwa-skill/main/LICENSE>
- Worldbook Skill 的 HTML/MVU/EJS 功能说明（作为格式设计参考，而非本项目依赖）：<https://github.com/echo-xianyu/worldbook-skill>
