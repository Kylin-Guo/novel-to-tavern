# Novel-to-Tavern：小说到酒馆世界的生成工具

> 项目代号。目标不是开发新酒馆客户端，而是把用户有权处理的完整小说/设定集，转换成可导入 Tavo（兼容 SillyTavern 格式）的多角色世界模拟器角色卡、内嵌/独立世界书，以及可追溯的剧情时间线和审计报告。

## 产品目标

给定一份小说文本，生成一套可以在既有酒馆客户端中使用的文件，使用户可以从原著某个时间点扮演主角、配角或自定义角色，并允许剧情分支，而不把原著后期发生的事件或秘密泄露给早期角色。

**首要交付物：**

1. `exports/world_simulator_v2.json`：单张多角色世界模拟器卡，采用兼容的 SillyTavern Character Card V2 JSON，并包含内嵌 `character_book`。
2. `exports/worldbook_standalone.json`：独立世界书，供 Tavo 支持的导入方式使用。
3. `exports/timeline.json`：章节化事件时间线、事件发生时间和来源依据。
4. `exports/start_states/`：可选的章节起始状态快照。
5. `reports/audit.md`：来源覆盖率、未知项、冲突、未解决问题与兼容性检查结果。
6. `project_data/`：可增量续跑的中间档案；不得只留下最终 JSON。

## 非目标

- 不开发新的聊天 UI、移动客户端、向量数据库服务或长期运行的 RPG 平台。
- MVP 不做 MVU、EJS、HTML/CSS 美化、状态栏装饰和复杂前端宏。
- 不把整本小说直接塞进角色卡或世界书。
- 不把模型推断伪装成原著事实。
- 不默认每个 NPC 都生成独立角色卡；第一阶段优先一张世界模拟器卡 + 世界书。
- 不强制要求使用某个付费模型/供应商。仅使用用户配置且符合其免费使用条件的 API。

## 设计原则

1. **原著证据优先**：所有重要事实尽量可以追溯到章节/段落/行号或原文片段。
2. **分层**：原始文本、抽取事实、规范化档案、世界书设计、导出 JSON 分开保存。
3. **分阶段提取**：先提取，后消歧合并，再设计世界书，最后生成角色卡；不要一步让模型“读完一本书然后全部吐出来”。
4. **时间敏感**：角色在章节 N 的知识只能来自 N 之前已获知的内容；后期真相不得泄露到早期设定。
5. **非破坏式运行**：每次执行使用独立 run 目录；默认续跑/备份，不删除旧输出。
6. **小步实施**：先做短篇样本的最小端到端闭环，再扩大到整本小说。
7. **真实校验**：JSON 能解析不代表酒馆能正确加载；必须验证字段结构、世界书条目数量和关键触发参数，最终用 Tavo 实际导入测试。

## 推荐第一步

让 Agent 阅读 [`AGENTS.md`](AGENTS.md)、[`docs/UPSTREAM_ANALYSIS.md`](docs/UPSTREAM_ANALYSIS.md)、[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 和 [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)，先产出实施计划，再实现 Phase 0/1，不要一次性开发所有功能。

## 上游项目参考

- [worldbook-skill](https://github.com/echo-xianyu/worldbook-skill)：重点参考二创提取方法、章节/行号追溯、世界观与世界书分层、卡片生成及验证流程。
- [st_book](https://github.com/nariahlamb/st_book)：重点参考可恢复的 Python 管线、配置驱动、分块提取、角色合并、重试/并发与中间产物。

上游项目分析、采纳点、弃用点和许可证边界详见 [`docs/UPSTREAM_ANALYSIS.md`](docs/UPSTREAM_ANALYSIS.md) 与 [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)。

## 当前状态

**Phase 0 已完成（格式与仓库基线）**，Phase 1 起尚未开始。

已具备：

- 可运行的 CLI 骨架：`n2t --help` / `version` / `config-check` / `doctor`
- 配置加载与校验（`config/config.example.yaml` 逐键建模，未知键直接报错）
- 密钥隔离：`.env` 不入库，日志经脱敏过滤器，导出前扫描密钥
- 非破坏式 `runs/<run_id>/` 目录隔离，已存在的 run 拒绝覆盖
- **酒馆格式层**：Character Card V2 + 内嵌 `character_book`、独立世界书，
  字段依据 SillyTavern 1.19.0 源码逐项核对（见 `docs/FORMAT_COMPATIBILITY.md`）
- 示例产物：`examples/fixtures/minimal_world_simulator_v2.json`（自创内容，可直接导入试）

尚未具备（后续阶段）：

- 小说导入、章节索引、分块（Phase 1）
- LLM 原子事实提取（Phase 2）
- 实体归一、时间线、知识边界（Phase 3–4）
- 从真实小说生成世界书与角色卡（Phase 5）

**尚未在 Tavo 实测。** 到 2026-10-16 为止没有任何导入记录，不得据此外推兼容性。
实测步骤见 [`docs/TAVO_IMPORT_CHECKLIST.md`](docs/TAVO_IMPORT_CHECKLIST.md)。

### 运行环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest          # 108 项离线测试，不访问网络、不花 API 额度
.venv/bin/n2t --help
.venv/bin/n2t config-check
```

Python 3.10+。运行期依赖只有 `pydantic` 与 `PyYAML`；不引入数据库、向量库或 Web 框架。

## 文档索引

| 文档 | 内容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 项目执行规则（证据、忠实度、安全边界） |
| [`docs/PLAN.md`](docs/PLAN.md) | 当前阶段的实施计划与验收划分 |
| [`docs/FORMAT_COMPATIBILITY.md`](docs/FORMAT_COMPATIBILITY.md) | 酒馆目标格式的字段依据与已知陷阱 |
| [`docs/TAVO_IMPORT_CHECKLIST.md`](docs/TAVO_IMPORT_CHECKLIST.md) | Tavo 手工实测步骤（待执行） |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Phase 0–7 路线图 |
| [`docs/UPSTREAM_ANALYSIS.md`](docs/UPSTREAM_ANALYSIS.md) | 上游项目借鉴与弃用取舍 |
