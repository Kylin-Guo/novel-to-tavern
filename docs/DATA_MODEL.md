# 内部数据模型（概念契约）

具体 Pydantic/dataclass/JSON Schema 由实现阶段确定，但必须覆盖以下语义。内部模型优先稳定、可追溯，最终酒馆格式通过 serializer 映射，不应让抽取提示词直接输出最终角色卡 JSON。

## 1. 所有事实都应带来源与状态

```json
{
  "fact_id": "fact_000123",
  "subject_id": "character_ren",
  "predicate": "occupation",
  "value": "王都调查员",
  "fact_type": "canon_fact",
  "valid_from_chapter": 12,
  "valid_to_chapter": null,
  "revealed_at_chapter": 12,
  "source_refs": [
    {
      "source_id": "novel_main",
      "chapter_id": "chapter_012",
      "start_line": 210,
      "end_line": 214,
      "quote": "仅保留足以验证该事实的短原文片段"
    }
  ],
  "confidence": 0.98,
  "review_status": "accepted"
}
```

`quote` 是示例占位符，不代表真实小说内容。行号无法可靠保留时，可用稳定段落 ID/字符范围替代，并在 manifest 中说明算法。不要把估算行号伪装为精确定位。

`fact_type` 建议枚举：

- `canon_fact`：原著明确陈述或充分确立的事实。
- `character_belief`：某角色相信的内容，未必客观正确。
- `rumor`：世界中流传的说法。
- `inference`：根据证据推断但原著未明说。
- `user_added`：用户主动补充的新设定。
- `reconstructed`：为了让缺失内容可运行而做的创作补全。
- `contradiction`：原文中存在不能直接消解的冲突。
- `unknown`：尚不清楚。

只允许 `canon_fact` 被无条件写入 canon 总纲。`inference`、`reconstructed` 必须清晰标记，并默认不与原著事实混在同一段里。

## 2. CanonicalCharacter

最低字段：

- `id`：稳定 ID，不以姓名作为唯一键。
- `canonical_name`、`aliases[]`、`titles[]`。
- `first_appearance_chapter`、`appearance_chapters[]`。
- `public_identity`、`background`、`appearance`、`speech_style`。
- `traits[]`：每个特征有证据/来源；区分原著明示和行为归纳。
- `goals[]`、`motivations[]`、`fears[]`、`limits[]`。
- `abilities[]`、`inventory[]`、`resources[]`。
- `relationships[]`：关系对象 ID、类型、方向、开始/变化章节、证据。
- `knowledge[]`：角色已知事实 ID，以及获知时间/来源。
- `secrets[]`：内容、知情者、首次揭露章节、是否允许在当前起始点注入。
- `source_refs[]`、`confidence`、`review_status`。

不要只用单一的“性格总结”替代角色在多个阶段的行为和动机变化。

## 3. Entity resolution（人物/实体归一）

每个合并建议都应记录：

- `candidate_entity_ids[]`
- `match_signals[]`（别名、相同经历、共同关系、明确化名声明等）
- `confidence`
- `decision`: `merge` / `keep_separate` / `needs_review`
- `evidence_refs[]`

绝不可仅因为名字相似就自动合并。默认对低置信度样本保留两个实体并输出待审清单。

## 4. Event 与时间线

每个事件至少包括：

- `event_id`、`title`、`summary`。
- `event_chapter`、`event_order`（用于章节内排序）。
- `occurred_at`（如小说明确给出）与 `relative_time`（如“次日”）；没有绝对时间则不要编造。
- `participants[]`、`location_id`、`causes[]`、`consequences[]`。
- `revealed_at_chapter`：读者/角色得到相关信息的章节，可与事件发生章节不同。
- `known_by[]`：已知情角色及其获知来源/章节。
- `source_refs[]`、`fact_type`、`confidence`。

把“事情发生的时间”和“读者/角色知道这件事的时间”分开，是防止剧透与角色越权知情的核心设计。

## 5. WorldbookEntry 内部结构

内部 schema 不应直接等同于 SillyTavern 输出字段：

- `entry_id`、`title`、`category`。
- `content_canonical`（基于来源的内容）与 `content_runtime`（为模型读取而做的精简表达）。
- `keys[]`、`secondary_keys[]`、`trigger_strategy`。
- `always_on`、`priority`、`position_policy`、`recursion_policy`、`budget_estimate`。
- `valid_from_chapter` / `valid_to_chapter`（时间相关条目）。
- `source_refs[]`、`entities[]`、`related_entries[]`。
- `quality_flags[]`、`review_status`。

serializer 再将这些字段映射成目标酒馆格式所需的真实字段。禁止把内部 schema 字段直接原样塞进最终文件，除非目标格式明确支持。

## 6. Export manifest

每轮导出保存：

- `project_id`、`run_id`、`created_at`。
- 输入文件 SHA-256 和解析器版本。
- 提取/合并/生成 prompt 版本与模型配置（不得包含 API key）。
- 起始章节、模式（canon/branch/freeform）。
- 输出文件 hash、验证结果、警告。

这样以后修改提示词或 schema 时，能够知道产物由什么输入与参数生成。
