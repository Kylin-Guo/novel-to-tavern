# 本阶段实施计划

当前阶段：**Phase 6 — 质量评估与 Tavo 实测**（Phase 2–5 均已实施；
另加了原计划没有的 `verify` 语义支持校验阶段，见 `docs/IMPLEMENTATION_PLAN.md` Phase 4.5）
状态：Phase 2–5 已实施并通过测试；Phase 6 的运行时部分**待人工实测**
更新日期：2026-10-17
上游依据：`docs/IMPLEMENTATION_PLAN.md` Phase 5

> 每个阶段完成后更新本文；已完成的阶段摘要见 §7 历史。

> ⚠️ **本文是分阶段的施工记录，不是验收状态的权威来源。**
> 文中各阶段的「尚未完成」只对**写下它的那一刻**成立。
> 当前的真实验收状态（哪些验证过、哪些没有）一律以下列文档为准：
> [`README.md`](../README.md) 的「验证等级」表、
> [`docs/RUN_REPORT.md`](RUN_REPORT.md) §1、
> [`docs/TAVO_IMPORT_CHECKLIST.md`](TAVO_IMPORT_CHECKLIST.md)。
>
> 具体到今天：Tavo **已实测导入成功**（不是「未实测」），
> 但**运行时行为仍全部未验证**（触发、常驻注入、剧透行为、token 占用）。
>
> 逐项复核结论见 [`docs/REVIEW_RECHECK.md`](REVIEW_RECHECK.md)；
> 配置键与消费点的对应关系见 [`docs/CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md)。

---

## Phase 2 — 分块原子事实提取

### 目标

对 Phase 1 的每个分块产出**可核查**的原子事实、实体提及、事件与关系。

### 不在本阶段范围内

- 不做实体归一（Phase 3，本阶段只产出带名字的提及）
- 不做时间线（Phase 4，本阶段的事件只带所属章节）
- 不生成世界书（Phase 5）

### 设计

| 模块 | 职责 |
|---|---|
| `extract/evidence.py` | 引文定位：去掉空白后逐字检索，映射回**最紧**的行区间；超长/跨行过多/找不到一律拒绝 |
| `extract/schema.py` | `Raw*`（模型直接产出，只给引文）与 `*Record`（带行号与 source_refs）两层 |
| `extract/prompts.py` | 版本化提示词，**明确要求不要输出行号** |
| `extract/runner.py` | 缓存键含模型+提示词版本+输入 hash+温度；坏响应重试后进 `_errors/` 隔离；逐块落盘续跑 |
| `llm/client.py` | 只用标准库 urllib；429/5xx/超时可重试，4xx 不重试；日志只出现 endpoint 主机名 |
| `llm/provider.py` | `openai_compatible` 与 `file`（读预生成响应）两种引擎 |

`file` 引擎不是测试替身：没有可用凭据时它让整条管线仍能离线跑通，
产出的 run 会在报告里标注 `provider`，不冒充 API 调用结果。

### 测试

- 引文定位：精确、跨空白差异、跨行、最紧区间、编造引文被拒、超长被拒、窗口限制
- canon 资格：定位失败的 canon 事实降级 `needs_review` 并注明原因
- 隔离：坏 JSON 先重试、再隔离并抛错，**绝不写成成功**
- 缓存：同输入二次运行不再调用引擎；改动输入/模型/温度即失效
- 续跑：`--limit` / resume 跳过已完成块；缺预生成响应被报告而非吞掉
- HTTP：429 重试后成功、400 不重试、耗尽重试后报错、**错误信息不含密钥**
- 报告：记录 provider 与提示词版本，且不含原文

### 依赖

无新增。HTTP 走标准库 `urllib`，不引入 requests/httpx。

---

## Phase 3 — 实体消歧与角色档案

### 目标

把跨章节的实体提及聚成 canonical 实体，并汇总每个实体的档案。

### 自动合并只允许两种情况

1. **规范化后字面完全相同**（NFKC + 去标点 + casefold）；
2. **抽取结果里显式标注为彼此的别名**（原文有"又名/化名/称号"依据）。

其余——字面包含、编辑距离为 1——**一律进复核队列**，`decision="needs_review"`，
绝不自动合并。这是 AGENTS「绝不可仅因为名字相似就自动合并」的落点。

### 不丢实体

- 所有实体都会得到档案，**不按体量排序裁剪**。
- 只有泛称（少年/士兵/众人…）被排除——它们是角色名词而非专有实体，
  被排除的名单完整列在报告里，不是静默丢弃。
- 每个合并判定都记录 `candidate_names` / `match_signals` / `confidence` /
  `evidence_refs`，可追溯可回滚。

### 档案字段

`first_appearance_chapter`、`appearance_chapters`、`aliases`、`facts`、
`events`、`relations`、`evidence_count`、`importance`（按证据量归一化）。

### 测试

同名聚类、泛称排除、字面包含只提候选不合并、别名合并有记录、
档案聚合正确、importance 归一化、**每个非泛称名字都出现在某个实体里**、
产物文件齐全、抽取目录缺失/为空/无提及/JSON 非法时明确报错。

---

## Phase 4 — 世界观、时间线与知识边界

### 目标

把 canonical 数据整理成时间线、知识边界与世界书规划，并**自动检查未来信息泄漏**。

### 三条不让步的规则

1. **不编造绝对时间。** `occurred_at` 只在原文明确给出时才填；本项目实现里它**恒为 null**。
   原文里的「次日」「当晚」等只作为 `relative_time` 原样记录，不换算成日期。
2. **不假设"事件发生后所有人都知道"。** 知识来源只有两类推断，且显式记录依据：
   `present_at_event`（事件参与者）与 `subject_of_fact`（事实主语自身）。
3. **冲突只报告，不覆盖。** 同一主语同一谓词的多个取值进 `contradictions.json`，
   由人工判断是随时间变化还是原文矛盾。

### 泄漏检查

对两个起始点分别计算"起始章节之后才出现的内容"有多少：

- `start_at_beginning`（第 1 章）：这些就是**必须被屏蔽**的量；
- `start_at_end`（末章之后）：应为 0。

屏蔽靠条目的 `valid_from_chapter` 实现，**源数据不删除**（
`filter_for_start_chapter` 返回"可用/被屏蔽"两组）。

### 世界书规划

- 常驻条目（核心规则/世界概况/人物索引）与按需触发条目分开；
- **每个实体都会得到条目**，重要性只体现在 `priority`，不做裁剪；
- 实体条目的触发词包含**名字 + 全部别名/称号**，任一命中即生效
  （放进 `secondary_keys` 会让"只用称号提到角色"漏触发）；
- token 为粗估（CJK 约 1 字 1 token），报告里注明非分词器真实计数。

### 测试

时间线排序、绝对时间恒为空、相对时间原样记录、只有参与者知情、
非参与者不获得知识、needs_review 不进知识、两个起始点的泄漏量、
冲突报告、每个实体都有条目、别名全部可触发、
按起始章节屏蔽但源条目不删除、报告声明 token 为粗估。

---

## Phase 5 — 世界书与角色卡导出

### 目标

把世界书规划装配成可导入 Tavo 的产物，并保证「完整剧情在卡内」与
「用户自选起始点」两件事同时成立。

### 用户可选的两个起点（本次目标的核心要求）

`first_mes` 先让用户选起点（回复 1 或 2），并额外给出两条 `alternate_greetings`
直接进入对应场景：

1. **从故事的开头开始**（第 1 章之前）；
2. **从故事的最终结尾之后开始**（末章之后）。

另外允许用户直接说"从第 N 章开始"。起点信息写进开场白，模型才知道"现在是哪一刻"。

### 完整剧情在卡内

`剧情主线（逐章）` 条目包含全书每一章的走向，作**触发**条目
（键：剧情/主线/前情/结局/回忆…），并在核心规则里说明按章标注的用法。
常驻条目塞的是极简「剧情阶段骨架」，控制在十几行。

### 常驻条目恰好 3 个

核心规则（含骨架）、世界概况、人物索引 —— 与 `config.worldbook.max_always_on_entries`
一致，超限会被 validator 报出来。常驻条目 `position="before_char"`，其余 `"after_char"`。

### 导出即校验，不过就不写文件

`validate_card(strict)` + `validate_worldbook(strict)` + `validate_parity` +
密钥扫描，任一有 error 就抛 `ExportError`，**不产出半成品**。

### 产物

| 文件 | 说明 |
|---|---|
| `exports/world_simulator_v2.json` | 主卡，内嵌 character_book，含全部条目 |
| `exports/worldbook_standalone.json` | 独立世界书（全部条目） |
| `exports/worldbook_start_beginning.json` | 已屏蔽起始点之后内容的版本 |
| `exports/worldbook_start_after_ending.json` | 从结局之后开始的版本 |
| `exports/timeline.json` | 时间线 |
| `exports/export_manifest.json` | 导出清单（输入 hash、prompt 版本、校验结果） |
| `reports/audit.md` | 审计报告 |

### 测试

开场白含两个起点且互不混淆、可从任意章节开始、剧情条目覆盖每一章、
常驻恰好 3 个且位置正确、别名可触发、条目都有可读标题、
导出物结构校验与内嵌/独立一致性、起始点过滤使条目变少、
导出清单无凭据、审计报告声明 Tavo 未实测且 token 为粗估、
上游缺失或无章节摘要时拒绝导出。

---

## 0. 贯穿全流程的两条硬规则

这两条是「不得出现与原文剧情或人物行为不符」在代码层的落点，后续阶段都依赖它们：

1. **行号由代码算出，不接受模型自报。**
   抽取结果只给引文（`quote`），`evidence.locate_quote` 在原文里逐字检索后
   反推行号。引文找不到 → 条目降级为 `needs_review`，**不得当作 canon 使用**。
2. **声称是原著事实却没有可定位证据 → 不能进 canon。**
   `canon_fact` 但引文定位失败的条目，`review_status` 置为 `needs_review`
   并在 `review_note` 注明，后续阶段的条目正文只取 `accepted` 的 canon 事实。

---

## 1. 阶段目标

把小说原文变成可追溯、可续跑的**章节索引与分块**，为后续提取提供稳定坐标。

- 原文**只读**，产物全部写进 `runs/<run_id>/`。
- 章节、区段、分块都必须能**无损重组**回原文；校验失败即中止，不产出"看起来成功"的结果。
- 识别不确定时给明确 fallback，不假装识别准确。

### 不在本阶段范围内

- 不做事实提取、不做 LLM 调用（Phase 2）
- 不支持 DOCX/EPUB/PDF（后续增量）
- 不做向量检索、不做 Web UI

---

## 2. 目标输入

`天之炽/` 下 3 个 UTF-8 TXT：

| 文件 | 行数 | 字符 | 章节 |
|---|---|---|---|
| 天之炽Ⅰ：红龙的归来.txt | 3755 | 252,006 | 60 |
| 天之炽Ⅱ：女武神1.txt | 3822 | 210,089 | 45 |
| 天之炽Ⅱ：女武神2.txt | 4374 | 236,165 | 51 |
| **合计** | **11,951** | **698,260** | **156** |

原文的站点残留结构（**已在实现中显式建模，未静默删除**）：

```
第1章 楔子：莲花（1）      ← 站点导航标题（重复）
----------------------------------------   ← 分隔线
（空行）
未知                                        ← 站点作者位
第1章 楔子：莲花（1）      ← 真正的正文标题
正文……
```

即每个章标题在文件中出现 **2 次**。实测折叠率正好 2.0（120→60、90→45、102→51）。

---

## 3. 设计

### 3.1 区段模型（无损的基础）

原文被 `Region` 无缝铺满，三种 kind：

| kind | 含义 | 是否参与提取 |
|---|---|---|
| `front_matter` | 卷首版权/简介/书名 | 否 |
| `site_noise` | 被折叠的导航标题、分隔线、作者位 | 否 |
| `chapter` | 章节正文，从**真正的标题行**开始 | 是 |

不变式：按 `start_line` 排序后，区段必须从第 0 行连续覆盖到末行，无空隙无重叠。
`rebuild_text(lines, regions) == 原文` 是强制断言。

### 3.2 分块

- **不跨章节**：每个 chunk 完整落在单个章节的行范围内。
- **行对齐**：chunk 是 `[start_line, end_line)`，拼接即还原，不切开任何一行。
- 单行超过 `chunk_max_chars` 时**不切开**（切开就无法行对齐），该行独占一块并记入警告。
- manifest 只存位置与 `sha256`，**不存原文**。

### 3.3 标题检测

默认正则 `^第\s*([0-9零一二三四五六七八九十百千〇两]+)\s*([章节回])\s*(.*)$`，只匹配行首。

- 同一标题在 ≤8 行内出现两次 → 折叠，**保留后面那次**作为正文起点。
- 自定义正则：3 个捕获组按 `(编号, 级别, 标题)`；1 个捕获组则整组当标题，编号自动生成。
- `chapter_detection: regex|manual` 时匹配不足**直接报错**，不静默降级。
- `auto` 且标题数 < 2 → 转 fallback：按字符预算在行边界自动分段，理由写进报告。

### 3.4 续跑

- 每个来源处理完立刻落盘 `manifest.json` + `state.json`。
- 续跑时按 `source_id + sha256` 跳过已完成来源。
- **来源内容变了则拒绝续跑**：一个 run 是一次原文快照，只重跑其中一部分会让
  同一次 run 混入两种来源版本。报错并提示改用新 run_id。
- 续跑时会先清掉该来源的旧记录再重建，保证重复续跑不产生重复条目（幂等）。

---

## 4. 修改计划

| 文件 | 内容 |
|---|---|
| `src/novel_to_tavern/ingest/source.py` | 只读读取、sha256、换行风格检测、行切分、source_id 规整 |
| `src/novel_to_tavern/ingest/chapters.py` | 标题检测、重复标题折叠、区段铺满、fallback |
| `src/novel_to_tavern/ingest/chunker.py` | 章节内行对齐分块 |
| `src/novel_to_tavern/ingest/manifest.py` | v1 schema：来源/区段/章节/分块/状态 |
| `src/novel_to_tavern/ingest/pipeline.py` | 编排、落盘、续跑、无损性强制校验、报告 |
| `src/novel_to_tavern/cli.py` | 新增 `n2t ingest`（`--run-id` / `--no-resume` / `--source`） |
| `tests/fixtures/sample_novel.txt` | **自创**测试夹具（含重复标题结构） |
| `tests/test_ingest_source.py` | 读取、指纹、行切分无损 |
| `tests/test_ingest_chapters.py` | 折叠、区段铺满、fallback、自定义正则 |
| `tests/test_ingest_pipeline.py` | 端到端、分块不跨章、续跑、幂等、报告 |

### 依赖

无新增。仍然是 `pydantic` + `PyYAML`（+ dev `pytest`）。

---

## 5. 测试与验收

**自动（离线，`python -m pytest`）—— 149 项全通过：**

- [x] `"".join(lines) == text`：行切分无损
- [x] 区段无缝铺满 `[0, total_lines)`，无空隙无重叠
- [x] `rebuild_text(regions) == 原文`
- [x] 每章 `rebuild_chapter(chunks) == 章节原文`
- [x] 分块覆盖字符 + 未分块字符 == 原文总字符
- [x] chunk 不跨章节边界
- [x] chunk `sha256` 与其文本一致
- [x] 重复标题折叠保留正文标题，正文不含"未知"等站点残留
- [x] 识别不足时 fallback 且有说明；显式规则失败时抛错
- [x] 续跑跳过已完成来源、不产生重复记录（连跑三次）
- [x] 来源变更时拒绝续跑
- [x] 单行超长时独占一块并告警，仍可无损重组
- [x] **manifest 中不含任何原文句子**
- [x] 已存在的 run 目录在 `--no-resume` 时拒绝写入

**真实原文实测（本地，非自动化断言）：**

- 3 个来源 → 156 章 / 156 块，0 警告
- 章节边界人工抽查正确（如卷1 第1章 = 第 21–67 行，
  站点导航标题第 16 行被正确排除在正文外）

---

## 6. 风险

1. **分块粒度偏细**：156 章平均 4,476 字符，按 10,000 目标切分得到 **1 章 1 块**，
   即 Phase 2 需要 156 次提取调用。可在 Phase 2 用并发 + 缓存消化；不建议合并跨章分块。
2. **卷首/站点残留 9,655 字符不分块** —— 这是设计而非遗漏（不属于任何章节正文），
   但意味着卷首的版权页信息不会进入知识库。
3. **`insertion_order` 方向**仍未定论（见 `FORMAT_COMPATIBILITY.md` §9），Phase 5 前需实测。
4. 章节识别依赖行首格式；若换入排版不同的版本，需重跑 Phase 1 并人工核对章节数。

---

## 7. 历史

### Phase 0 — 格式与仓库基线（已合并）

- 私有 GitLab 仓库（不公开），初始提交 + 4 个 Phase 0 提交，110 项测试。
- 关键产出：`docs/FORMAT_COMPATIBILITY.md`（ST 1.19.0 源码级字段依据）、
  `docs/TAVO_IMPORT_CHECKLIST.md`、两个可导入的最小 fixture、酒馆格式层与校验器。
- 期间修正：误提交的 `egg-info` 产物；`doctor` 因缺凭据返回非零退出码；
  受版权小说原文未纳入 `.gitignore`（已封堵）。

---

## 8. 交付

- **改动摘要**：新增 `ingest` 子包与 `n2t ingest`；真实原文导入产出 156 章索引。
- **测试命令及结果**：`.venv/bin/python -m pytest` → **149 passed**；零网络调用。
- **尚未完成**：Phase 2–6；`docs/TAVO_IMPORT_CHECKLIST.md` 仍未经人工执行。
- **兼容性尚未验证的点**：Tavo 全部行为；ST 导入往返。
- **下一步**：Phase 2 — 分块原子事实提取。
