# 上游项目分析与取舍

分析日期：2026-10-16。以下记录基于公开仓库说明及可浏览的关键文件；本项目尚未复制任何上游源码。

## 1. worldbook-skill

来源：
- Repository / README: https://github.com/echo-xianyu/worldbook-skill
- Skill entry: https://github.com/echo-xianyu/worldbook-skill/blob/main/world-book-skill/SKILL.md
- Novel/derivative extraction guide: https://github.com/echo-xianyu/worldbook-skill/blob/main/world-book-skill/references/information-extraction-guide.md
- Worldbook design guide: https://github.com/echo-xianyu/worldbook-skill/blob/main/world-book-skill/references/world-book-guide.md
- Card-generator guide: https://github.com/echo-xianyu/worldbook-skill/blob/main/world-book-skill/references/card-generator-guide.md
- License: https://github.com/echo-xianyu/worldbook-skill/blob/main/LICENSE

### 项目定位

一个指导 Agent 制作和管理 SillyTavern 角色卡/世界书的 Skill + Python CLI 组合。它的长处主要是“怎样抽取、怎样组织、怎样把信息设计成有效世界书、怎样校验输出”，而不是高吞吐的全文批处理器。

### 值得借鉴

1. **原创/二创分流**：已有小说应进入证据驱动的信息提取路线，不能按原创设定流程随意补写。
2. **先采集，后建模，最后条目化**：将世界观总纲、人物档案、世界书规划与最终条目制作分开。
3. **章节范围与原文依据**：记录章节索引、人物首次/再次出场及关键事件位置，便于回查。
4. **多维人物档案**：身份、外貌、行为证据、关系、能力、目标、关键事件、出场章节应分开管理。
5. **世界书触发设计**：把常驻核心规则与按需触发的角色/地点/组织/物品详情分开，考虑关键词、secondary keys、位置、优先级、递归和预算。
6. **生成与校验分开**：让模型提供结构化内容，最终 JSON 由代码生成；生成后检查字段、position、递归参数、条目数量和内容缺失。
7. **中间档案是产品的一部分**：原始提取、规范化设定、世界书计划和最终文件都要保留，方便纠正漏项而无需重跑全文。

### 不直接照搬

1. **不把 description 强制留空当作铁律**。本项目的单卡是世界模拟器，需要在高优先级位置放少量世界运行规则、用户控制权和时间/知识边界；详细人物资料则进 worldbook。最终安排必须通过 token 与触发测试决定。
2. **不默认启用 MVU/EJS/HTML/CSS 美化**。这些不属于第一阶段目标。
3. **不照搬与原著忠实度无关的写作禁词**，包括特定标点、词汇、比喻的通用禁令。只实施可验证的质量约束：设定有来源、人物行为前后一致、不控制用户行动、知识边界正确。
4. **不将固定条目顺序、position 或递归值当成所有卡型的万能常量**。使用目标格式文档、样例 fixture 和实测结果确定值。
5. **不复制其提示词/文档的大段原文或 CLI 代码**。先用本项目自己的语言重新实现所需方法。

### 风险与限制

- README 明确说明项目基本由 AI 生成，可能出现问题，因此脚本和所谓规范都应通过测试验证。
- LICENSE 使用 CC BY-NC-SA 4.0；README 另外声明不用于收费 AI 平台、商业 API 服务或盈利性角色卡代写。用户计划使用免费 API，并愿意遵循限制。即便如此，也不要在本仓库直接复制其 Skill 正文、参考文档或代码；如未来确实要改编可版权表达，先复核许可证并保留所需署名、非商业和相同方式共享义务。

## 2. st_book

来源：
- Repository / README: https://github.com/nariahlamb/st_book
- Workflow: https://github.com/nariahlamb/st_book/blob/main/character_workflow.py
- Character extractor: https://github.com/nariahlamb/st_book/blob/main/character_extractor_llm.py
- Character merger: https://github.com/nariahlamb/st_book/blob/main/character_merger.py
- Character filter: https://github.com/nariahlamb/st_book/blob/main/character_filter.py
- Worldbook extractor: https://github.com/nariahlamb/st_book/blob/main/worldbook_extractor.py
- Worldbook generator: https://github.com/nariahlamb/st_book/blob/main/worldbook_generator.py
- License: https://github.com/nariahlamb/st_book/blob/main/LICENSE

### 项目定位

一个 Python 自动化管线：文本切块 → LLM 角色提取 → 合并/去重 → 筛选 → 生成角色卡；世界书则通过提取原始条目、分类/综合与参数优化生成。它更像可执行的数据处理流程，不是纯 Skill。

### 值得借鉴

1. **分块与分步 CLI**：`split / extract / merge / filter / create` 以及独立世界书流程，使出错后能从单个阶段重跑。
2. **配置驱动**：API、模型、分块大小、并发、重试和输出路径可配置。
3. **缓存/中间输出/恢复能力**：减少相同输入重复请求，并避免一次 API 失败导致从头重跑。
4. **两阶段生成思想**：先提取原子资料，再综合成更高层级设定，不把一次模型回答当作最终真相。
5. **模块化设计**：切块器、提取器、合并器、筛选器、世界书生成器、导出器分离。
6. **世界书参数优化作为可选阶段**：可以后续根据触发测试做调优，但不应第一版就让模型自动改大量参数。

### 必须修正或避免的设计

1. `character_filter.py` 的核心筛选逻辑按 JSON 文件大小排序保留前 N 个，并非按照剧情重要性、人物完整度或未来剧情关联评分。不能用文件体积代替人物重要性；默认流程应保留全部人物并打标签/优先级，只有用户明确设置上限时才裁剪。
2. `character_workflow.py` 的帮助说明称 `auto` 会清理并完整运行。新项目不得有默认清空工作目录的“自动模式”；每次 run 必须隔离输出，清理必须显式、可确认和可恢复。
3. 合并角色不能只依靠 LLM 一次性判断。必须有 aliases、来源证据、匹配置信度和 unresolved candidates；不确定就不合并。
4. 单纯输出角色概要会丢掉章节时间和人物在不同阶段的状态。规范化模型必须保存事件时间线、关系变化、秘密揭露时间与角色知识边界。
5. 世界书生成需要先有清楚的中间 schema 与字段校验，不能只凭提示词“生成三层架构”就相信输出一定完整。
6. 角色卡单体生成与“一个多角色世界模拟器”是不同产物。本项目首版优先生成一个世界模拟器主卡与其内嵌世界书，不直接把每个角色都导出成独立卡；独立 NPC 卡后续再做。

### 许可证

仓库 LICENSE 为 MIT。若未来确实直接复用代码，必须随派生/分发保留版权和许可证声明。本项目第一阶段只借鉴模块边界和流程思想，优先编写自己的实现，不复制源码。

## 3. 合并策略总结

| 子系统 | 主要借鉴来源 | 本项目方案 |
|---|---|---|
| 小说索引、章节追溯、人物多维采集 | worldbook-skill | 加强为结构化事实及来源证据表 |
| 世界观分层、条目触发设计 | worldbook-skill | 常驻核心 + 角色/地点/组织/物品/事件按需触发 |
| Python 分块、批处理、配置、缓存、重试 | st_book | 建立可恢复 CLI pipeline，每阶段独立可重跑 |
| 人物归一和去重 | 两者启发，但自行设计 | aliases + 证据 + 置信度 + 人工复核队列 |
| 人物筛选 | 不照搬 st_book 文件大小排序 | 默认不丢人物，使用 canonical importance / coverage 标记 |
| 角色卡 description | 不照搬 worldbook-skill 空字段规则 | 放少量不可缺席的模拟器核心规则；细节放 worldbook |
| 世界书 JSON 生成 | worldbook-skill 的 CLI 校验理念 | 内部 schema → Python serializer → JSON validator → Tavo 导入测试 |
| 长篇时间线/分支 | 本项目新增 | 保留 canon timeline + chapter-specific start state，屏蔽未来信息 |
| 写作风格和装饰 | 不做第一期 | 不加禁词模板、不启用 MVU/EJS/HTML |

## 4. 明确的技术原则

这不是把两个仓库整份拼在一起，也不是保留所有功能的“大一统”。我们提取的是方法：worldbook-skill 提供质量与信息组织原则，st_book 提供自动化流水线思路；数据模型、提示词和最终代码由本项目重新设计。
