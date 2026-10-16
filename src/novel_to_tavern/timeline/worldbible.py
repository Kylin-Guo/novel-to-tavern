"""世界 Bible 与世界书规划。

这一层只**整理与排布**已经过校验的 canonical 数据，不重新调用模型猜事实。
每个条目都带来源引用与生效章节，供 Phase 5 序列化成目标格式。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import EventRecord, FactRecord, SourceRef
from ..resolve.entities import CanonicalEntity
from .build import TimelineEvent

EntryCategory = Literal[
    "core_rules",
    "world_overview",
    "character_index",
    "character",
    "place",
    "faction",
    "item",
    "ability",
    "concept",
    "event",
]

#: 实体类别 → 世界书条目类别。
_KIND_TO_CATEGORY: dict[str, EntryCategory] = {
    "character": "character",
    "place": "place",
    "faction": "faction",
    "item": "item",
    "ability": "ability",
    "concept": "concept",
    "event": "event",
}

#: 每个谓词最多渲染多少条取值，避免单个角色条目膨胀。
MAX_VALUES_PER_PREDICATE = 4

#: 人物索引条目里最多列多少人。
MAX_INDEX_ENTRIES = 60

#: 单章事件条目最多带多少个触发词，避免一章人物太多时把常用词全吸进来。
MAX_EVENT_KEYS = 12

_CJK = re.compile(r"[㐀-䶿一-鿿぀-ヿ가-힯]")


class PlannedEntry(BaseModel):
    entry_id: str
    category: EntryCategory
    title: str
    content_runtime: str = Field(description="给模型读的精简表达，会进世界书")
    content_canonical: str = Field(description="带来源标注的版本，仅供审阅")
    keys: list[str] = Field(default_factory=list)
    secondary_keys: list[str] = Field(default_factory=list)
    always_on: bool = False
    valid_from_chapter: int | None = None
    valid_to_chapter: int | None = None
    entities: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    estimated_tokens: int = 0
    priority: int = 0
    quality_flags: list[str] = Field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 约 1 字 1 token，其余约 4 字符 1 token。

    这是**规划用的估算**，不是任何具体分词器的真实计数，报告里会注明。
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def _render_facts(
    facts: list[FactRecord], *, with_sources: bool
) -> str:
    """把原子事实渲染成条目正文。只取 review_status=accepted 的 canon 事实。"""
    buckets: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts:
        if fact.review_status != "accepted" or fact.fact_type != "canon_fact":
            continue
        buckets[fact.predicate].append(fact)

    lines: list[str] = []
    for predicate in sorted(buckets):
        seen: list[str] = []
        for fact in sorted(buckets[predicate], key=lambda f: f.chapter_index):
            if fact.value in seen:
                continue
            seen.append(fact.value)
            if len(seen) > MAX_VALUES_PER_PREDICATE:
                break
        if not seen:
            continue
        rendered = "；".join(seen)
        if with_sources:
            chapters = sorted({f.chapter_index + 1 for f in buckets[predicate]})
            rendered += f"（第 {'、'.join(str(c) for c in chapters[:6])} 章）"
        lines.append(f"{predicate}：{rendered}")
    return "\n".join(lines)


def _entity_keys(entity: CanonicalEntity) -> tuple[list[str], list[str]]:
    """实体条目的触发词。

    **名字、别名、称号全部作为主触发词**：任一出现都应让条目生效。
    不放进 `secondary_keys` —— `secondary_keys` 配合 `selective` 要求主次同时命中，
    那会让"只用称号提到这个角色"的场面漏触发（质量门禁 D 明确要求别名/称号可触发）。
    """
    keys = [k for k in dict.fromkeys([entity.canonical_name, *entity.aliases]) if k]
    return keys, []


def plan_entity_entries(
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    *,
    start_chapter: int | None = None,
) -> list[PlannedEntry]:
    """为每个实体规划一个世界书条目。

    **不按体量裁剪**：所有实体都会得到条目，重要性只体现在 `priority` 上。
    """
    facts_by_subject: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts:
        facts_by_subject[fact.subject].append(fact)

    entries: list[PlannedEntry] = []
    for entity in sorted(entities, key=lambda e: (-e.evidence_count, e.canonical_name)):
        names = {entity.canonical_name, *entity.aliases}
        own_facts = [f for name in names for f in facts_by_subject.get(name, [])]

        runtime = _render_facts(own_facts, with_sources=False)
        canonical = _render_facts(own_facts, with_sources=True)
        primary, secondary = _entity_keys(entity)

        flags: list[str] = []
        if not runtime:
            runtime = f"{entity.kind}：{entity.canonical_name}"
            flags.append("无已校验事实，仅条目占位")
        if len(runtime) > 1200:
            flags.append(f"内容偏长（{len(runtime)} 字），建议人工精简")

        entries.append(
            PlannedEntry(
                entry_id=f"wb_entity_{entity.id}",
                category=_KIND_TO_CATEGORY.get(entity.kind, "concept"),
                title=entity.canonical_name,
                content_runtime=runtime,
                content_canonical=canonical or runtime,
                keys=primary,
                secondary_keys=secondary,
                always_on=False,
                valid_from_chapter=entity.first_appearance_chapter,
                entities=[entity.canonical_name],
                source_refs=entity.source_refs[:3],
                estimated_tokens=estimate_tokens(runtime),
                priority=int(entity.importance * 100),
                quality_flags=flags,
            )
        )
    return entries


def plan_character_index(entities: list[CanonicalEntity]) -> PlannedEntry | None:
    """常驻的紧凑人物索引，让模型知道世界里有谁。"""
    characters = [e for e in entities if e.kind == "character"]
    if not characters:
        return None
    characters.sort(key=lambda e: (-e.evidence_count, e.canonical_name))

    lines = []
    for entity in characters[:MAX_INDEX_ENTRIES]:
        alias = f"（{ '、'.join(entity.aliases[:3]) }）" if entity.aliases else ""
        lines.append(f"{entity.canonical_name}{alias}")
    body = "世界中的主要人物：\n" + "、".join(lines)
    if len(characters) > MAX_INDEX_ENTRIES:
        body += f"\n（另有 {len(characters) - MAX_INDEX_ENTRIES} 人及次要角色，需要时在正文中出现）"

    return PlannedEntry(
        entry_id="wb_index_characters",
        category="character_index",
        title="人物索引",
        content_runtime=body,
        content_canonical=body,
        keys=[],
        always_on=True,
        estimated_tokens=estimate_tokens(body),
        priority=90,
    )


def plan_world_overview(
    entities: list[CanonicalEntity], facts: list[FactRecord]
) -> PlannedEntry | None:
    """常驻的世界概况：由证据量最高的地点/势力条目拼出。"""
    parts: list[str] = []
    for kind, label in (("place", "地点"), ("faction", "势力")):
        picked = sorted(
            (e for e in entities if e.kind == kind), key=lambda e: -e.evidence_count
        )[:8]
        if picked:
            parts.append(f"{label}：" + "、".join(e.canonical_name for e in picked))
    if not parts:
        return None

    body = "\n".join(parts)
    return PlannedEntry(
        entry_id="wb_overview",
        category="world_overview",
        title="世界概况",
        content_runtime=body,
        content_canonical=body,
        keys=[],
        always_on=True,
        estimated_tokens=estimate_tokens(body),
        priority=95,
    )


def plan_event_entries(
    timeline: list[TimelineEvent], *, start_chapter: int | None = None
) -> list[PlannedEntry]:
    """按**章**合并事件条目。

    早先的实现在每个事件上单开一个条目，结果是几百个 `keys=[]` 且非常驻的条目 ——
    它们永远不会被触发，纯属占位。现在同一章的事件合成一条，并把
    该章参与者与地点作为触发词，这样提到相关人物时该章背景才会进上下文。

    每个条目记录 `valid_from_chapter` —— 起始章节早于它的条目**不得**进入活动上下文。
    """
    by_chapter: dict[int, list[TimelineEvent]] = {}
    for event in timeline:
        by_chapter.setdefault(event.chapter_index, []).append(event)

    entries: list[PlannedEntry] = []
    for chapter_index in sorted(by_chapter):
        events = sorted(by_chapter[chapter_index], key=lambda e: e.order_in_chapter)
        label = events[0].chapter_label or f"第{chapter_index + 1}章"

        keys: list[str] = []
        for event in events:
            for name in [*event.participants, *( [event.location] if event.location else [] )]:
                if name and name not in keys:
                    keys.append(name)

        body_lines = [f"{label} 发生的事："]
        for event in events:
            line = f"- {event.title}：{event.summary.strip()}"
            if event.participants:
                line += f"（在场：{'、'.join(event.participants)}）"
            if event.location:
                line += f"［{event.location}］"
            body_lines.append(line)
        body = "\n".join(body_lines)

        flags = ["事件条目：需按起始章节屏蔽未来内容"]
        if not keys:
            flags.append("无参与者与地点，缺少触发词，只能随剧情主线条目一起被检索到")

        entries.append(
            PlannedEntry(
                entry_id=f"wb_chapter_events_{chapter_index:04d}",
                category="event",
                title=f"{label} 事件",
                content_runtime=body,
                content_canonical=body,
                keys=keys[:MAX_EVENT_KEYS],
                always_on=False,
                valid_from_chapter=chapter_index,
                entities=sorted({p for e in events for p in e.participants}),
                source_refs=[r for e in events for r in e.source_refs[:1]][:3],
                estimated_tokens=estimate_tokens(body),
                priority=30,
                quality_flags=flags,
            )
        )
    return entries


def filter_for_start_chapter(
    entries: list[PlannedEntry], start_chapter: int | None
) -> tuple[list[PlannedEntry], list[PlannedEntry]]:
    """按起始章节切分条目：`(可用, 被屏蔽)`。

    被屏蔽的条目**不删除**，只是不进入该起始点的活动上下文。
    """
    if start_chapter is None:
        return entries, []
    available: list[PlannedEntry] = []
    blocked: list[PlannedEntry] = []
    for entry in entries:
        if entry.valid_from_chapter is not None and entry.valid_from_chapter > start_chapter:
            blocked.append(entry)
        else:
            available.append(entry)
    return available, blocked


def summarize_plan(entries: list[PlannedEntry]) -> dict[str, int | float]:
    always_on = [e for e in entries if e.always_on]
    return {
        "total_entries": len(entries),
        "always_on_entries": len(always_on),
        "triggered_entries": len(entries) - len(always_on),
        "always_on_tokens": sum(e.estimated_tokens for e in always_on),
        "total_tokens": sum(e.estimated_tokens for e in entries),
    }
