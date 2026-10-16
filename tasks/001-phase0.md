# Task 001 — Phase 0: 格式与项目基线

## 目标

建立一个最小、离线可测的 Python CLI 基础，确认角色卡 V2 和世界书的目标格式后再进入小说提取。

## 任务

- [ ] 检查当前代码库与 Python 环境，不覆盖现有内容。
- [ ] 新建 `pyproject.toml`，设置最小必要依赖和测试命令。
- [ ] 建立 CLI `--help` 与配置读取。
- [ ] 查阅当前 SillyTavern 官方角色卡/World Info 规范，写入 `docs/FORMAT_COMPATIBILITY.md`，包含来源 URL、查阅日期和实际采用的字段。
- [ ] 建立最小角色卡 V2 + 内嵌 character_book JSON fixture。
- [ ] 建立独立世界书 JSON fixture（仅字段确有依据时）。
- [ ] 编写 JSON parse/schema/round-trip 测试。
- [ ] 验证 `.env` 不入库、日志无 secret。

## 验收

- [ ] 离线单元测试全部通过。
- [ ] 没有实际 API 调用。
- [ ] 没有假称已在 Tavo 导入成功。
- [ ] 告诉用户下一步如何手动导入 fixture 到 Tavo 做实测。
