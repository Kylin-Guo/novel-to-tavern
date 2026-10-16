# Novel-to-Tavern

把一部小说转成可导入 **SillyTavern / Tavo** 的多角色世界模拟器角色卡、世界书与时间线 ——
每一条事实都能回溯到原文的某一行。

[![tests](https://github.com/Kylin-Guo/novel-to-tavern/actions/workflows/tests.yml/badge.svg)](https://github.com/Kylin-Guo/novel-to-tavern/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![offline](https://img.shields.io/badge/tests-100%25%20offline-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

---

## 这是什么

给定一份小说的纯文本，产出一套能在既有酒馆客户端里使用的文件，让用户从**任意章节**开始扮演，
并且**不会**把后面的剧情或秘密泄露给早期角色。

| 产物 | 说明 |
|---|---|
| `world_simulator_v2.json` | 单张多角色世界模拟器卡（Character Card V2），**内嵌世界书** |
| `worldbook_standalone.json` | 独立世界书，供单独导入 |
| `timeline.json` | 章节化事件时间线 |
| `reports/audit.md` | 来源覆盖率、冲突、待复核项与兼容性检查 |

## 这不是什么

- 不是新的聊天客户端、Web 前端、移动端或 RPG 平台
- 不引入数据库、向量库、消息队列或 Web 框架
- 不做 MVU / EJS / HTML / CSS 美化
- 不把整本小说塞进角色卡，也不把模型推断伪装成原著事实

---

## 快速开始

```bash
git clone git@github.com:Kylin-Guo/novel-to-tavern.git
cd novel-to-tavern

python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"

.venv/bin/python -m pytest      # 289 项离线测试，不联网、不花 API 额度
.venv/bin/n2t --help
```

运行期只依赖 `pydantic` 与 `PyYAML`；HTTP 走标准库 `urllib`，不引入 `requests` / `httpx`。

---

## 工作流

五个阶段，每段独立可重跑，产物写在 `runs/<run_id>/` 下，**默认不覆盖已有结果**。

```bash
cp config/config.example.yaml config/config.yaml   # 改 source_path 指向你的小说
.venv/bin/n2t config-check

.venv/bin/n2t ingest                            # ① 导入 · 章节索引 · 分块
.venv/bin/n2t extract --run-id <run_id>         # ② 分块原子事实提取
.venv/bin/n2t resolve --run-id <run_id>         # ③ 实体消歧与角色档案
.venv/bin/n2t timeline --run-id <run_id>        # ④ 时间线 · 知识边界 · 世界书规划
.venv/bin/n2t export  --run-id <run_id>         # ⑤ 导出角色卡与世界书
```

| 阶段 | 做什么 | 关键约束 |
|---|---|---|
| ① `ingest` | 只读原文，检测章节，按章分块 | 区段**无缝铺满**原文；逐块可无损重组，否则中止 |
| ② `extract` | 提取人物/地点/组织/物品/事件/关系 | **行号由代码算出**，不接受模型自报 |
| ③ `resolve` | 提及聚成 canonical 实体 | 相似名**不自动合并**，低置信度进复核队列 |
| ④ `timeline` | 时间线、知识边界、世界书规划 | 不编造绝对时间；冲突只报告不覆盖 |
| ⑤ `export` | 序列化成 V2 卡与独立世界书 | 校验不过就**不写文件**，不产出半成品 |

### 抽取引擎

支持两种，配置里切换（`llm.provider`）：

- `openai_compatible` —— 调用户自己配置的 endpoint。凭据**只**从环境变量 / `.env` 读取，
  只按配置里的变量名间接寻址；不硬编码供应商，缺凭据时报错并给出可操作提示。
- `file` —— 从目录读预生成的响应。没有可用凭据时，靠它仍能离线跑完整条管线；
  run 报告里会如实标注 `provider`，**不冒充 API 调用结果**。

---

## 质量保证：每条事实都能回到原文

这是整个项目的核心设计，也是「不得与原文剧情或人物行为不符」的落点。

1. **模型只给引文，行号由程序算。**
   模型输出的每条事实带一段 `quote`；`evidence.locate_quote` 去掉空白后在原文里逐字检索，
   反推出**最紧的行区间**。跨行过多、超长、找不到，一律拒绝。
2. **没有证据的内容不进 canon。**
   声称是原著事实却定位不到引文的条目，降级为 `needs_review` 并注明原因；
   后续阶段的条目正文只取 `accepted` 的 canon 事实。
3. **导出前强制校验。**
   结构校验 + 内嵌/独立世界书一致性比对 + 密钥扫描，任一有 error 就中止导出。

### 实测（《天之炽》三部曲，156 章 / 69.8 万字）

| 指标 | 结果 |
|---|---|
| 原子事实 | 1,806 |
| 实体 | 504（人物 153） |
| 引文逐字定位 | **5,746 / 5,746 = 100.00%** |
| 待人工复核 | **0** |

示例产物见 [`exports/天之炽/world_simulator_v2.json`](exports/天之炽/world_simulator_v2.json)，
完整报告见 [`docs/RUN_REPORT.md`](docs/RUN_REPORT.md)。

---

## 目录结构

```
├── src/novel_to_tavern/
│   ├── ingest/        ① 原文读取 · 章节索引 · 分块
│   ├── extract/       ② 事实抽取 · 证据定位 · schema 校验
│   ├── llm/           抽取引擎（OpenAI 兼容 / 文件）
│   ├── resolve/       ③ 实体消歧与角色档案
│   ├── timeline/      ④ 时间线 · 知识边界 · 世界书规划
│   ├── export/        ⑤ 角色卡与世界书装配
│   ├── tavern/        酒馆目标格式层（V2 卡 / 独立世界书 / 序列化 / 校验）
│   ├── cli.py         命令行入口
│   ├── config.py      配置模型（未知键直接报错）
│   ├── env.py  secrets.py  logging_setup.py   .env 读取 · 密钥脱敏 · 日志
│   └── paths.py       runs/<run_id>/ 隔离，拒绝覆盖
├── tests/             289 项离线单元测试
├── docs/              架构 · 数据模型 · 格式依据 · 实施计划 · 运行报告
├── exports/           生成的产物（含一张可直接导入的示例卡）
├── examples/fixtures/ 最小合法卡与世界书 fixture（自创内容）
├── tools/             fixture 生成与防漂移脚本
├── config/            配置示例
└── tasks/             阶段任务单
```

`runs/` 与 `precomputed/` 在 `.gitignore` 中 —— 它们含原文与逐字引文，与原文同等对待。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 分层与阶段划分 |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | 事实、实体、事件、世界书条目的内部契约 |
| [`docs/FORMAT_COMPATIBILITY.md`](docs/FORMAT_COMPATIBILITY.md) | 酒馆格式的**字段级依据**与已知陷阱 |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Phase 0–7 路线图 |
| [`docs/PLAN.md`](docs/PLAN.md) | 当前阶段的实施计划与验收划分 |
| [`docs/QUALITY_GATES.md`](docs/QUALITY_GATES.md) | 质量门禁清单 |
| [`docs/RUN_REPORT.md`](docs/RUN_REPORT.md) | 端到端运行报告与产物说明 |
| [`docs/TAVO_IMPORT_CHECKLIST.md`](docs/TAVO_IMPORT_CHECKLIST.md) | Tavo 手工实测步骤 |
| [`docs/UPSTREAM_ANALYSIS.md`](docs/UPSTREAM_ANALYSIS.md) | 上游项目借鉴与弃用取舍 |
| [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) | 第三方许可证边界 |

`AGENTS.md` 与 `CLAUDE.md` 是本项目**构建过程**的规则文件，用来说明这个仓库是怎么做出来的，
不是使用本工具的必需文档。

---

## 格式依据

目标格式的每个字段都指向 SillyTavern **1.19.0 的源码**，而非文档转述
（`convertCharacterBook` / `world_info_position` / `newWorldInfoEntryDefinition` 等）。
逐字段记录在 [`docs/FORMAT_COMPATIBILITY.md`](docs/FORMAT_COMPATIBILITY.md)。

期间确证了几个「JSON 合法但行为静默出错」的陷阱，例如：

- 内嵌条目的 `position` 必须是字符串 `"before_char"`；写数字 `0` 会被**静默当成** `after_char`
- 缺 `enabled` 字段 → 条目被永久禁用，且不报任何错
- 条目标题读的是 `comment`，不是 `name`
- `probability` 是「命中后的插入概率」，**不代表常驻上下文**

---

## 已知限制

- 事件**没有绝对时间**：原文未明确给出时 `occurred_at` 恒为 `null`，不予推算。
- 知识边界由「事件参与者」推断，标注为 `present_at_event`，不等于原著明文授权。
- 角色卡含全书剧情，剧透防护靠核心规则的**时间纪律**，不是靠条目隔离。
- 事实来自自动抽取，做了抽样核对，**未逐条人工审校**。

---

## 版权与免责

- **代码**：见下方「许可」。
- **导出的角色卡**（`exports/`）是原著小说的**衍生作品**，其权利不随代码许可证授予。
  角色卡涉及原著版权，导出不等于获得再分发、公开发布或商业化的许可。
- 仓库内**不包含**任何小说原文；测试 fixture 全部为自行编写的占位文本。
- 本项目不复制上游项目（`worldbook-skill` / `st_book`）的源码或文档正文，只借鉴方法。
  详见 [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)。

## 许可

本仓库的**代码与文档**采用 [MIT 许可证](LICENSE)。

> **例外：`exports/` 下的角色卡不在 MIT 授权范围内。**
> 那些文件是原著小说的衍生作品，其权利归原著权利人；本仓库对导出的卡片
> 不授予任何许可，也不声称拥有再分发或公开发布的权利。
> 见 [`NOTICE.md`](NOTICE.md) 与 [`exports/README.md`](exports/README.md)。
