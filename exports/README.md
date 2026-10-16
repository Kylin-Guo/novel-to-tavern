# 导出物

这里是程序生成的角色卡与世界书，**不是源码**，改动请改生成器再重跑。

## 天之炽/world_simulator_v2.json

由 `docs/RUN_REPORT.md` 记录的那次运行导出，可直接导入 SillyTavern / Tavo。

| 项 | 值 |
|---|---|
| 格式 | `chara_card_v2` / `spec_version 2.0` |
| 世界书 | 已内嵌在 `data.character_book`（508 条目，常驻 3 条） |
| 开场白 | 1 个主开场（让用户选起点）+ 2 个备用开场 |
| 来源 | 《天之炽》三部曲 156 章，1,806 条原子事实，引文 100% 可回溯 |

**导入时只需要这一个文件**，世界书已经包含在里面。

重新生成：

```bash
n2t ingest && n2t extract --run-id <id> && n2t resolve --run-id <id> \
  && n2t timeline --run-id <id> && n2t export --run-id <id>
```

## 版权

**本目录下的全部文件都不在根目录 MIT 许可证的授权范围内。**

这张卡是《天之炽》（作者：江南）的衍生作品，其权利归原著权利人所有。
本仓库对它不授予任何许可，也不声称拥有再分发、公开发布或商业化的权利。

详见根目录 [`NOTICE.md`](../NOTICE.md) 与 [`README.md`](../README.md) 的「许可」与「版权与免责」，
以及 [`../docs/THIRD_PARTY_NOTICES.md`](../docs/THIRD_PARTY_NOTICES.md)。
