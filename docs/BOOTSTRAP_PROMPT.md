# 可直接发送给 Agent 的启动任务

请在当前仓库实现 Novel-to-Tavern。开始前必须阅读 `AGENTS.md` 与 `docs/` 下的架构、数据模型、上游分析、实现计划、质量门禁和第三方许可证说明。

**先不要直接写代码。** 请先检查仓库状态和现有文件，创建 `docs/PLAN.md`，并用中文向我汇报：

1. 你理解的目标与非目标。
2. `worldbook-skill` 和 `st_book` 分别借鉴什么、明确不复制什么。
3. Phase 0 最小实现计划，涉及文件、依赖、测试、风险。
4. 你如何验证 SillyTavern/Tavo 的角色卡和世界书 JSON 格式，避免猜字段。
5. 哪些验收可以自动完成，哪些需要最终在 Tavo 手工实测。

等待用户确认或依项目主 AGENTS.md 的执行约定继续。不要引入新平台/数据库/向量库，不要实现 MVU/EJS/HTML，不要一次性实现整条路线。

后续优先顺序：Phase 0 格式 fixture → Phase 1 章节导入 → Phase 2 原子事实提取 → Phase 3 实体归一 → Phase 4 时间线/知识边界 → Phase 5 酒馆导出 → Phase 6 Tavo 实测。每个阶段要有可运行测试和独立提交边界。
