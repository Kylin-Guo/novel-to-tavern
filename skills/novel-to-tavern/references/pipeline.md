# 管线详解：六阶段、产物、响应生成、恢复与缓存

逐阶段手动执行、理解产物、或排查某一步时读本文件。

## 阶段总览

| 顺序 | 命令 | 产物（runs/<run_id>/ 下） |
|---|---|---|
| ① | `n2t ingest` | `manifest.json`（章节索引 + 全部分块） |
| ② | `n2t extract --run-id ID` | `extraction/`（事实 + 引文；非法响应隔离在 `_errors/`） |
| ③ | `n2t resolve --run-id ID` | `canonical/`（实体、关系、时间线、冲突、复核队列） |
| ④ | `n2t timeline --run-id ID` | `worldbook/`（事件、知识边界、世界书规划） |
| ⑤ | `n2t verify --run-id ID` | `verification/`（默认跳过，见下） |
| ⑥ | `n2t export --run-id ID` | `exports/`、`reports/`（含 audit.md、budget 报告） |

顺序约束：②依赖①，③依赖②，④依赖③，⑥依赖④。⑤ `verify` 依赖③，与④无依赖。
⑥导出时若 `style.enabled: true` 且风格产物缺失/过期，自动先跑风格管线
（见 style-and-html.md）。

常用选项：

- `n2t ingest --run-id ID` 复用/指定 run；不带则新建。`--source PATH` 临时覆盖
  `source_path`，`--no-resume` 强制重处理所有来源。
- `n2t extract --limit N` 只抽前 N 块（小样验证）。
- `n2t timeline --include-character 名字` 强制给某实体出条目（可重复），之后重跑 export。
- 全局 `--config PATH`、`--log-level DEBUG`。

## 默认路径：Agent 即抽取模型

配置 `llm.provider: file` 后，extract / style-observe 等阶段的模型响应全部由
调用本技能的 Agent 预先生成：

1. `n2t ingest` 生成 `runs/<id>/manifest.json`，`chunks[*]` 给出每块的
   `chunk_id`、`start_line`、`end_line`、`sha256`。
2. 对每块读原文对应行区间，按 `src/novel_to_tavern/extract/schema.py` 的
   `ChunkExtraction` 结构写出 `precomputed/<chunk_id>.json`。
3. `scripts/check_responses.py runs/<id> <precomputed目录>` 核对覆盖率；
   `n2t extract` 遇到缺失文件会**直接报错**（不静默跳过），所以先核对再跑。
4. 风格蒸馏同理：`style-observe` 缺响应时报错，先小样本（`--limit 4`）试运行，
   按报错补齐文件后再全量。

响应质量要求：

- `quote` 逐字摘自该块原文（schema 里可见哪些字段需要引文）；程序回查行号，
  改写、翻译、拼接的引文会被拒或降级 `needs_review`。
- 只提取该块内容，不跨块发挥；全书的归并与冲突检测由 resolve/timeline 阶段负责。
- 长篇全量生成的 token 成本与用户直接Agent读全书相当，动手前先和用户确认
  要不要先 `--limit N` 小样。

用户主动提供 OpenAI 兼容 endpoint 时，切换 `provider: openai_compatible`，
填 `extraction_model`，base URL/key 放 `.env`（变量名 =
`base_url_env` / `api_key_env`）。**不向用户索要凭据**；没有就走上面的默认路径。

## 各阶段要点

### ① ingest

章节检测错了后面全错。跑完先看 `manifest.json` 的 `chapters`：章节数是否符合
预期、标题是否乱码。不对就给 `chapter_heading_regex` 写显式正则（或
`chapter_detection: manual`），`--no-resume` 重跑。分块不变量：区段无缝铺满原文、
逐块可无损重组，不满足时 ingest 会中止——不要绕过带病继续。

### ② extract

行号由程序从引文反查，模型自报的行号不被采信。非法 JSON / 截断响应按
`quarantine_invalid_responses` 隔离到 `extraction/_errors/` 并写原因；限流/失败按
`max_retries` 与 `retry_backoff_seconds` 有限重试。

### ③ resolve

按字面同名聚类；低置信度匹配进复核队列。已知限制：**同名不同人会被合并**
（被黄金集测试锁定）。用户在卡片里指出时，记录受影响条目，不要手工改中间产物。

### ④ timeline

不编造绝对时间：原文没给时 `occurred_at` 恒为 `null`。冲突只报告不覆盖。

### ⑤ verify（默认跳过）

语义支持校验：`supported / partially_supported / contradicted / insufficient_evidence`。
后两者不进条目正文，`partially_supported` 按世界模拟器口径照常进正文并独立计数。
file 引擎下需要 Agent 生成逐条判定响应，成本高，用户没要求就不跑；用户要求时
先 `--sample N` 抽样。调用失败不静默放过，一条都调不通就整体中止。

### ⑥ export

校验不过不写文件。产物：

- `exports/world_simulator_v2.json` —— 主卡（内嵌世界书）
- `exports/worldbook_standalone.json`、`timeline.json`、`export_manifest.json`
- `reports/audit.md`（汇报数字来源）、`reports/worldbook_budget.md`
- 加 `--start-chapter N` 时另有 `worldbook_start_beginning.json` 与
  `start_state_chapter_N.json`

## 恢复、缓存与重跑判定

- `pipeline.resume: true`（默认）：中断后用**同一 run id** 重跑原命令即断点续跑。
  换 run id 等于从头再来。
- 缓存键含模型名、提示词版本、输入 hash、endpoint 指纹与生成参数：换模型/改原文
  旧缓存自动失效，不用手工清 `cache/`。
- 风格产物「过期」由 `inputs_fingerprint` 判定：改预算、来源 hash、补充资料都会
  触发重跑。
- 强制重来：单阶段 `--no-resume`；风格编译 `style-compile --no-resume`。
  不要删 `runs/` 下的目录来「重置」。
