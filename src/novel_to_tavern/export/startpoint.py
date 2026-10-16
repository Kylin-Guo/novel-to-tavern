"""严格起始点导出。

**为什么要有这个模块。** 默认那张卡把全书剧情放在一个可触发条目里，靠核心规则的
「时间纪律」要求模型别提后续 —— 那是**提示词层面的约束，不是访问控制**。
本模块走另一条路：把起始点之后的内容**从文件里删掉**。模型读不到不存在的东西。

产出：
- 按起始点截断后的条目计划（`StrictPlan.entries`）
- `start_state.json`：此刻的世界状态（活动事实、隐藏事实、各角色已知、关系状态）
- 一份「删了什么、为什么删」的差异清单，写进审计报告

**不做什么：** 不修改 canonical 数据，不删除任何源产物，不推断原文没写的东西。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import EventRecord, FactRecord, RelationRecord, SourceRef
from ..resolve.entities import CanonicalEntity
from ..timeline.build import KnowledgeItem, TimelineEvent
from ..timeline.worldbible import (
    PlannedEntry,
    entities_skipped_from_worldbook,
    facts_upto_chapter,
    plan_character_index,
    plan_entity_entries,
    plan_world_overview,
)
from .builder import ChapterDigest, build_plot_entry

StartMode = Literal["beginning", "chapter", "after_ending"]


class StartPoint(BaseModel):
    """一个起始点。`chapter_index` 是 **0 基**的章节下标。"""

    mode: StartMode
    chapter_index: int
    chapter_label: str
    total_chapters: int
    strict: bool = Field(
        default=False,
        description="True 表示条目已按此起点截断 —— 起点之后的内容不在文件里",
    )

    @property
    def is_beginning(self) -> bool:
        return self.mode == "beginning"

    @property
    def is_after_ending(self) -> bool:
        return self.mode == "after_ending"


class EntryDelta(BaseModel):
    """一个条目相对于「全量版本」的差异。"""

    entry_id: str
    title: str
    action: Literal["kept", "dropped", "truncated"]
    reason: str = ""
    chars_before: int = 0
    chars_after: int = 0


class StrictPlan(BaseModel):
    """严格起始点的完整规划结果，可追溯到每个条目的去留。"""

    start: StartPoint
    entries: list[PlannedEntry]
    deltas: list[EntryDelta]
    facts_total: int
    facts_included: int
    facts_excluded: int
    events_total: int
    events_included: int
    entities_total: int
    entities_with_entries: int
    skipped_entities: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def dropped(self) -> list[EntryDelta]:
        return [d for d in self.deltas if d.action == "dropped"]

    @property
    def truncated(self) -> list[EntryDelta]:
        return [d for d in self.deltas if d.action == "truncated"]


def resolve_start_point(
    *,
    mode: StartMode,
    chapter_index: int | None,
    digests_chapters: list[int],
    chapter_label: str = "",
) -> StartPoint:
    """把用户给的模式/章节号标准化成一个 `StartPoint`。"""
    if not digests_chapters:
        raise ValueError("没有章节信息，无法确定起始点")
    total = max(digests_chapters)
    if mode == "after_ending":
        index = total
    elif mode == "beginning":
        index = -1  # 第 1 章之前：什么都还没发生
    else:
        if chapter_index is None:
            raise ValueError("mode=chapter 时必须给 chapter_index")
        if chapter_index < 0 or chapter_index > total:
            raise ValueError(f"起始章节超出范围：{chapter_index}（全书 0–{total}）")
        index = chapter_index

    label = chapter_label or (
        "故事开头之前" if mode == "beginning" else f"第 {index + 1} 章"
    )
    return StartPoint(
        mode=mode,
        chapter_index=index,
        chapter_label=label,
        total_chapters=total,
        strict=True,
    )


def plan_strict(
    *,
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    events: list[EventRecord],
    digests: list[ChapterDigest] | None = None,
    start: StartPoint,
) -> StrictPlan:
    """按 `start` 规划条目，并记录每个条目被删/被截断的原因。

    返回的 `entries` **不含**核心规则条目（那条由调用方装配，因为它要追加
    「本卡为严格起始点」的说明），但**含**截断后的剧情主线。

    「故事开头之前」这一档等价于只用第 0 章之前存在的内容 —— 实际上什么都还没有，
    所以实体条目全部落空，只剩常驻的规则与空索引。这是诚实的：那一刻世界
    还没被叙述出来。用户想要开头就从第 1 章用起。
    """
    cutoff = None if start.is_after_ending else start.chapter_index

    overview = plan_world_overview(entities, facts, start_chapter=cutoff)
    index_entry = plan_character_index(entities, start_chapter=cutoff)
    entity_entries = plan_entity_entries(entities, facts, start_chapter=cutoff)
    plot = build_plot_entry(digests or [], upto_chapter=cutoff if cutoff is not None else None)

    entries: list[PlannedEntry] = []
    if overview:
        entries.append(overview)
    if index_entry:
        entries.append(index_entry)
    if plot:
        entries.append(plot)
    entries.extend(entity_entries)

    # 与「全量版本」对照，得出差异清单
    full_entries: dict[str, PlannedEntry] = {}
    full_candidates: list[PlannedEntry | None] = [
        plan_world_overview(entities, facts),
        plan_character_index(entities),
        build_plot_entry(digests or []),
        *plan_entity_entries(entities, facts),
    ]
    for candidate in full_candidates:
        if candidate is not None:
            full_entries[candidate.entry_id] = candidate

    kept_ids = {e.entry_id for e in entries}
    deltas: list[EntryDelta] = []
    for entry_id, full in full_entries.items():
        if entry_id not in kept_ids:
            deltas.append(
                EntryDelta(
                    entry_id=entry_id,
                    title=full.title,
                    action="dropped",
                    reason="起始点之前没有足够的已校验事实，此刻写不出内容",
                    chars_before=len(full.content_runtime),
                )
            )
    for entry in entries:
        full = full_entries.get(entry.entry_id)
        before = len(full.content_runtime) if full else 0
        after = len(entry.content_runtime)
        deltas.append(
            EntryDelta(
                entry_id=entry.entry_id,
                title=entry.title,
                action="truncated" if after < before else "kept",
                reason=(
                    f"只渲染起始点及之前的内容，删去 {before - after} 字"
                    if after < before
                    else ""
                ),
                chars_before=before,
                chars_after=after,
            )
        )

    skipped = entities_skipped_from_worldbook(entities, facts, start_chapter=cutoff)
    included_facts = facts_upto_chapter(facts, cutoff)
    included_events = [
        e
        for e in events
        if cutoff is None or e.chapter_index <= cutoff
    ]

    return StrictPlan(
        start=start,
        entries=entries,
        deltas=sorted(deltas, key=lambda d: (d.action, d.title)),
        facts_total=len(facts),
        facts_included=len(included_facts),
        facts_excluded=len(facts) - len(included_facts),
        events_total=len(events),
        events_included=len(included_events),
        entities_total=len(entities),
        entities_with_entries=len(entity_entries),
        skipped_entities=[(e.canonical_name, reason) for e, reason in skipped],
    )


# --- start_state.json ------------------------------------------------------


class KnowledgeSnapshot(BaseModel):
    """起始点快照里的一条知识。

    `acquired_at_chapter` 为空表示原文未确立该角色何时（或是否）知道 ——
    这是默认情况，不要当成 bug。
    """

    entity_name: str
    item_type: str
    item_id: str
    revealed_at_chapter: int
    acquired_at_chapter: int | None = None
    knowledge_status: str = "unknown"
    acquisition_method: str = "unknown"
    basis: str = "unknown"
    candidate: bool = False


class RelationshipState(BaseModel):
    from_entity: str
    to_entity: str
    relation: str
    first_seen_chapter: int
    last_seen_chapter: int
    source_refs: list[SourceRef] = Field(default_factory=list)


class StartState(BaseModel):
    """起始点的世界状态快照。**给人和程序看的，不直接进世界书。**"""

    schema_version: int = 1
    generated_at: str
    start_mode: StartMode
    start_chapter_index: int
    start_chapter_label: str
    total_chapters: int
    strict: bool
    #: 此刻已经发生的事实 —— 条目的正文只取这些
    active_fact_ids: list[str] = Field(default_factory=list)
    #: 此刻尚未发生的事实 —— 严格档下它们不在任何条目正文里
    hidden_fact_ids: list[str] = Field(default_factory=list)
    facts_included: int = 0
    facts_excluded: int = 0
    #: 每个人物此刻已知的事（依据是推断，见 basis）
    knowledge: list[KnowledgeSnapshot] = Field(default_factory=list)
    #: 此刻已经成立的关系
    relationships: list[RelationshipState] = Field(default_factory=list)
    entry_counts: dict[str, int] = Field(default_factory=dict)
    entries_dropped: int = 0
    entries_truncated: int = 0
    notes: list[str] = Field(default_factory=list)


def build_start_state(
    *,
    start: StartPoint,
    plan: StrictPlan,
    facts: list[FactRecord],
    events: list[EventRecord],
    relations: list[RelationRecord],
    knowledge: dict[str, list[KnowledgeItem]] | None = None,
) -> StartState:
    """组装 `start_state.json`。"""
    cutoff = None if start.is_after_ending else start.chapter_index

    included = facts_upto_chapter(facts, cutoff)
    included_ids = {f.fact_id for f in included}
    hidden = [f.fact_id for f in facts if f.fact_id not in included_ids]

    snapshots: list[KnowledgeSnapshot] = []
    for name, items in sorted((knowledge or {}).items()):
        for item in items:
            # 按**读者可见时间**过滤：角色何时知道未知，但内容本身
            # 不能在起始点之前出现过。用 acquired_at 会把候补全滤掉。
            if cutoff is not None and item.revealed_at_chapter > cutoff:
                continue
            snapshots.append(
                KnowledgeSnapshot(
                    entity_name=name,
                    item_type=item.item_type,
                    item_id=item.item_id,
                    revealed_at_chapter=item.revealed_at_chapter,
                    acquired_at_chapter=item.acquired_at_chapter,
                    knowledge_status=item.knowledge_status,
                    acquisition_method=item.acquisition_method,
                    basis=item.basis,
                    candidate=item.candidate,
                )
            )

    grouped: dict[tuple[str, str, str], list[RelationRecord]] = {}
    for relation in relations:
        if cutoff is not None and relation.chapter_index > cutoff:
            continue
        key = (relation.from_entity, relation.to_entity, relation.relation)
        grouped.setdefault(key, []).append(relation)

    relationships = [
        RelationshipState(
            from_entity=key[0],
            to_entity=key[1],
            relation=key[2],
            first_seen_chapter=min(r.chapter_index for r in items),
            last_seen_chapter=max(r.chapter_index for r in items),
            source_refs=list(items[0].source_refs[:1]),
        )
        for key, items in sorted(grouped.items())
    ]

    by_category: dict[str, int] = {}
    for entry in plan.entries:
        by_category[entry.category] = by_category.get(entry.category, 0) + 1

    notes = [
        "active_fact_ids 是「条目正文实际使用的 canon 事实」；"
        "hidden_fact_ids 是此刻尚未发生的，严格档下它们不出现在任何条目里。",
        "knowledge 里 candidate=true 表示**结构上可能知道**（例如事件参与者），"
        "但原文没有确立 —— 在场不等于看见或听懂，不要当作可靠依据。",
        "knowledge 里 acquired_at_chapter 为空是正常情况（原文未确立），不是数据缺失。",
        "occurred_at 一律为空：原文未给出绝对时间时本项目不推算。",
    ]
    if start.mode == "beginning":
        notes.append(
            "起点选在「第 1 章之前」时，世界尚未被叙述，实体条目会全部落空 —— "
            "这是正确行为，不是 bug。想要故事开头请从第 1 章用起。"
        )

    return StartState(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        start_mode=start.mode,
        start_chapter_index=start.chapter_index,
        start_chapter_label=start.chapter_label,
        total_chapters=start.total_chapters,
        strict=start.strict,
        active_fact_ids=sorted(included_ids),
        hidden_fact_ids=sorted(hidden),
        facts_included=len(included),
        facts_excluded=len(hidden),
        knowledge=snapshots,
        relationships=relationships,
        entry_counts=by_category,
        entries_dropped=len(plan.dropped),
        entries_truncated=len(plan.truncated),
        notes=notes,
    )


def write_start_state(path: Path, state: StartState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_knowledge(run_dir: Path) -> dict[str, list[KnowledgeItem]]:
    """读回 `canonical/knowledge.json`。不存在就返回空 —— 不阻断导出。"""
    path = run_dir / "canonical" / "knowledge.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: [KnowledgeItem.model_validate(item) for item in items]
        for name, items in raw.items()
    }


def load_timeline(run_dir: Path) -> list[TimelineEvent]:
    path = run_dir / "canonical" / "timeline.json"
    if not path.is_file():
        return []
    return [TimelineEvent.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
