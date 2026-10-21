# Novel-to-Tavern

把一部小说转成可导入 **SillyTavern / Tavo** 的多角色世界模拟器角色卡、世界书与时间线 ——
每一条事实都能回溯到原文的某一行。

[![tests](https://github.com/kylin-guo/novel-to-tavern/actions/workflows/tests.yml/badge.svg)](https://github.com/kylin-guo/novel-to-tavern/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![offline](https://img.shields.io/badge/tests-100%25%20offline-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

---

## 感谢与灵感

这个项目能出现，先要感谢三个开源项目：

| 项目 | 它给我的启发 |
|---|---|
| [nuwa-skill](https://github.com/alchaincyf/nuwa-skill) | 把「风格」拆成可观察、可执行的东西：表达 DNA、反模式、诚实边界。本仓库的作者风格蒸馏直接受它影响。 |
| [st_book](https://github.com/nariahlamb/st_book) | 酒馆世界书 / 角色卡的组织方式与格式取舍。 |
| [worldbook-skill](https://github.com/echo-xianyu/worldbook-skill) | 从小说里抽取资料、再组织成世界书的流程与检查清单。 |

我仔细读过它们的 README、SKILL 和工作流，然后结合自己的理解重写了实现：
**借鉴的是方法论，不是源码。** 本项目没有复制或分发上述项目的代码、提示词或文档正文，
许可证边界写在 [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)。

最初的动机很具体：我想在酒馆里把一部**没写完的小说**接着玩下去 ——
既不想丢原著的设定，也不想让 AI 用通用网文腔替我续写。
所以我先把「事实」和「文风」拆成两条线：一条保证不编造原著设定，
一条尽量模仿作者的写法。这个仓库就是这两条线的合并。

## 这是什么

给定一份小说的纯文本，产出一套能在既有酒馆客户端里使用的文件，
让用户**自己选一个起始时间点**开始扮演。

- **角色卡**：单文件 Character Card V2，内嵌世界书，直接导入。
- **世界书**：人物 / 地点 / 势力 / 事件 / 剧情主线，关键词触发；另有独立世界书与严格起始点版本。
- **时间线**：章节化事件、知识边界、冲突报告。
- **严格无剧透档**：起点之后的事实**不写进任何条目正文**。
- **可选：作者风格蒸馏**（默认关闭）：逐块观察文风 → 合并 → 编译档案 →
  Description 开头要求模仿作者风格，8 组完整档案作为触发式世界书条目。
- **可选：受控 HTML 条目**（默认关闭）：只允许 `span` + 配置字号/色板/斜体，
  作为世界书触发条目；这是提示词约束，不是运行时沙箱。

### 剧透防护的真实保证（重要，请先读）

**完整原著剧情 —— 包括结局 —— 就在卡里。** 它写在 `剧情主线（逐章）` 条目中
（25,483 字，覆盖全书 156 章），是一个**可触发**条目。因此：

- 本工具提供的是**提示词层面的时间纪律**：核心规则要求 NPC 把「标注章节晚于当前起始点的内容」
  视为尚未发生。**这是行为约束，不是访问控制。** 模型仍可能读到或说出后续剧情。
- **严格无剧透需要导出时按起始点过滤**，用 `worldbook_start_beginning.json`
  （已屏蔽起始点之后的内容）。该文件**不在这张卡内**，也不在本仓库中，需本地生成。
- 因此「从任意章节开始」在**默认单卡**下是**尽力而为**，不是硬保证。选哪一档由你决定。

细节见 [剧透防护](#剧透防护两个档位)。

| 产物 | 说明 | 在仓库里？ |
|---|---|---|
| `world_simulator_v2.json` | 单张多角色世界模拟器卡（Character Card V2），**内嵌世界书** | ✅ `exports/天之炽/`（示例） |
| `worldbook_start_beginning.json` | **按起始点过滤**的世界书，严格无剧透版 | ❌ 本地生成 |
| `worldbook_standalone.json` | 独立世界书，全部条目 | ❌ 本地生成 |
| `timeline.json` | 章节化事件时间线 | ❌ 本地生成 |
| `reports/audit.md` | 来源覆盖率、冲突、待复核项与兼容性检查 | ❌ 本地生成 |

> 只有主卡进了公开仓库 —— 它是唯一一个「单文件即可导入」的产物。
> `exports/天之炽/` 是**示例**，不要拿它当你的书；用你自己的原文重新导出。
> 其余产物含逐章剧情与逐字引文，只留在本地 `runs/`，与原文同等对待。

## 这不是什么

- 不是新的聊天客户端、Web 前端、移动端或 RPG 平台
- 不引入数据库、向量库、消息队列或 Web 框架
- 不做 MVU / EJS
- 不支持任意 HTML 美化；只提供**受控 span 子集**（字号/色板/斜体），
  以世界书触发条目形式可选提供，且不保证客户端一定渲染
- 不把小说**原文**逐字塞进角色卡（角色卡里是抽取后的条目，不是原文），
  也不把模型推断伪装成原著事实

---

## 作为 Agent Skill 安装（推荐给 Agent 用户）

仓库自带一个标准 **Agent Skill**：[`skills/novel-to-tavern/`](skills/novel-to-tavern/)——
工作流程、执行纪律、三份参考、三个随附脚本，按开放的 Agent Skills 协议组织，
可在 Claude Code、Codex、Cursor、Kimi Code 等兼容 runtime 中加载。装上之后，
下面「最快用法」里的提示词都不用写了，也不需要给 Agent 配 API 凭据：
**抽取由 Agent 自己完成**（file 引擎 + Agent 按 schema 生成的预生成响应）。

### 方式一：一句话安装（推荐，跨 runtime）

打开你正在用的 Agent，告诉它：

```text
帮我安装这个 skill：https://github.com/kylin-guo/novel-to-tavern/skills
```

或用通用 CLI 安装器（vercel-labs/skills，支持 50+ runtime，自动识别当前 runtime）：

```bash
npx skills add kylin-guo/novel-to-tavern/skills
```

需要指定 runtime 时加参数，如 `-a claude-code`、`-a codex`、`-a cursor`。

### 方式二：手动安装

| Runtime | 安装路径 |
|---|---|
| Claude Code | `~/.claude/skills/novel-to-tavern/` |
| Codex CLI | `~/.codex/skills/novel-to-tavern/` |
| Cursor | `~/.cursor/skills/novel-to-tavern/` |
| Kimi Code | `~/.agents/skills/novel-to-tavern/` |
| 其他 runtime | clone 后复制到对应 runtime 的 skills/ 目录 |

```bash
git clone git@github.com:kylin-guo/novel-to-tavern.git
# 例：Kimi Code 用户级安装
cp -r novel-to-tavern/skills/novel-to-tavern ~/.agents/skills/
```

### 方式三：当提示词用

runtime 不支持技能自动加载时，直接把
[`skills/novel-to-tavern/SKILL.md`](skills/novel-to-tavern/SKILL.md) 的内容
粘贴进对话 —— 它本质就是一份 markdown + YAML frontmatter。

### 如何使用

装好后**新开一个对话**（确认技能列表出现 `novel-to-tavern`），直接说人话：

```text
把 /path/to/小说目录 导出成可导入 SillyTavern/Tavo 的角色卡。
```

技能会接管：确认环境、写配置、跑
`ingest → extract → resolve → timeline → export`、复核产物并如实汇报。
它会先问你四件事：原文路径、起始章节/剧透敏感度、要不要作者风格蒸馏
（默认不开）、对话要不要 HTML 美化（默认不开，token 更高且只是提示词约束）。

> `scripts/check_card.py` 可独立校验任何一张 V2 卡（不只本仓库导出的），
> 发现「JSON 合法但客户端静默出错」的字段问题；`evals/evals.json` 是开发期
> 测试提示集，不进分发包。

---

## 最快用法：让 Agent 一句话导出角色卡

前提：你有一个能读仓库、能执行命令的 Agent（Claude Code / Codex / Cursor 等），
本机有 Python 3.10+，小说是 `txt` / `md`。装了上面的 Skill 就可以跳过本节
—— 以下是「不装技能、直接贴提示词」的用法。

### 一句话版

把下面一句发给 Agent，路径换成你的小说目录：

```text
把 /path/to/小说目录 用 https://github.com/kylin-guo/novel-to-tavern 导出成可导入
SillyTavern/Tavo 的角色卡；新建 run，不要覆盖已有 runs/；完成后告诉我卡在哪。
```

### 推荐版（把事情说清楚，少返工）

```text
请用 https://github.com/kylin-guo/novel-to-tavern 这个仓库，把 /path/to/小说目录
导出成可导入 SillyTavern/Tavo 的多角色世界模拟器角色卡。

要求：
1. 先读 README.md 和 AGENTS.md，不要修改小说原文。
2. 新建 run，产物写到 runs/<run_id>/，不要覆盖已有 runs/。
3. 按 ingest → extract → resolve → timeline → export 执行；verify 可选。
4. 事实抽取由你完成：用 file 引擎，按 ChunkExtraction schema 逐块生成预生成
   响应，引文必须逐字摘自原文，不要伪造抽取结果；不需要向我要 API 凭据。
5. 导出后跑一遍结构校验；把主卡路径、条目数、哪些验证做了/没做告诉我。
6. 默认不要开启作者风格蒸馏和 HTML 美化；如果我要，再按 README 的对应章节处理。
```

### Agent 会做什么

| 步骤 | 命令 | 产物 |
|---|---|---|
| 1. 准备 | `git clone` / `python -m venv` / `pip install -e ".[dev]"` | `.venv/` |
| 2. 导入 | `n2t ingest --run-id <id>` | 章节索引、分块 |
| 3. 抽取 | `n2t extract --run-id <id>` | 原子事实、引文定位 |
| 4. 归一 | `n2t resolve --run-id <id>` | canonical 实体 |
| 5. 时间线 | `n2t timeline --run-id <id>` | 事件、知识边界、世界书规划 |
| 6. 导出 | `n2t export --run-id <id> [--start-chapter N]` | `runs/<id>/exports/world_simulator_v2.json` |

> 抽取不需要 API：Agent 本身就是抽取模型（file 引擎 + 预生成响应，覆盖检查用
> `skills/novel-to-tavern/scripts/check_responses.py`）。长篇全量生成响应会消耗
> 较多 Agent token，建议先小样（`extract --limit N`）再全量；用户主动提供
> OpenAI 兼容凭据时可切 `openai_compatible`。
> **不要把 `exports/天之炽/` 里的示例卡当成你的书。**

### 导出之后

1. 把 `runs/<id>/exports/world_simulator_v2.json` 导入 Tavo / SillyTavern。
2. 剧透敏感就用 `--start-chapter N` 的严格档。
3. 按 [`docs/TAVO_IMPORT_CHECKLIST.md`](docs/TAVO_IMPORT_CHECKLIST.md) 逐项实测；
   「导入成功」不等于触发、常驻、剧透行为都正确。

---

## 作者风格蒸馏：默认关闭、怎么开、花多少 token

### 默认没有风格蒸馏

不改配置时 `style.enabled=false`：不会多调用模型，Description 里也没有
【写作要求：作者风格】和【叙事风格规范】。卡仍然可以正常用。

### 想开启时怎么跟 Agent 说

在导出提示词里加一句即可：

```text
在导出时开启作者风格蒸馏（style.enabled=true），观察全部章节；
如果 token 预算有限，用 observe_max_chunks 抽样，并在报告里写明覆盖率。
```

或者手动改 `config/config.yaml`：

```yaml
style:
  enabled: true
  max_runtime_tokens: 800
  worldbook_entries: true
  observe_max_chunks: 0    # 0 = 全部章节；>0 为确定性等距抽样
  merge_batch_size: 30
```

然后正常 `n2t export`：产物缺失/过期时会自动跑
`style-observe → style-compile`；产物新鲜时不需要凭据。

### 大概要花多少 token

以本仓库实测的《天之炽》156 章为例（全量观察，没有抽样）：

| 阶段 | 量级 |
|---|---|
| 章节级观察（156 块） | 约 **0.9M** token |
| 6 批合并 + 1 次编译 | 约 **0.16M** token |
| **合计** | **约 1.0–1.1M token**（本次实测 1,080,307） |

粗算规则：**每章约 6–7k token**，再加约 100–160k 的合并/编译开销。
这是**模型 token**，不是角色卡运行时占用；换成真实 API 时按你所用模型的单价计费。

想省 token 就用抽样：

| `observe_max_chunks` | 大致观察成本 | 覆盖率 |
|---|---|---|
| 0（全部，156 章） | 约 1.0–1.1M | 156 / 156 |
| 48 | 约 1/3 | 48 / 156 |
| 24 | 约 1/6 | 24 / 156 |
| 12 | 约 1/12 | 12 / 156 |

抽样是**确定性等距抽样**，首尾必含；`author_style/audit.md` 和 README
会写明「这是抽样，不是全量」。覆盖越少，风格档案越容易偏。

> 没有 API 凭据也能做：把预生成响应放进 `llm.precomputed_responses_dir`，
> 用 `file` 引擎。让 Agent 阅读原文生成这些响应同样会消耗 token，
> 只是不产生 API 账单。

### 风格卡会多出什么

- Description **最开头**：【写作要求：作者风格】，要求尽量模仿该作者文风，
  并指向世界书里标题以「作者风格：」开头的条目。
- Description 末尾：【叙事风格规范】精简规则（默认上限 800 token）。
- 世界书：**8 条触发式**作者风格条目（总体原则、句式、对白、心理、描写、意象、节奏、反模式）。
- 单轮常驻增量约 **850 token**；提到「作者风格」时 8 条一起触发，约 **3.3k token**。

**风格档案是自动蒸馏产物，不是「与作者文风完全一致」的证明。**
覆盖率、置信度、压缩丢弃项与人工复核项都在 `runs/<id>/author_style/audit.md`。

---

## 手动使用（CLI）

```bash
git clone git@github.com:kylin-guo/novel-to-tavern.git
cd novel-to-tavern

python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"

.venv/bin/python -m pytest      # 701 项离线测试，不联网、不花 API 额度
.venv/bin/n2t --help
```

运行期只依赖 `pydantic` 与 `PyYAML`；HTTP 走标准库 `urllib`，不引入 `requests` / `httpx`。

### 六个阶段

```bash
cp config/config.example.yaml config/config.yaml   # 改 source_path 指向你的小说
.venv/bin/n2t config-check

.venv/bin/n2t ingest                            # ① 导入 · 章节索引 · 分块
.venv/bin/n2t extract --run-id <run_id>         # ② 分块原子事实提取
.venv/bin/n2t resolve --run-id <run_id>         # ③ 实体消歧与角色档案
.venv/bin/n2t verify  --run-id <run_id>         # ④ 语义支持校验（可选但建议）
.venv/bin/n2t timeline --run-id <run_id>        # ⑤ 时间线 · 知识边界 · 世界书规划
.venv/bin/n2t export  --run-id <run_id>         # ⑥ 导出角色卡与世界书
```

| 阶段 | 做什么 | 关键约束 |
|---|---|---|
| ① `ingest` | 只读原文，检测章节，按章分块 | 区段**无缝铺满**原文；逐块可无损重组，否则中止 |
| ② `extract` | 提取人物/地点/组织/物品/事件/关系 | **行号由代码算出**，不接受模型自报 |
| ③ `resolve` | 提及聚成 canonical 实体 | 相似名**不自动合并**，低置信度进复核队列 |
| ④ `verify` | 判断引文**支不支持**那条主张 | 失败不静默放过；一条都调不通就整体中止 |
| ⑤ `timeline` | 时间线、知识边界、世界书规划 | 不编造绝对时间；冲突只报告不覆盖 |
| ⑥ `export` | 序列化成 V2 卡与独立世界书 | 校验不过就**不写文件**，不产出半成品 |

### 可选：作者风格分步命令

```bash
.venv/bin/n2t style-observe --run-id <run_id>   # 逐块观察写作风格（带逐字引文证据）
.venv/bin/n2t style-compile --run-id <run_id>   # 合并 → 编译档案 → 8 组世界书条目
```

产物在 `runs/<run_id>/author_style/`。详见
[`docs/AUTHOR_STYLE_PIPELINE.md`](docs/AUTHOR_STYLE_PIPELINE.md)。

### 可选：受控 HTML 世界书条目

默认关闭。开启 `rendering.html.enabled` 后，世界书多一条触发式条目
`wb_rendering_html`（不进 Description）。只允许 `<span>` + 配置里的
`font-size` / `color` / `font-style`；非法配置在 `config-check` 就报错。

> **这是提示词约束。** 本工具不声称能过滤 Tavo 运行时模型的 HTML 输出，
> 也不声称 Tavo 一定会渲染。详见 [`docs/HTML_RENDERING.md`](docs/HTML_RENDERING.md)。

### 严格起始点导出（结构性无剧透）

```bash
.venv/bin/n2t export --run-id <run_id> --start-chapter 40
```

额外产出一整套起点固定的产物：**起点之后的事实不写进任何条目正文**。
不是「加一句要求模型别看」，是那些内容根本不在文件里。
同时给出 `start_state_chapter_N.json`：此刻哪些事实已发生、哪些还没、
各角色已知什么（依据标注为推断）、已成立的关系。

不指定 `--start-chapter` 时只产出默认的「尽力而为」档，清单里会如实标注。

### 抽取引擎

支持两种，配置里切换（`llm.provider`）：

- `openai_compatible` —— 调用户自己配置的 endpoint。凭据**只**从环境变量 / `.env` 读取，
  只按配置里的变量名间接寻址；不硬编码供应商，缺凭据时报错并给出可操作提示。
  需要同时设置 `llm.extraction_model`。
- `file` —— 从目录读预生成的响应。没有可用凭据时，靠它仍能离线跑完整条管线；
  run 报告里会如实标注 `provider`，**不冒充 API 调用结果**。

凭据变量默认是 `NOVEL_TAVERN_BASE_URL` / `NOVEL_TAVERN_API_KEY`，
只写变量名到配置里，值放 `.env`（已在 `.gitignore` 中）。见 `.env.example`。

---

## 质量保证：每条事实都能回到原文

这是整个项目的核心设计，也是「不得与原文剧情或人物行为不符」的落点。

1. **模型只给引文，行号由程序算。**
   模型输出的每条事实带一段 `quote`；`evidence.locate_quote` 去掉空白后在原文里逐字检索，
   反推出**最紧的行区间**。跨行过多、超长、过短、找不到，一律拒绝。
2. **没有证据的内容不进 canon。**
   声称是原著事实却定位不到引文的条目，降级为 `needs_review` 并注明原因；
   后续阶段的条目正文只取 `accepted` 的 canon 事实。
3. **「找到了」还要问「是不是只有一处」。** 只取首次匹配会让「同一句话在书里出现两次」
   静默落到靠前那处。`locate_quote` 现在统计**全部**命中，多处命中降级为待复核；
   引文另有 4 字下限（短串在长篇里必然多处命中）。报告分别给出
   `引文逐字定位率` 与 `唯一定位率` —— 前者回答「能不能找到」，后者回答「是不是只有一处」。
4. **引文存在还要问「支不支持」。** `n2t verify` 逐条判断引文是否支持那条主张，
   判定为 `contradicted` / `insufficient_evidence` 的事实不进条目正文。
   调用失败**不静默放过** —— 一条都调不通就整体中止。
5. **导出前强制校验。**
   结构校验 + 内嵌/独立世界书一致性比对 + 密钥扫描，任一有 error 就中止导出。

### 这张卡的口径：世界模拟器，不是考据

定位是**多角色世界模拟器资料**，不是「逐字考据的原始文献」。由此有两个刻意的取舍：

- 语义校验判为 `partially_supported`（只支持了一半的复合事实）**照常进正文** ——
  在世界模拟器里它仍是有用的设定。计数独立出现在校验报告里，随时可查。
- **不设**「语义校验没跑完就不许导出」的硬门禁 —— 那会让没有 API 额度的人
  彻底无法离线导出。取而代之是如实标注：清单写 `executed: false`，
  audit 报告该列写「未执行」。

要换成严格考据口径，改动点是 `verify/schema.py` 的 `PROBLEM_VERDICTS`
（加上 `partially_supported`）；两处都有测试锁着当前行为，改时会失败提醒。

### 这些指标说明了什么，不说明什么

| 指标 | 它证明 | 它**不**证明 |
|---|---|---|
| `引文逐字定位率` | 引文**逐字存在于原文**，行号是程序算的 | 事实被**正确解读/归属**、没有漏掉否定、抽取没有遗漏 |
| `semantic_entailed_rate` | 引文**支持**那条主张 | 这是**模型判定**，不是人工审校；只覆盖已校验的那部分 |
| `唯一定位率` | 引文在原文里**只有一处**命中 | 那一处就是这条事实的出处（仍可能有归属错误） |
| 「`needs_review` 2 条」 | 只有 2 条事实的引文定位失败或多处命中 | 「已逐条人工审校」；也**不**说明剩下的都正确 |

本次运行**没有**跑语义校验（需要可用的 API 额度），只做了**抽样核对**
（10 条事实回原文比对，见 RUN_REPORT §7），**没有**全量人工审校。

### 实测（《天之炽》三部曲，156 章 / 69.8 万字）

| 指标 | 结果 | 这是什么指标 |
|---|---|---|
| 原子事实 | 1,806 | 抽取产量 |
| 实体 | 504（人物 153）；**176 个通过条目门槛 → 生成世界书条目** | 抽取产量 |
| 世界书条目 | 188（常驻 3，正文 63,882 字；其中 8 条作者风格条目） | 产物规模 |
| **引文逐字定位率** | **5,746 / 5,746 = 100.00%** | **来源定位**，非正确性 |
| **唯一定位率** | **5,739 / 5,746 = 99.88%**（多处命中 7 条） | 来源**唯一性** |
| `needs_review` 的事实 | **2**（引文定位失败或多处命中） | 来源定位 |
| 语义支持校验 | **未执行**（清单里如实写 `executed: false`） | —— |
| 全量人工审校 | **未做**（仅抽样） | —— |
| 常驻预算（粗估） | 1,855 token | 预算 |
| 最坏情况一句话 | `剧情主线` 全键同现 → 4 条 ≈ 24,860 token | 预算上界，构造值 |

示例产物见 [`exports/天之炽/world_simulator_v2.json`](exports/天之炽/world_simulator_v2.json)，
完整报告见 [`docs/RUN_REPORT.md`](docs/RUN_REPORT.md)。

### 还有一套黄金集

[`examples/gold/`](examples/gold/) 是一篇**自创**的八章微型小说 + 手写抽取 + 手标期望，
端到端跑一遍并算出精确率/召回率。它测的是**管线**，不是模型。

| 项 | 结果 |
|---|---|
| 应当生成条目的实体 | 8 / 8 |
| 应当保持沉默的实体 | 6 / 6 |
| 必须出现的事实 | 5 / 5 |
| 故意编造引文被挡在 canon 之外 | 1 / 1 |
| 已知限制（同名不同人会被合并） | 被测试**锁定** |

---

## 剧透防护：两个档位

| 档位 | 怎么做 | 保证强度 |
|---|---|---|
| **默认单卡**（`world_simulator_v2.json`） | 全书剧情在可触发条目内，靠核心规则的**时间纪律**约束 NPC | **尽力而为**。提示词不是访问控制，模型仍可能读到后续剧情 |
| **严格起始点**（`export --start-chapter N`） | 起点之后的事实**不写入任何条目正文**，人物索引只列已出场的人，剧情主线只渲染到第 N 章 | **结构性**。内容不在文件里，模型无从读到 |

严格档需要本地重跑导出（那些文件不在仓库中）。默认档适合「不介意剧透、想要完整参考」的用法。

实测（从第 1 章开始）：188 条 → **16 条**（其中 8 条是作者风格条目），
63,882 字 → **5,147 字**，采用 8 条事实、隐藏 1,798 条；
第 151–156 章的 34 条事件摘要命中 **0** 条。

---

## 目录结构

```text
novel-to-tavern/
├── src/novel_to_tavern/          # 可安装的 Python 包
│   ├── ingest/                   # ① 原文读取 · 章节索引 · 分块
│   ├── extract/                  # ② 事实抽取 · 证据定位 · schema 校验
│   ├── llm/                      # 引擎（OpenAI 兼容 / 文件）
│   ├── resolve/                  # ③ 实体消歧与角色档案
│   ├── verify/                   # ④ 语义支持校验
│   ├── timeline/                 # ⑤ 时间线 · 知识边界 · 世界书规划
│   ├── export/                   # ⑥ 角色卡与世界书装配 · 严格起始点 · 游玩模式
│   ├── style/                    # 旁路：作者风格观察 · 合并 · 编译 · 世界书条目
│   ├── render/                   # 旁路：受控 HTML 输出规范
│   ├── tavern/                   # 酒馆格式层（V2 卡 / 独立世界书 / 序列化 / 校验 / 触发模拟）
│   ├── cli.py                    # 命令行入口
│   ├── config.py                 # 配置模型（未知键直接报错）
│   ├── env.py  secrets.py  logging_setup.py
│   └── paths.py                  # runs/<run_id>/ 隔离，拒绝覆盖
├── tests/                        # 701 项离线单元测试
├── docs/                         # 公开文档（见下方「文档」）
├── examples/
│   ├── fixtures/                 # 最小合法卡与世界书 fixture（自创内容）
│   └── gold/                     # 黄金集：自创微型小说 + 手标期望
├── tools/                        # fixture 生成与防漂移脚本
├── skills/novel-to-tavern/       # Agent Skill（SKILL.md + references + scripts + evals）
├── config/config.example.yaml    # 配置示例
├── exports/天之炽/               # 唯一入库的示例主卡（衍生作品，不在 MIT 内）
├── .github/workflows/            # CI
├── AGENTS.md  CLAUDE.md          # Agent / Claude Code 的仓库规则
├── README.md  LICENSE  NOTICE.md
└── 本地、不入库：runs/  precomputed/  cache/  天之炽/  config/config.yaml
                 docs/internal/（内部计划、审查复核、任务单）
```

`runs/`、`precomputed/`、`cache/`、小说原文、本地配置与 `docs/internal/`
都在 `.gitignore` 中，与原文同等对待。公开仓库只保留代码、公开文档、
自创 fixture 与一张示例主卡。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 分层与阶段划分 |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | 事实、实体、事件、世界书条目的内部契约 |
| [`docs/FORMAT_COMPATIBILITY.md`](docs/FORMAT_COMPATIBILITY.md) | 酒馆格式的**字段级依据**与已知陷阱 |
| [`docs/CONFIG_REFERENCE.md`](docs/CONFIG_REFERENCE.md) | 每个配置键读在哪里 |
| [`docs/QUALITY_GATES.md`](docs/QUALITY_GATES.md) | 质量门禁清单 |
| [`docs/RUN_REPORT.md`](docs/RUN_REPORT.md) | 端到端运行报告与产物说明 |
| [`docs/TAVO_IMPORT_CHECKLIST.md`](docs/TAVO_IMPORT_CHECKLIST.md) | Tavo 手工实测步骤 |
| [`docs/AUTHOR_STYLE_PIPELINE.md`](docs/AUTHOR_STYLE_PIPELINE.md) | 作者风格蒸馏：方法论映射、操作、缓存与指纹、局限 |
| [`docs/HTML_RENDERING.md`](docs/HTML_RENDERING.md) | 受控 HTML：白名单、配置、触发条目、非沙箱声明 |
| [`docs/UPSTREAM_ANALYSIS.md`](docs/UPSTREAM_ANALYSIS.md) | 上游项目借鉴与弃用取舍 |
| [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) | 第三方许可证边界 |

`AGENTS.md` 是给 Agent 的仓库规则；`CLAUDE.md` 是 Claude Code 的入口。
内部计划与审查记录放在本地 `docs/internal/`，不随公开仓库分发。

---

## 已知限制

1. **默认档的剧透防护是提示词层面的，不是访问控制。** 单卡含全书剧情；
   要硬保证必须用 `--start-chapter N` 导出严格档。
2. **本次运行没有跑语义校验。** 100% 引文定位率只说明引文在原文里存在。
   `n2t verify` 能补上这一层，但需要可用的 API 额度。
3. **未做全量人工审校。** 只做了抽样核对（10 条事实回原文比对，见 RUN_REPORT §7）。
4. **Tavo 只验证到「导入成功」。** 触发、常驻、剧透行为、token 占用**均未验证**。
5. 事件**没有绝对时间**：原文未明确给出时 `occurred_at` 恒为 `null`，不予推算。
6. **在场不等于知晓，而且大量情况是「不知道」。** 知识边界只把「事实的主语就是它自己」
   当作已确立；事件参与者只记为**候补**（3,806 条记录里 2,078 条是候补）。
   角色通过信件、报告、传闻、他人转述或推断获得的知识，当前模型**表达不了**。
7. **抽取本身的遗漏未被度量** —— 出场多而事实少的实体（如只抽到 1 条事实的重要地点）
   多为**抽取遗漏**，不是原著里真的没写。
   这个遗漏也会影响严格档的人物名单：名单按 `first_appearance_chapter`（源自**提及抽取**）
   过滤，而模型未必为每个在章节摘要里出现的名字都产出一条提及。
   实测第 1 章：有一位公主出现在该章摘要里，却没有该章的提及记录，
   于是她不在严格档的人物名单里 —— **方向是少列，不是多列**，
   对剧透防护是安全的一侧（实测严格卡里出现的 4 个角色名，
   全部逐字存在于第 1 章原文）。
8. **同名不同人会被合并。** 归一阶段按字面同名聚类，原文明说是两个人的同名角色
   仍会合成一个实体。这个限制被黄金集测试**锁定**，修好时会失败提醒。
9. **触发词仍可能误伤。** 子串匹配不认识否定 —— 「我没见过西泽尔」一样会命中。
   本次产物里有 60 个条目只有单个触发词，1 个触发词短到 1 个汉字（`隆`）。
   `reports/worldbook_budget.md` 会把这些列出来。
10. **风格档案是自动蒸馏产物，不是「与作者文风完全一致」的证明。**
    观察覆盖率、置信度分布、压缩丢弃项与人工复核项都写在
    `author_style/audit.md`；证据不足的维度会保留 `unknown`，不强行填值。
11. **受控 HTML 只是提示词约束。** 不保证 Tavo 渲染、不保证模型遵守、
    不构成运行时过滤；HTML 规范条目本身也会占用触发预算。
12. **风格管线让导出可能发起 LLM 调用。** 仅在 `style.enabled=true`
    且产物缺失/过期时发生；产物新鲜时不需要凭据。产物过期判定基于
    `inputs_fingerprint`，改预算、来源 hash 或补充资料都会触发重跑。

---

## 版权与免责

- **代码与文档**：MIT，见下方「许可」。
- **导出的角色卡**：`exports/天之炽/world_simulator_v2.json` **确实发布在本公开仓库中**。
  它是原著小说的**衍生作品**，其权利归原著权利人所有，**不随代码许可证授予**。
  本仓库以技术演示为目的保留该样例，**不声称**拥有再分发、公开发布或商业化的权利。
  权利人若要求移除，见 [`exports/README.md`](exports/README.md)。
- 仓库内**不包含**任何小说原文；`runs/`、`precomputed/`、`cache/`、`天之炽/`
  均在 `.gitignore` 中，与原文同等对待。测试 fixture 全部为自行编写的占位文本。
- 本项目不复制上游项目（`nuwa-skill` / `st_book` / `worldbook-skill`）的源码或文档正文，
  只借鉴方法论。详见 [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)。
- 感谢三个项目带来的灵感；如果它们不存在，这个仓库大概不会出现。

## 许可

本仓库的**代码与文档**采用 [MIT 许可证](LICENSE)。

> **例外：`exports/` 下的角色卡不在 MIT 授权范围内。**
> 那些文件是原著小说的衍生作品，其权利归原著权利人；本仓库对导出的卡片
> 不授予任何许可，也不声称拥有再分发或公开发布的权利。
> 见 [`NOTICE.md`](NOTICE.md) 与 [`exports/README.md`](exports/README.md)。
