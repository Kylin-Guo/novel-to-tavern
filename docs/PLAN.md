# 本阶段实施计划（Phase 0：格式与仓库基线）

状态：待用户确认
创建日期：2026-10-16
上游依据：`tasks/001-phase0.md`、`docs/IMPLEMENTATION_PLAN.md` Phase 0

---

## 1. 阶段与目标

- 阶段：**Phase 0 — 格式与仓库基线**
- 目标：建立一个**离线可测**的 Python CLI 骨架，并把「SillyTavern / Tavo 目标 JSON 格式」从**可验证来源**固化成 docs 与 fixture，使后续阶段可以只做数据、不再猜字段。
- 不在本阶段范围内：
  - 不调用任何 LLM / API（不装 requests、不写 client）
  - 不解析小说原文（Phase 1）
  - 不做事实提取、实体归一、时间线（Phase 2–4）
  - 不做完整导出流水线（Phase 5）
  - 不引入数据库、向量库、Web UI、消息队列
  - 不实现 MVU / EJS / HTML/CSS 装饰
  - 不生成 `.png` 角色卡（Phase 0 只产出 JSON；PNG 打包属于 Phase 5/6 讨论项）

### 仓库现状（已核查，2026-10-16）

| 项目 | 现状 |
|---|---|
| 仓库性质 | **不是 git 仓库**（`git rev-parse` 失败），只有规格文档，无任何代码 |
| 已有文件 | `AGENTS.md`、`CLAUDE.md`、`README.md`、`LICENSE_POLICY.md`、`.env.example`、`.gitignore`、`config/config.example.yaml`、`docs/*.md`（7 篇）、`tasks/001-phase0.md` |
| 空目录 | `docs/`（无 PLAN.md）、`schemas/`、`examples/` 均为空 |
| Python | 3.12.3（`/usr/bin/python3`），`venv`/`ensurepip` 可用，pip 24.0 可用 |
| 已装依赖 | `pydantic 2.13.4`、`PyYAML 6.0.1` 全局已装；`pytest` **未装**（pip 网络可达，已验证可下载 pytest 9.1.1） |
| 路径说明 | `REPO_ROOT` 与 `REPO_ROOT` 是**同一 inode**（同一目录的两个挂载路径），任一路径写入等价 |
| 外部参照 | 本机已有部署：`SILLYTAVERN_DEPLOY/`，含 4 张**已成功导入生产酒馆**的角色卡 JSON |

### 关键发现：项目已存在「已知可用」的格式基准

`sillytavern-deployment/character-cards/` 下有 4 张用户自建、已导入 `sillytavern.example.invalid`（namespace `sillytavern`，PVC `sillytavern-data`）的卡，全部是 `spec: chara_card_v2` / `spec_version: 2.0`，且内嵌 `character_book`。**这 4 个文件是比任何社区文档都可靠的本地基准**，Phase 0 将把它们作为交叉验证对象（只读，不复制进本仓库）。

---

## 2. 上游借鉴与明确不复制

### worldbook-skill（CC BY-NC-SA 4.0）

**借鉴（方法与流程思想，用本项目自己的语言重新实现）：**

1. 原创/二创分流：已有小说走证据驱动提取，不按原创设定随意补写。
2. 「先采集 → 再建模 → 最后条目化」三段式，不一步到位。
3. 章节范围与原文依据：记录章节索引、人物首/再次出场、关键事件位置。
4. 多维人物档案：身份/外貌/行为证据/关系/能力/目标/关键事件/出场章节分开。
5. 世界书触发设计：常驻核心规则与按需触发条目分离，考虑关键词、secondary keys、位置、优先级、递归与预算。
6. 生成与校验分离：模型产出结构化内容，最终 JSON 由代码序列化；生成后校验字段、position、递归、条目数。

**明确不复制：**

1. 不照搬「description 必须留空」的铁律 —— 本项目主卡需要少量高优先级世界运行规则。
2. 不默认启用 MVU / EJS / HTML / CSS。
3. 不照搬与忠实度无关的写作禁词表。
4. 不把固定 `position` / `insertion_order` / 递归值当作万能常量（本项目已实证：这些值取决于目标客户端实际实现）。
5. **不复制其 SKILL.md、references/*.md 正文或 Python 源码**（CC BY-NC-SA 4.0 + 作者额外非商业限制）。若未来确需改编可版权表达，先复核许可证并保留署名 / 非商业 / 相同方式共享。本项目当前不使用其任何代码，因此 `THIRD_PARTY_NOTICES.md` 无需新增归属声明。

### st_book（MIT）

**借鉴：**

1. 分阶段 CLI（split / extract / merge / filter / create），每段可单独重跑。
2. 配置驱动：API、模型、分块大小、并发、重试、输出路径全部可配。
3. 缓存 / 中间产物 / 恢复能力：相同输入不重复请求，单次失败不从头再来。
4. 两阶段生成：先原子资料，再综合成高层设定。
5. 模块化边界：切块器 / 提取器 / 合并器 / 筛选器 / 世界书生成器 / 导出器分离。

**明确不复制 / 必须修正：**

1. **不照搬 `character_filter.py` 按 JSON 文件体积排序保留前 N 个** —— 用文件大小代替人物重要性是错的。本项目默认**保留全部人物**并打 `importance` / `evidence_count` / `coverage` 标签，只有用户显式设上限才裁剪，且裁剪必须记录。
2. **不做默认清空工作目录的 `auto` 模式** —— 每次 run 独立目录，清理必须显式、可确认、可恢复。
3. 角色合并不靠 LLM 一次性拍板：必须 `aliases` + 证据 + 置信度 + 人工复核队列，不确定就不合并。
4. 不只输出角色概要：必须保存事件时间线、关系变化、秘密揭露时间、角色知识边界。
5. 不靠提示词「生成三层架构」就相信输出完整：先有中间 schema 与字段校验。
6. **不直接把每个角色导出成独立卡** —— 首版是一张多角色世界模拟器卡 + 世界书。
7. 不复制其源码（虽然 MIT 允许，但本项目优先自行实现；若日后复用，必须随分发保留 MIT 版权与许可声明，并记录复用文件、修改与来源）。

### 一句话结论

提取的是**方法**：worldbook-skill 给信息组织与质量原则，st_book 给可恢复流水线思路。数据模型、提示词、序列化代码**全部由本项目重新设计**。这不是把两个仓库拼起来。

---

## 3. 格式验证方案（如何避免猜字段）

### 核心原则

> 任何进入 serializer 的字段，必须能指向三选一的证据：**①目标客户端源码**、**②已实测成功的本地产物**、**③社区规范文档**。三者冲突时，以 ① > ② > ③ 为准。找不到证据的字段一律不写。

### 已完成的验证（2026-10-16 实际拉取，非记忆）

验证目标锁定 **SillyTavern 1.19.0**（GitHub release `1.19.0`，发布于 2026-09-14），因为用户生产部署 `sillytavern.example.invalid` 正是 1.19（St 迁移记录 2026-09-22），且 `character-cards/README.md` 明确写「ST 1.19 的目录扫描只认 `.png`（`src/endpoints/characters.js` 过滤 `extname === '.png'`）」。

已下载并逐行核对（源码文件，非文档转述）：

| 证据文件 | 结论 |
|---|---|
| `public/scripts/char-data.js` | 权威 V2 typedef：`v2CharData`、`v2WorldInfoBook`、`v2DataWorldInfoEntry`、`v2DataWorldInfoEntryExtensionInfos` |
| `public/scripts/world-info.js:5617` `convertCharacterBook()` | 内嵌 `character_book` → 运行时 world info 的**唯一映射代码** |
| `public/scripts/world-info.js:855` `world_info_position` | `before:0, after:1, ANTop:2, ANBottom:3, atDepth:4, EMTop:5, EMBottom:6, outlet:7` |
| `public/scripts/world-info.js:4127` `newWorldInfoEntryDefinition` | 独立世界书条目的 **42 个字段**及其 type / default |
| `src/endpoints/worldinfo.js` | 独立世界书文件格式：必须含 `entries` 键，否则报 `File must contain a world info entries list` |
| `src/character-card-parser.js` | PNG tEXt chunk 写 `chara`（V2）；V3 存在（`chara_card_v3` / `3.0`）但导出时**只写 `chara`**，注释明说 `ccv3 is not supported and removed not to create a mismatch` |
| `character-card-spec-v2` 规范（malfoyslastname） | V2 权威类型定义：`spec`/`spec_version`/`data` 必填，`character_book.entries` 是**数组**，`position` 为 `'before_char' \| 'after_char'`。**注意：该规范只有 TS 类型，无任何 JSON 示例** |
| `character-card-spec-v3` 规范（kwaroran） | V3 为 V2 超集；新增 `use_regex`、`assets`、`nickname`、`group_only_greetings` 等 |
| Tavo 官方文档 https://docs.tavoai.dev/ | **无字段级信息**，只写「可导入 SillyTavern 卡」 |

### 已确证的关键字段事实（这些直接决定 Phase 0 的 fixture 设计）

1. **内嵌 `character_book` 条目的 `position` 是字符串**，`convertCharacterBook` 里写的是
   `entry.position === 'before_char' ? world_info_position.before : world_info_position.after`。
   → 写成数字 `0` 会**静默变成** `after(1)`。用户现有 4 张卡写的是数字 `1`，恰好等于 `after_char`，所以「碰巧正确」。
   → **本项目 serializer 必须对内嵌条目输出字符串 `"before_char"` / `"after_char"`；对独立世界书输出数字 0–7。两套枚举必须分开建模。**
2. **条目标题字段是 `comment`，不是 `name`**：映射为 `comment: entry.comment || ''`、`addMemo: !!entry.comment`；`name` 在 `convertCharacterBook` 中**完全未被读取**。用户现有卡用 `name`（如 `检定规则`）作为条目标题 → 在 ST 里不可见。
3. **条目 ID 字段是 `id`，不是 `uid`**：`if (entry.id === undefined) entry.id = index;` 然后 `uid: entry.id`。用户现有卡写 `uid` → ST 忽略并用数组下标兜底。
4. **`priority` 未被读取**：`convertCharacterBook` 无 `priority` 映射，排序由 `order`（= `insertion_order`）+ `position` 决定。用户现有卡的 `priority: 10` 是无效字段。
5. **`case_sensitive` / `scan_depth` / `probability` / `depth` / `group` 等只从 `extensions.*` 读取**（如 `caseSensitive: entry.extensions?.case_sensitive ?? null`）。顶层同名字段被忽略。
6. **内嵌 `character_book` 不会自动生效**：`importEmbeddedWorldInfo()` 需要用户确认后，才把 `character_book` 转成一本独立世界书保存并按名字挂到角色上。用户 README 中「导入后随卡自动生效」需在 Tavo 侧单独确认。
7. **`enabled` 缺失 = 条目被禁用**：`disable: !entry.enabled`。缺 `enabled` 时 `!undefined === true` → `disable: true` → **条目静默失效**。serializer 必须**无条件**输出 `enabled`。
8. **`use_regex` 不属于 V2 规范**（是 V3 新增；ST 导入时仍会识别）。本项目在 V2 产物中**不写** `use_regex`。
9. **V2 规范原文只有 TS 类型定义，没有任何 JSON 示例** —— 所以「照抄官网示例」这条路不存在，必须以 ST 源码为准。
10. **`selective` 的默认值在两侧不一致**：ST 独立世界书模板 `selective: true`，而 `convertCharacterBook` 是 `entry.selective || false`。跨两种格式搬运时不能沿用默认值，必须显式写。
11. **排序方向存在文档冲突（未解决）**：V2 规范称 `insertion_order`「值越小越靠前」，ST 独立世界书文档称 `order`「值越大越靠近上下文末尾」，而 `convertCharacterBook` 是**原样拷贝不取反**。两种说法指向同一字段却方向相反 → 列为 Phase 0 待实证项，实证前不写死「越大越靠前」这类假设。

### 其余验证手段（Phase 0 内执行）

1. **来源与日期落盘**：写入 `docs/FORMAT_COMPATIBILITY.md`，每条字段标注来源 URL + 拉取日期 + ST commit/tag，并显式列出**未能验证**的项。
2. **往返测试**：把 fixture 卡导入用户运行中的 ST 1.19 实例（`POST /api/characters/import`，字段名 `avatar` + `file_type=json`，需先 `GET /csrf-token`），再导出回来 diff。**此项为可选强化验证**，需要用户同意后接触生产实例；不做也不阻塞 Phase 0。
3. **他人产物交叉验证**：与本机 4 张已成功导入的卡逐字段对照，任何差异都必须在 FORMAT_COMPATIBILITY.md 中解释（例如「他们写了 `uid`，ST 忽略」）。
4. **社区规范对照**：`character-card-spec-v2` 规范与 ST 官方 docs 仅作 ③ 级佐证，不作唯一依据。
5. **未知即不写**：任何无法归入以上证据的字段不写入产物；确需自定义的放进 `extensions` 并注明来源。

### Tavo 侧核查结果（2026-10-16）

- Tavo 是手机端 AI 角色扮演客户端（包名 `app.bitbear.tav`，Google Play / App Store 均有），官方文档站：**https://docs.tavoai.dev/**（有 `/en/`、`/cn/`）。
- **官方文档只说了「可导入 SillyTavern 的卡，支持各大角色卡站点」，没有任何字段级说明** —— 未记载 V1/V2/V3、PNG/JSON/CHARX、`character_book`、世界书（lorebook）的任何处理细节。部分子页面 404 或超时。
- 应用商店页面**宣称**支持 Spec V1/V2/V3、PNG/JSON/CHARX、与 SillyTavern / JanitorAI / Pygmalion / RisuRealm / Chub 等互通 —— 但这是**商店营销文案，官方文档未确认**。
- **结论：Tavo 对 `character_book` / 世界书的具体行为完全无法离线验证，不得做任何假设。** 唯一可靠路径是把 ST 1.19 已验证过的产物，在 Tavo 里**实际导入并记录观察**（Phase 6），观察结果单独成文，不与自动验证混写。

### 未决问题（Phase 0 内需定论）

- V2（`chara_card_v2`/`2.0`）vs V3（`chara_card_v3`/`3.0`）：**默认仍用 V2**，与用户现有 4 张可用卡一致，且 V2 是 V3 的子集、向前兼容面更宽。V3 详情（`ccv3` tEXt chunk 优先级高于 `chara`；独立世界书在 V3 下包成 `{spec:'lorebook_v3', data: Lorebook}`；V3 条目新增 `use_regex`，`id` 可为字符串）记入 FORMAT_COMPATIBILITY.md 备查，**Phase 0 不实现 V3**。
- 独立世界书顶层结构：ST 落盘为 `{ entries: {...}, ... }`（`saveWorldInfo` 直写整个 data 对象）。本项目是否额外附带 `name` / `originalData` 需在 FORMAT_COMPATIBILITY.md 定论。
- `insertion_order` / `order` 方向语义（见上文事实 11）：Phase 0 记录冲突，Phase 6 实测确定，不预先假设。
- Tavo 是否接受 `.json` 直接导入、是否读内嵌 `character_book`：**只能实测**。

---

## 4. 修改计划（Phase 0 拟新增文件）

全部为**新增**，不修改任何现有文档内容（除 `README.md` 追加状态段落）。

### 4.1 依赖决策

| 依赖 | 用途 | 必要性说明 |
|---|---|---|
| `pydantic >= 2` | 有版本的 schema 校验（AGENTS 要求） | 已全局存在；比 dataclasses+jsonschema 更少代码、错误信息更好 |
| `PyYAML >= 6` | 读 `config.yaml` | 已全局存在；配置文件已是 YAML |
| `pytest >= 8`（dev） | 离线测试 | 必需；已验证可下载 |

**明确不引入**：`click`/`typer`（用 stdlib `argparse`）、`python-dotenv`（自写 ~25 行 stdlib 解析器）、`requests`/`httpx`（Phase 0 无网络调用）、`jsonschema`（pydantic 已覆盖）、任何数据库/向量库。

### 4.2 文件清单

| 文件 | 计划内容 | 理由 |
|---|---|---|
| `pyproject.toml` | 项目元数据、src 布局、依赖、`[project.scripts] n2t`、pytest 配置 | Phase 0 任务 1 |
| `src/novel_to_tavern/__init__.py` | `__version__` | 包入口 |
| `src/novel_to_tavern/__main__.py` | 支持 `python -m novel_to_tavern` | 验收项「`--help` 可运行」 |
| `src/novel_to_tavern/cli.py` | `argparse` 子命令：`version` / `config-check` / `doctor` | 阶段边界入口；后续阶段在此挂 `import`/`extract`/… |
| `src/novel_to_tavern/config.py` | pydantic 模型 + YAML 加载 + 环境变量**名**解析（不解析值） | 配置驱动；密钥只从 env 读 |
| `src/novel_to_tavern/env.py` | 标准库 `.env` 读取（仅 `KEY=VALUE`，不进 os.environ 之外的日志） | 避免引入 python-dotenv |
| `src/novel_to_tavern/secrets.py` | 密钥登记与脱敏（`redact()`） | 日志与导出双重防线 |
| `src/novel_to_tavern/logging_setup.py` | logging 配置 + `RedactionFilter` | AGENTS：不得记录密钥 |
| `src/novel_to_tavern/paths.py` | `runs/<run_id>/` 布局、run id 生成、拒绝覆盖 | AGENTS：非破坏式运行 |
| `src/novel_to_tavern/tavern/__init__.py` | 格式层入口 | 业务与格式分离 |
| `src/novel_to_tavern/tavern/spec_v2.py` | `CardV2` / `CharData` / `CharacterBook` / `CharacterBookEntry` pydantic 模型，**只含已确证字段** | AGENTS：有版本的 schema |
| `src/novel_to_tavern/tavern/wi_standalone.py` | 独立世界书模型（依 `newWorldInfoEntryDefinition` 的 42 字段选取子集） | 独立导出格式 |
| `src/novel_to_tavern/tavern/position.py` | `CharBookPosition`(str) 与 `WiPosition`(int 0–7) **两个独立枚举** + 显式转换 | 直接对应已确证的 position 分歧 |
| `src/novel_to_tavern/tavern/serializer.py` | 内部模型 → 目标 JSON 的**唯一映射表** | 禁止 LLM 手写最终 JSON |
| `src/novel_to_tavern/tavern/validator.py` | 结构校验 + 警告收集（唯一 id、position 类型、keys 非空、常驻条目数） | 质量门禁 E |
| `docs/FORMAT_COMPATIBILITY.md` | 来源 URL、拉取日期、采用字段表、未验证项、V2/V3 定论 | Phase 0 核心交付 |
| `examples/fixtures/minimal_card_v2.json` | 最小合法角色卡 + 内嵌 `character_book`（**自创内容**） | 许可证要求：不得用有版权原文 |
| `examples/fixtures/minimal_worldbook_standalone.json` | 最小独立世界书（含 `entries`） | 同上 |
| `tests/fixtures/` | 测试用 JSON（含故意畸形的反例） | 离线测试 |
| `tests/test_cli.py` | `--help` / `version` / `config-check` | 验收项 |
| `tests/test_config.py` | YAML 解析、默认值、env 名称间接寻址、缺 env 报错友好 | — |
| `tests/test_secrets.py` | 密钥不出现在日志与导出 JSON | 质量门禁 F |
| `tests/test_format_roundtrip.py` | 内部模型 → JSON → 解析 → 模型，等值；内嵌/独立条目语义一致性 | 质量门禁 E |
| `tests/test_field_mapping.py` | 黄金断言：`keys`→`key`、`secondary_keys`→`keysecondary`、`insertion_order`→`order`、`enabled`→`disable`（取反）、`position` 字符串 vs 数字、标题用 `comment`、**`enabled` 必须显式存在**（缺失会被 ST 判为禁用）、V2 产物**不含** `use_regex` | 防止回归到「猜字段」 |
| `tests/test_run_isolation.py` | run 目录不复用、有产物时拒绝覆盖 | 质量门禁 F |
| `tests/test_gitignore.py` | `.env` 被忽略、`.env.example` 不被忽略 | 验收项 |
| `README.md`（追加） | 当前状态 → Phase 0 完成范围 + 手工导入 Tavo 的步骤 | AGENTS：每阶段更新状态 |

### 4.3 内部模型与目标字段的分层（呼应 DATA_MODEL.md §5）

```
WorldbookEntry（内部，本项目自有字段）
   ├─ entry_id / title / category / content_canonical / content_runtime
   ├─ keys / secondary_keys / trigger_strategy / always_on / priority
   ├─ valid_from_chapter / valid_to_chapter / source_refs / review_status
   ↓ serializer（唯一映射点，Phase 0 先建骨架 + 2 条真实映射）
CharacterBookEntry（目标：字符串 position，comment 作标题，id 作 uid 源）
WiStandaloneEntry （目标：42 字段子集，数字 position 0–7）
```

**明确不做**：Phase 0 不定义完整世界 Bible 条目体系（属 Phase 4），只在 serializer 中建立映射骨架与 2–3 个代表性条目的真实转换 + 测试。

---

## 5. 风险和假设

1. **`position` 类型分歧（最高风险，已确证存在）**
   内嵌条目必须用字符串 `"before_char"`/`"after_char"`，独立世界书必须用数字 0–7；写错不报错、只静默错位。
   *缓解*：`position.py` 用两个独立枚举 + `test_field_mapping.py` 黄金断言 + FORMAT_COMPATIBILITY.md 显式记录。
2. **`enabled` 缺失会静默禁用整条世界书条目（与风险 1 同级）**
   `disable: !entry.enabled` —— 少写一个字段，条目就永久不触发，且 JSON 完全合法、不报任何错。
   *缓解*：pydantic 模型把 `enabled` 设为**必填无默认**；`test_field_mapping.py` 断言其存在；validator 输出条目总数与「启用数」。
3. **目标客户端版本漂移**
   部署用的是 `ghcr-io/sillytavern/sillytavern:latest`，`:latest` 会漂移；验证锚点是 ST **1.19.0**。
   *缓解*：FORMAT_COMPATIBILITY.md 记录验证所用的确切 tag 与核查日期；换版本须重跑格式测试。
4. **Tavo 行为未知且无法离线验证**
   官方文档 `docs.tavoai.dev` **没有任何字段级说明**，只有「可导入 SillyTavern 卡」一句；商店页面的 V1/V2/V3 + CHARX 说法属未确认的营销文案。**Phase 0 不得声称 Tavo 导入成功。**
   *缓解*：产出 `docs/TAVO_IMPORT_CHECKLIST.md`（人工步骤清单），实测结果单独记录，不与自动验证混写。
5. **仓库不是 git 仓库**
   用户要求「每个阶段独立提交边界」，但当前 `git rev-parse` 失败，且全局 CLAUDE.md 规定走 GitLab（master + MR）流程。
   *缓解*：**需用户决策**：是否 `git init`？是否配置远程（`gitlab.example.invalid`，SSH 端口 10086，`~/.ssh/id_ed25519`）？未确认前不执行任何 git 操作。
6. **许可证边界**
   fixture 必须自创，不得使用有版权的原文；不复制上游 Skill 正文/代码。
   *缓解*：fixture 用自写的 3 章玩具设定；`THIRD_PARTY_NOTICES.md` 当前无需改动（未复用任何上游代码）。
7. **排序方向语义冲突**
   规范与 ST 文档对 `insertion_order`/`order` 方向描述相反，且转换代码不取反。
   *缓解*：Phase 0 只记录冲突、不预设方向；条目顺序先用 ST 模板默认值（`order: 100` 起），Phase 6 实测后定论。
8. **假设：Python 3.12 + venv 可用、pip 网络可达** —— 已验证（pytest 9.1.1 下载成功）。

---

## 6. 测试

- [ ] 单元测试（离线，`python -m pytest -q`，默认不访问网络、不花 API 额度）：
      上述 `tests/` 全部 8 个文件
- [ ] 集成测试：Phase 0 **无**（不做 API、不做 ST 往返）。往返验证为可选强化项，需用户另行同意。
- [ ] 人工检查：Tavo 手工导入清单（Phase 6 才正式执行，Phase 0 只产出清单）
- [ ] 静态检查：`python -m compileall` / `python -m novel_to_tavern --help` 退出码 0

## 7. 验收：自动 vs 人工

### 可自动完成（Phase 0 内必须全绿）

- [ ] `n2t --help` / `python -m novel_to_tavern --help` 退出码 0
- [ ] `config-check` 能加载 `config/config.example.yaml` 并通过 pydantic 校验
- [ ] 缺 `NOVEL_TAVERN_API_KEY` 时给出可读错误，而不是 traceback
- [ ] fixture 是严格合法 JSON（无注释、尾逗号、未转义字符）
- [ ] 内部模型 → JSON → 解析 → 模型 往返等值
- [ ] 内嵌 `character_book` 与独立世界书条目数一致、语义字段可互相映射
- [ ] 字段映射黄金断言全绿（`key`/`keysecondary`/`order`/`disable`/position 类型/`comment`）
- [ ] `uid`/`id` 唯一性、`position` 类型、`keys` 非空 校验通过
- [ ] 导出 JSON 中**不含**任何 API key
- [ ] 日志文件中**不含**任何 API key
- [ ] `.env` 命中 `.gitignore`，`.env.example` 不被忽略
- [ ] 已存在产物的 run 目录被拒绝覆盖
- [ ] 全程零网络请求（可用禁用网络的测试或 mock 断言）

### 必须在 Tavo 手工实测（Phase 0 只写清单，不声称通过）

- [ ] 导出的 JSON 能被 Tavo 接受并出现在角色列表
- [ ] 内嵌世界书在 Tavo 中是否**自动生效**，还是需要手动「导入卡内世界书」（ST 1.19 需手动确认，Tavo 行为未知）
- [ ] 角色/地点条目的关键词触发**真的命中**（而非只是 JSON 合法）
- [ ] 常驻核心规则在无任何关键词命中时**仍然加载**
- [ ] 触发词不会让大量无关条目同时命中
- [ ] 实际 token 占用 / 上下文预算可接受
- [ ] 起始章节之后的信息**没有泄漏**（需 Phase 4 产物，Phase 0 只留检查位）
- [ ] 独立世界书能否单独导入、条目是否与内嵌版一致

---

## 8. 交付与提交边界

Phase 0 拆成 **3 个独立提交**（待 git 决策后执行）：

1. `chore: 建立 Python 项目骨架、CLI、配置与日志`
2. `docs: 记录 SillyTavern 1.19 格式核查结果与字段映射依据`
3. `test: 加入 V2 卡与独立世界书 fixture、往返与字段映射测试`

每步完成后运行 `python -m pytest -q` 并更新本节状态。

---

## 9. 变更记录

- 2026-10-16：建立本计划，完成仓库现状核查与 SillyTavern 1.19.0 源码级格式验证。
- 2026-10-16：补入上游规范（character-card-spec-v2 / v3）与 Tavo 官方文档核查结果；新增 `enabled` 缺失即禁用、`use_regex` 非 V2 字段、排序方向文档冲突三项发现。
