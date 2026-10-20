# 第三方项目参考与许可证边界

本项目最初只参考以下公开项目的高层设计和公开说明；当前 starter 文档未包含从上游复制的源码或大段原文。

## worldbook-skill

- URL: https://github.com/echo-xianyu/worldbook-skill
- 仓库 LICENSE：CC BY-NC-SA 4.0。
- README 另有作者限制：不用于收费 AI 平台、商业 API 服务或盈利性角色卡代写业务。
- 用户计划使用免费 API，并表示愿意遵循作者限制。
- 处理原则：优先借鉴抽取流程/概念；不直接复制 Skill 文件、引用文档或 Python 源码。若未来要复制或改编具体文档/代码表达，实施前必须复核仓库当前 LICENSE、署名要求、非商业及相同方式共享要求，并明确给派生文件加来源和许可证说明。
- 不能仅凭“使用免费 API”推导出所有使用场景都自动合规；仍需遵守作品版权、作者限制和相关平台条款。

## nuwa-skill

- URL: https://github.com/alchaincyf/nuwa-skill
- 仓库 LICENSE：MIT（检索日期 2026-10-20）。
- 用途：**方法论参考**。「表达 DNA → 观察维度」「反模式 → anti_patterns」
  「诚实边界 → limitations」的映射写在 `docs/AUTHOR_STYLE_PIPELINE.md`。
- 处理原则：**本仓库不分发、不导入其代码或产物**；没有 `style-import` 命令，
  也不要求用户先装 Nuwa。风格蒸馏由本项目自己的 LLM 管线完成。
  其面向咨询场景的心智模型 / 实时调研流程不采用。
- 若将来复制或改编其具体文档/代码表达，必须复核当时的 LICENSE 与署名要求，
  并随分发保留版权声明。

## st_book

- URL: https://github.com/nariahlamb/st_book
- 仓库 LICENSE：MIT。
- 当前方案优先重新实现，不直接复制代码。若后续决定复用代码，必须把原 MIT LICENSE/版权声明随相关分发保留，并记录复用文件、修改和来源。

## 通用规则

- 不复制原小说全文到示例/测试中，除非测试材料明确为公版、用户拥有权利或已获得授权。
- 默认用自行创作的短篇 fixture 测试；不把有版权的原文作为仓库测试数据。
- 角色卡本身可能涉及原著版权。导出不等于获得再分发、公开发布或商业化的许可。
- 在项目 README 中如实说明功能与测试状态；不得以“兼容 Tavo”暗示已经完成实际导入测试，除非确有实测记录。
