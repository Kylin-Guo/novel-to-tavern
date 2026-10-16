"""时间线与知识边界。

两件事必须分开：
- **事情发生的时间**（`occurred_at` / `relative_time`，只有原文明确给出才填）；
- **读者/角色知道它的时间**（`revealed_at_chapter`，即该内容在正文中出现的章节）。

没有明确时间时**不编造绝对日期**。知识边界由「事件参与者」推断得出，
并明确标注推断依据，不当作原著明文。
"""

from __future__ import annotations

import re

from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import EventRecord, FactRecord, FactType, RelationRecord, SourceRef

#: 一条知识记录的依据。`unknown` 表示原文没有确立这条知识。
KnowledgeBasis = Literal["present_at_event", "subject_of_fact", "extraction_marked", "unknown"]

#: 角色与这条信息的关系。
#: - 只有 `knows` 是**已确立**的（原文明写，或该事实就是它自身的属性/行为）；
#: - `unknown` 是默认值 —— 原文没说的，就不替它说知道。
KnowledgeStatus = Literal[
    "knows",
    "suspects",
    "believes",
    "heard_rumor",
    "does_not_know",
    "unknown",
]

#: 怎么知道的。`witnessed` 只是「在场」，**不等于**看见或听见。
AcquisitionMethod = Literal[
    "subject",
    "witnessed",
    "author_explicit",
    "inferred",
    "rumor",
    "unknown",
]


class TimelineEvent(BaseModel):
    event_id: str
    chapter_index: int
    chapter_id: str
    chapter_label: str = ""
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
    """「某个角色知道某件事」的一条记录。

    **三个时间必须分开**（这是旧模型最主要的问题）：

    - `revealed_at_chapter` —— **读者**在正文里看到它的章节；
    - `acquired_at_chapter` —— **角色**可能知道的章节；原文没确立时为 `None`；
    - `occurred_at_chapter` —— 事情本身的章节（对事件而言）。

    旧模型把「事件参与者在事件章节就知道该事件」当成已确立的知识。
    那一步跨得太大：**在场不等于看见，看见不等于听懂**；角色也可能是在
    之后的章节里通过信件、报告、传闻、他人转述或自行推断才知道的。
    现在 `present_at_event` 只产生一个 `candidate`（`knowledge_status="unknown"`），
    **不产生** `knows`。
    """

    entity_name: str
    item_type: Literal["event", "fact"]
    item_id: str
    revealed_at_chapter: int
    occurred_at_chapter: int | None = None
    acquired_at_chapter: int | None = Field(
        default=None, description="角色可能知道的章节；原文未确立时为 None，不推算"
    )
    knowledge_status: KnowledgeStatus = "unknown"
    acquisition_method: AcquisitionMethod = "unknown"
    basis: KnowledgeBasis = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate: bool = Field(
        default=False,
        description="True 表示这只是一条**候选**：结构上可能知道，但原文没有确立",
    )
    note: str = ""
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

#: 更通用的相对时间：数量词 + 时间单位 + 方位词。
#: 光靠固定词表会漏掉「三天后」「两个时辰之后」这类写法 ——
#: 真实语料里它们和「次日」一样常见。
_RELATIVE_PATTERN = re.compile(
    r"([一二三四五六七八九十百千两0-9]+)\s*"
    r"(个)?\s*"
    r"(天|日|夜|年|月|周|星期|时辰|小时|刻钟|盏茶)"
    r"(之后|以后|后|之前|以前|前)"
)


def extract_relative_time(*texts: str) -> str | None:
    """从摘录里识别相对时间表述。**不把相对时间换算成绝对日期。**

    只把原文里的说法原样抠出来，不做任何换算 —— 「三天后」不是日期。
    """
    for text in texts:
        for marker in _RELATIVE_MARKERS:
            if marker in text:
                return marker
        match = _RELATIVE_PATTERN.search(text or "")
        if match:
            return match.group(0).replace(" ", "")
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
                chapter_label=event.chapter_label,
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


#: 由抽取器**显式标注**的类型 → 该主语与这条信息的关系。
#: 这几类不需要猜测：抽取阶段已经说了这是谁的信念、传闻还是推断。
_MARKED_STATUS: dict[str, tuple[KnowledgeStatus, AcquisitionMethod, float]] = {
    "character_belief": ("believes", "author_explicit", 0.9),
    "rumor": ("heard_rumor", "rumor", 0.4),
    "inference": ("suspects", "inferred", 0.6),
}


def build_knowledge(
    events: list[EventRecord], facts: list[FactRecord]
) -> dict[str, list[KnowledgeItem]]:
    """按实体汇总「它知道什么、什么时候知道的」。

    **只记录能站住的，其余一律留白。** 三档：

    1. **已确立（`knows`）** —— 只有一种情况：该事实的主语就是它自己
       （`subject_of_fact`）。一个人知道自己叫什么、什么状态、做过什么，
       这是唯一不需要额外证据的知识关系。
    2. **抽取器标注的信念/传闻/推断** —— 抽取阶段已经区分了
       `character_belief` / `rumor` / `inference`，直接沿用，标 `author_explicit`。
    3. **候补（`candidate=True`，状态 `unknown`）** —— 事件参与者。
       结构上「可能在场」，但**没有**任何证据说明它看见了、听懂了、记住了。
       `acquired_at_chapter` 留 `None`，不推算。

    不作「事件发生后所有人都知道」这种假设，也不把在场当成知晓。
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
                    revealed_at_chapter=event.chapter_index,
                    occurred_at_chapter=event.chapter_index,
                    acquired_at_chapter=None,
                    knowledge_status="unknown",
                    acquisition_method="witnessed",
                    basis="present_at_event",
                    confidence=0.2,
                    candidate=True,
                    note=(
                        "该角色是事件参与者，可能在场 —— 但在场不等于看见或听懂，"
                        "原文没有确立它是否知情"
                    ),
                    source_refs=list(event.source_refs[:1]),
                )
            )

    for fact in facts:
        if fact.review_status != "accepted":
            continue
        marked = _MARKED_STATUS.get(fact.fact_type)
        if marked is not None:
            status, method, confidence = marked
            note = f"抽取阶段把这条标为 {fact.fact_type}，据此记录"
            basis: KnowledgeBasis = "extraction_marked"
        else:
            status, method, confidence = "knows", "subject", 0.85
            note = "该事实的主语就是它自己 —— 一个人知道自己是什么、在做什么"
            basis = "subject_of_fact"

        knowledge.setdefault(fact.subject, []).append(
            KnowledgeItem(
                entity_name=fact.subject,
                item_type="fact",
                item_id=fact.fact_id,
                revealed_at_chapter=fact.chapter_index,
                occurred_at_chapter=None,
                acquired_at_chapter=fact.chapter_index if status == "knows" else None,
                knowledge_status=status,
                acquisition_method=method,
                basis=basis,
                confidence=confidence,
                candidate=status != "knows",
                note=note,
                source_refs=list(fact.source_refs[:1]),
            )
        )

    for items in knowledge.values():
        items.sort(key=lambda k: (k.revealed_at_chapter, k.item_id))
    return knowledge


def knowledge_summary(knowledge: dict[str, list[KnowledgeItem]]) -> dict[str, int]:
    """按状态统计知识记录。**候选占多数是正常且诚实的**，不是缺陷。"""
    summary: dict[str, int] = {"total": 0, "entities": len(knowledge), "candidates": 0}
    for items in knowledge.values():
        for item in items:
            summary["total"] += 1
            summary[item.knowledge_status] = summary.get(item.knowledge_status, 0) + 1
            if item.candidate:
                summary["candidates"] += 1
    return summary


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
