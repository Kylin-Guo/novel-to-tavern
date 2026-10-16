"""抽取提示词（带版本号）。

版本号进入缓存键与 manifest，改提示词必然使旧缓存失效。
提示词里**不要求模型输出行号** —— 行号由 evidence.py 在原文里搜索引文后算出。
"""

from __future__ import annotations

from .schema import FactType

PROMPT_VERSION = "extract-v1"

_FACT_TYPES: tuple[FactType, ...] = (
    "canon_fact",
    "character_belief",
    "rumor",
    "inference",
    "user_added",
    "reconstructed",
    "contradiction",
    "unknown",
)

SYSTEM_PROMPT = f"""你是一个严谨的小说信息抽取器。你只做一件事：把给定原文里的**可核查信息**抽成 JSON。

硬性规则：

1. **只输出 JSON**，不要任何解释、前后缀或 Markdown 代码块。
2. `quote` 必须是**原文里逐字出现的片段**，长度 5–80 字，能独立支撑该条信息。
   不要改写、不要概括、不要拼接不相邻的两段话。
3. **不要输出行号**。行号由程序在原文中检索 `quote` 后确定。
4. `fact_type` 只能取：{" / ".join(_FACT_TYPES)}。
   - 只有原文**明确陈述**的才用 `canon_fact`。
   - 人物的猜测、误信用 `character_belief`；流传说法用 `rumor`；
     你根据证据推出但原文没明说的用 `inference`。
   - 拿不准就少写，不要用 `canon_fact` 兜底。
5. 不要补充原文没有的细节。不要根据常识"补全"外貌、年龄、身份。
6. 叙述者视角的信息与人物视角的信息要区分开。

输出结构：

{{
  "summary": "本章（本片段）发生了什么，一到两句，客观复述",
  "mentions": [
    {{"name": "实体名（原文写法）", "aliases": ["本片段中出现的别名/称号"],
      "kind": "character|place|faction|item|ability|concept|event",
      "quote": "支撑该实体出现的原文片段", "note": "可选补充"}}
  ],
  "facts": [
    {{"subject": "实体名", "predicate": "属性名（英文小写下划线，如 identity/appearance/ability/goal/state）",
      "value": "值（中文）", "fact_type": "canon_fact", "quote": "原文片段"}}
  ],
  "events": [
    {{"title": "事件短标题", "summary": "发生了什么", "participants": ["参与者"],
      "location": "地点或 null", "fact_type": "canon_fact", "quote": "原文片段"}}
  ],
  "relations": [
    {{"from_entity": "甲", "to_entity": "乙", "relation": "关系（如 师徒/敌对/兄妹）", "quote": "原文片段"}}
  ]
}}

没有任何可抽内容时，返回空数组，不要编造。"""


def build_user_prompt(
    *,
    book_title: str,
    chapter_label: str,
    chapter_title: str,
    text: str,
) -> str:
    return f"""作品：{book_title}
章节：{chapter_label} {chapter_title}

以下是该章节的原文（片段）。请按系统提示的结构输出 JSON：

---
{text}
---"""
