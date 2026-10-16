"""时间线与知识边界。

两件事必须分开：
- **事情发生的时间**（`occurred_at` / `relative_time`，只有原文明确给出才填）；
- **读者/角色知道它的时间**（`revealed_at_chapter`，即该内容在正文中出现的章节）。

没有明确时间时**不编造绝对日期**。知识边界由「事件参与者」推断得出，
并明确标注推断依据，不当作原著明文。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import EventRecord, FactRecord, FactType, RelationRecord, SourceRef

KnowledgeBasis = Literal["present_at_event", "subject_of_fact", "unknown"]


class TimelineEvent(BaseModel):
    event_id: str
    chapter_index: int
    chapter_id: str
    order_in_chapter: int
    title: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    fact_type: FactType = "canon_fact"
    occurred_at: str | None = Field(
        default=None, description="仅当原文明确给出时才填；否则为 null，不推算"
    )
    relative_time: str | None = Field(
        default=None, description="原文里的相对时间表述，如「次日」"
    )
    revealed_at_chapter: int = Field(description="该内容在正文中出现的章节")
    source_refs: list[SourceRef] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    entity_name: str
    item_type: Literal["event", "fact"]
    item_id: str
    chapter_index: int
    acquired_at_chapter: int
    basis: KnowledgeBasis
    source_refs: list[SourceRef] = Field(default_factory=list)


class LeakageFinding(BaseModel):
    start_chapter: int
    item_id: str
    item_type: str
    item_chapter: int
    reason: str


class ContradictionFinding(BaseModel):
    subject: str
    predicate: str
    values: list[str]
    chapter_indexes: list[int]
    note: str


#: 原文里常见的相对时间词，用于填 `relative_time` 而不推算绝对时间。
_RELATIVE_MARKERS = ("次日", "翌日", "第二天", "当晚", "当夜", "次日清晨", "几年后", "多年后", "数月后")


def extract_relative_time(*texts: str) -> str | None:
    """从摘录里识别相对时间表述。**不把相对时间换算成绝对日期。**"""
    for text in texts:
        for marker in _RELATIVE_MARKERS:
            if marker in text:
                return marker
    return None


def build_timeline(
    events: list[EventRecord],
    *,
    chapter_titles: dict[int, str] | None = None,
) -> list[TimelineEvent]:
    """按章节顺序、章节内顺序排出时间线。

    `occurred_at` 一律留空 —— 抽取阶段没有可靠依据给出绝对时间，
    宁可空着也不填一个看起来精确的假日期。
    """
    titles = chapter_titles or {}
    timeline: list[TimelineEvent] = []
    for event in sorted(events, key=lambda e: (e.chapter_index, e.order_in_chapter)):
        excerpt = "".join(ref.quote for ref in event.source_refs)
        timeline.append(
            TimelineEvent(
                event_id=event.event_id,
                chapter_index=event.chapter_index,
                chapter_id=event.chapter_id,
                order_in_chapter=event.order_in_chapter,
                title=event.title,
                summary=event.summary,
                participants=list(event.participants),
                location=event.location,
                fact_type=event.fact_type,
                occurred_at=None,
                relative_time=extract_relative_time(event.summary, excerpt),
                revealed_at_chapter=event.chapter_index,
                source_refs=list(event.source_refs),
            )
        )
    return timeline


def build_knowledge(
    events: list[EventRecord], facts: list[FactRecord]
) -> dict[str, list[KnowledgeItem]]:
    """按实体汇总「它知道什么、什么时候知道的」。

    依据只有两类，都是**推断**而非原著明文，故显式记录 `basis`：
    - `present_at_event`：该实体是事件参与者 → 在事件所属章节已知情；
    - `subject_of_fact`：该事实的主语是它自己。

    不作「事件发生后所有人都知道」这种假设。
    """
    knowledge: dict[str, list[KnowledgeItem]] = {}

    for event in events:
        if event.review_status != "accepted":
            continue
        for participant in event.participants:
            knowledge.setdefault(participant, []).append(
                KnowledgeItem(
                    entity_name=participant,
                    item_type="event",
                    item_id=event.event_id,
                    chapter_index=event.chapter_index,
                    acquired_at_chapter=event.chapter_index,
                    basis="present_at_event",
                    source_refs=list(event.source_refs[:1]),
                )
            )

    for fact in facts:
        if fact.review_status != "accepted":
            continue
        knowledge.setdefault(fact.subject, []).append(
            KnowledgeItem(
                entity_name=fact.subject,
                item_type="fact",
                item_id=fact.fact_id,
                chapter_index=fact.chapter_index,
                acquired_at_chapter=fact.chapter_index,
                basis="subject_of_fact",
                source_refs=list(fact.source_refs[:1]),
            )
        )

    for items in knowledge.values():
        items.sort(key=lambda k: (k.acquired_at_chapter, k.item_id))
    return knowledge


def check_leakage(
    *,
    start_chapter: int,
    events: list[EventRecord],
    facts: list[FactRecord],
) -> list[LeakageFinding]:
    """检查「起始章节 N 的状态里混进了 N 之后才出现的内容」。

    这是质量门禁 C 的自动化部分：任何 `chapter_index > start_chapter` 的内容
    都不允许进入该起始点的活动上下文。
    """
    findings: list[LeakageFinding] = []
    for event in events:
        if event.chapter_index > start_chapter:
            findings.append(
                LeakageFinding(
                    start_chapter=start_chapter,
                    item_id=event.event_id,
                    item_type="event",
                    item_chapter=event.chapter_index,
                    reason=f"事件发生在第 {event.chapter_index + 1} 章，晚于起始章节第 {start_chapter + 1} 章",
                )
            )
    for fact in facts:
        if fact.chapter_index > start_chapter:
            findings.append(
                LeakageFinding(
                    start_chapter=start_chapter,
                    item_id=fact.fact_id,
                    item_type="fact",
                    item_chapter=fact.chapter_index,
                    reason=f"该内容出现在第 {fact.chapter_index + 1} 章，晚于起始章节第 {start_chapter + 1} 章",
                )
            )
    return findings


def find_contradictions(facts: list[FactRecord]) -> list[ContradictionFinding]:
    """同一主语同一谓词出现多个不同取值 → 冲突报告，而不是悄悄选一个。"""
    buckets: dict[tuple[str, str], list[FactRecord]] = {}
    for fact in facts:
        if fact.fact_type != "canon_fact" or fact.review_status != "accepted":
            continue
        buckets.setdefault((fact.subject, fact.predicate), []).append(fact)

    findings: list[ContradictionFinding] = []
    for (subject, predicate), items in buckets.items():
        values = sorted({item.value for item in items})
        if len(values) < 2:
            continue
        findings.append(
            ContradictionFinding(
                subject=subject,
                predicate=predicate,
                values=values,
                chapter_indexes=sorted(item.chapter_index for item in items),
                note="同一主语同一谓词有多个取值：可能随时间变化，也可能是原文矛盾，需人工判断。",
            )
        )
    return sorted(findings, key=lambda f: (-len(f.values), f.subject))


def relation_timeline(relations: list[RelationRecord]) -> dict[str, list[RelationRecord]]:
    """按「实体对」汇总关系记录，保留章节顺序以便看出关系变化。"""
    grouped: dict[str, list[RelationRecord]] = {}
    for relation in sorted(relations, key=lambda r: r.chapter_index):
        if relation.review_status != "accepted":
            continue
        key = f"{relation.from_entity}→{relation.to_entity}"
        grouped.setdefault(key, []).append(relation)
    return grouped
