# 目标架构

## 1. 总体流程

```text
小说原文（只读）
   │
   ▼
[1] 导入与章节索引
   │  source manifest / chapter index / stable line spans
   ▼
[2] 分块与检查点
   │  chunk manifest / content hash / resumable state
   ▼
[3] 分块事实提取（多任务、结构化输出）
   │  people / places / factions / items / rules / events / relations / evidence
   ▼
[4] 实体消歧与规范化
   │  canonical IDs / aliases / confidence / unresolved review queue
   ▼
[5] 时间线与知识边界构建
   │  event chronology / fact valid-from chapter / who-knows-what-when
   ▼
[6] 世界 Bible 与世界书规划
   │  always-on facts / trigger entries / keyword plans / budget estimates
   ▼
[7] 酒馆导出
   │  Character Card V2 + embedded character_book + standalone worldbook
   ▼
[8] 程序校验 + 质量审计
      schema validation / evidence coverage / temporal leakage / import fixture
```

各阶段只读取上游数据，输出到新目录；不得修改原始小说。每个阶段有独立 CLI 命令、状态文件和单元测试。

## 2. 三层资料模型

### A. 原始层（immutable source）

- 原小说文件及其 SHA-256。
- 章节索引、行号/段落范围、chunk manifest。
- 原文引文仅作为证据片段，不需要把整本小说复制到最终角色卡。

### B. Canonical 层（项目内的可信资料）

- 角色/组织/地点/物品等实体档案。
- 原子事实及来源、事实类型、时间范围、置信度。
- 事件时间线、人物关系和关系变化。
- 每名角色每个时间点所知信息的边界。
- 冲突项和需要人工确认的合并候选。

Canonical 层是生成世界书与角色卡的唯一事实来源。导出阶段不得直接调用 LLM 重新猜测事实。

### C. Runtime 层（酒馆加载资料）

- `description`/`system_prompt`/`post_history_instructions`：只放对每轮推理都重要、不能依赖关键词触发的模拟器规则。
- 内嵌世界书：角色、关系、地点、势力、物品、能力和特定事件等详细资料，按需触发。
- 独立世界书：与内嵌内容一致的单独导出，供客户端导入或维护。
- 起始时间点/记忆快照：由用户指定章节生成；不把该章节之后的 canon 事件当成当前已发生事件。

## 3. 第一版导出策略

### 主角色卡

生成一张多角色世界模拟器卡，而不是只生成某个原著主角的单人卡。它至少负责：

- 世界由多个 NPC 自主行动，而不是所有人围绕用户转。
- 用户拥有其扮演角色的行动、台词和内心状态决定权。
- NPC 的知识受已发生事件和获知渠道限制。
- 角色性格与动机不能无依据改变。
- 保持时间、地点、伤势、物品、资源与事件因果连续。
- 区分原著事实、角色信念、传闻、未知和分支剧情新事件。
- 当前故事从指定章节开始；进入分支模式后，未来原著事件不是必然结果。

`description` 不要求空置。只保留短而稳定的全局规则，避免把完整百科重贴进每轮提示词。

### 世界书

建议分组：

1. 核心世界运行规则（常驻，尽量精简）。
2. 世界概况（常驻或高优先级，限制长度）。
3. 角色索引/简述（可常驻但必须紧凑）。
4. 单角色详情（姓名、别名、称号触发）。
5. 组织与势力。
6. 地点和地理规则。
7. 物品、能力、术语。
8. 事件/章节背景（受起始章节和当前场景约束）。
9. 可选的特定时间点状态条目。

不要照搬固定的 `position`、`insertion_order` 或递归配置常数。需以目标格式和 Tavo 测试结果决定。

### 独立角色卡

后续可选：按用户所选角色生成单角色卡。角色卡引用同一份 canonical worldbook 数据；不要复制后再让多个卡独立漂移。

## 4. 时间与分支模式

- `canon_start`：从原著章节 N 的状态开始，允许 NPC 具备截至 N 章已获取的知识。
- `branch_start`：同一时间点起步，但后续行动由当前模拟产生；原著后期事件仅保留在本地隐藏参考资料中，不能进入活动提示词，除非被角色合法获知。
- `freeform_start`：可选后续模式，允许用户自定义初始状态。所有额外设定标记为用户输入或 reconstructed，而不是 canon。

事件至少保存 `event_chapter`、`event_order`、`revealed_at_chapter`（若与发生时间不同）和 `source_refs`。人物知识需要单独建模，不能简单认为事件发生后所有人都知道。

## 5. LLM 调用原则

- 初版默认一个 OpenAI-compatible endpoint 和一个模型；模型名、base URL、并发、超时、最大重试全部在配置中。
- 只调用用户配置的免费 API/免费额度 endpoint；不要硬编码供应商，不要自动切换到收费服务。
- 低创造性参数用于原文提取和归并，高创造性仅可用于卡片语言润色，且润色结果不能创建新 canon 事实。
- 对每次调用保存 `prompt_version`、输入 hash、输出 hash、模型名、状态、耗时和用量（若可获取）。
- 先校验 LLM JSON 输出，再落盘；失败内容进入错误目录，不要默默当作成功。
- 不需要把整本原文一次塞给模型。按章节分块提取，之后用 canonical 文件和必要证据做汇总。
