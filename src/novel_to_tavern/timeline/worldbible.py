"""世界 Bible 与世界书规划。

这一层只**整理与排布**已经过校验的 canonical 数据，不重新调用模型猜事实。
每个条目都带来源引用与生效章节，供 Phase 5 序列化成目标格式。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import FactRecord, SourceRef
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

#: 生成世界书条目的门槛。满足**其一**即可：
#:   ① 至少有 MIN_ENTITY_FACTS 条已校验的 canon 事实；
#:   ② 至少有 1 条事实，且至少在 MIN_ENTITY_CHAPTERS 个章节里出现过。
#:
#: 为什么不能只看事实条数：实测「教皇国」出场 17 章却只抽到 1 条事实、
#: 「赫克托耳家长」出场 10 章只有 1 条 —— 那是抽取漏了，不是它们不重要。
#: 为什么第二条还要求「至少有 1 条事实」：一条事实都没有就**写不出任何内容**，
#: 保留了也只是一个空条目，比「item：玩具熊」那种空壳更糟。
MIN_ENTITY_FACTS = 2
MIN_ENTITY_CHAPTERS = 3

#: 世界概况里各分类最多列多少个「带一句说明」的实体。
OVERVIEW_TOP_PER_KIND = {"faction": 6, "place": 8, "concept": 5, "ability": 4, "item": 4}

#: 世界概况里「只列名字」的补充清单上限。
OVERVIEW_NAME_ONLY_LIMIT = 24

#: 概况里单条说明的最大长度。
OVERVIEW_LINE_CHARS = 64

#: 人物索引条目里最多列多少人。
MAX_INDEX_ENTRIES = 60

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
    chapter_gated: bool = Field(
        default=False,
        description="是否按起始章节屏蔽。只有「剧情类」条目为真 —— "
        "人物与地点在世界里本来就存在，不该因为尚未登场就被过滤掉。",
    )
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


def _reject_duplicate_entity_ids(entities: list[CanonicalEntity]) -> None:
    """实体 id 必须唯一。

    这里挡的是一个**静默**故障：条目 id 由 `entity.id` 派生、事实也按 `entity.id`
    归集，所以两个实体撞 id 时，后者的事实会顶掉前者的 —— 而卡片结构完全合法，
    校验也通不过任何一项。宁可在这里报错，也不要产出一张看起来正常的错卡。
    """
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for entity in entities:
        if entity.id in seen:
            duplicates.append(f"{entity.id}（{seen[entity.id]!r} 与 {entity.canonical_name!r}）")
        else:
            seen[entity.id] = entity.canonical_name
    if duplicates:
        raise ValueError(
            "实体 id 重复，事实会互相顶掉：" + "；".join(duplicates[:5])
        )


def facts_upto_chapter(
    facts: list[FactRecord], start_chapter: int | None
) -> list[FactRecord]:
    """截到第 `start_chapter` 章（含）为止的事实。

    `None` 表示不过滤。这是**严格起始点导出**的核心：起点之后的内容
    不进入条目正文，而不是进了正文再叫模型别看。
    """
    if start_chapter is None:
        return facts
    return [f for f in facts if f.chapter_index <= start_chapter]


def _facts_by_entity(
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    *,
    start_chapter: int | None = None,
) -> dict[str, list[FactRecord]]:
    """`{entity.id: [该实体的已校验 canon 事实]}`。

    `start_chapter` 非空时只收该章节及之前的 fact —— 严格起始点用。
    """
    _reject_duplicate_entity_ids(entities)
    by_subject: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts_upto_chapter(facts, start_chapter):
        if fact.review_status != "accepted" or fact.fact_type != "canon_fact":
            continue
        by_subject[fact.subject].append(fact)

    result: dict[str, list[FactRecord]] = {}
    for entity in entities:
        names = {entity.canonical_name, *entity.aliases}
        collected: list[FactRecord] = []
        for name in names:
            collected.extend(by_subject.get(name, []))
        result[entity.id] = collected
    return result


def entry_qualification(entity: CanonicalEntity, own_facts: list[FactRecord]) -> tuple[bool, str]:
    """该实体是否值得单开一个世界书条目，以及不符合时的原因。"""
    if len(own_facts) >= MIN_ENTITY_FACTS:
        return True, ""
    if not own_facts:
        return False, "没有任何已校验的 canon 事实 —— 写不出内容"
    if len(entity.appearance_chapters) >= MIN_ENTITY_CHAPTERS:
        # 反复出现说明故事确实在用它，只是抽取没抽够 —— 保留，内容偏薄由报告提示
        return True, ""
    return False, (
        f"只有 {len(own_facts)} 条事实，且只在 {len(entity.appearance_chapters)} 个章节里出现过"
        "（像顺带一提）"
    )


def entities_skipped_from_worldbook(
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    *,
    start_chapter: int | None = None,
) -> list[tuple[CanonicalEntity, str]]:
    """不该单开世界书条目的实体及原因。

    这些实体仍保留在 canonical 数据里（来源可追溯），只是不进世界书。
    名单会写进报告，不是静默丢弃。

    `start_chapter` 非空时按该章节截断事实再判定 —— 严格起始点下
    「后面才有了事实」的实体此刻确实写不出内容，与「抽取漏了」不是一回事，
    所以原因里会写清楚。
    """
    by_entity = _facts_by_entity(entities, facts, start_chapter=start_chapter)
    full_counts: dict[str, int] = {}
    if start_chapter is not None:
        full_counts = {
            key: len(value) for key, value in _facts_by_entity(entities, facts).items()
        }

    result: list[tuple[CanonicalEntity, str]] = []
    for entity in entities:
        own = by_entity.get(entity.id, [])
        ok, reason = entry_qualification(entity, own)
        if not ok:
            total = full_counts.get(entity.id, len(own))
            if start_chapter is not None and total > len(own):
                reason = (
                    f"起始点之前只有 {len(own)} 条事实（全书共 {total} 条）"
                    "—— 严格起始点下此刻内容不足，不是抽取遗漏"
                )
            result.append((entity, reason))
    return result


#: 概括一个实体时优先用哪些谓词 —— 越靠前越像「它是什么」，越靠后越像「它做了什么」。
_HEADLINE_PREDICATES = (
    "identity",
    "background",
    "ability",
    "possession",
    "appearance",
    "alias",
    "goal",
    "state",
    "action",
)

#: 定义式表述的标志词。有这些词的取值更像"这东西是什么"，而不是"它这章干了什么"。
_DEFINITIONAL_MARKERS = ("是", "叫做", "称为", "名为", "属于", "指", "由")


def clip_at_sentence(text: str, limit: int = OVERVIEW_LINE_CHARS) -> str:
    """按长度裁剪，但**在句读处断开**，不把句子切在半截。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    for mark in ("。", "；", "，", ";", ",", "、"):
        cut = window.rfind(mark)
        if cut >= limit // 2:
            return window[: cut + 1].rstrip("，、；,;")
    return window.rstrip() + "…"


def headline_for(entity: CanonicalEntity, facts: list[FactRecord]) -> str:
    """从实体的事实里挑一句最能说明它的，用于世界概况。

    同一谓词下可能有多条（跨章节），先挑像「定义」的那条 ——
    否则会出现「十字禁卫军：本章出动十二个师团」这种把某章战况当成组织介绍的情况。
    """
    buckets: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts:
        buckets[fact.predicate].append(fact)

    def best(candidates: list[FactRecord]) -> FactRecord:
        def score(fact: FactRecord) -> tuple[int, int]:
            definitional = any(m in fact.value for m in _DEFINITIONAL_MARKERS)
            long_enough = len(fact.value) >= 10
            return (int(definitional) + int(long_enough), -len(fact.value))

        return max(candidates, key=score)

    for predicate in _HEADLINE_PREDICATES:
        if buckets.get(predicate):
            return clip_at_sentence(best(buckets[predicate]).value)
    for predicate in sorted(buckets):
        return clip_at_sentence(best(buckets[predicate]).value)
    return ""


def _render_facts(
    facts: list[FactRecord],
    *,
    with_sources: bool,
    excluded_fact_ids: frozenset[str] | set[str] = frozenset(),
) -> str:
    """把原子事实渲染成条目正文。只取 review_status=accepted 的 canon 事实。

    `excluded_fact_ids` 来自语义支持校验：判定为 `contradicted` /
    `insufficient_evidence` 的事实不进正文，但**保留**在 canonical 数据里。
    """
    buckets: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts:
        if fact.review_status != "accepted" or fact.fact_type != "canon_fact":
            continue
        if fact.fact_id in excluded_fact_ids:
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
    excluded_fact_ids: frozenset[str] | set[str] = frozenset(),
) -> list[PlannedEntry]:
    """为**有已校验事实**的实体规划世界书条目。

    一条 canon 事实都没有的实体（「玩具熊」「自闭症」这类顺带提到的名词）会被跳过 ——
    它们只能渲染成「item：玩具熊」这种零信息空壳，占触发预算却毫无帮助。
    被跳过的名单由 `entities_without_facts` 给出并写进报告，不是静默丢弃。

    有事实的实体**不按体量裁剪**，重要性只体现在 `priority` 上。

    `start_chapter` 非空时只使用该章节及之前的事实 —— **严格起始点导出**。
    这不是加一句「别看后面」，而是后面的事实根本不出现在条目正文里。
    """
    if start_chapter is not None or excluded_fact_ids:
        facts = [
            f
            for f in facts_upto_chapter(facts, start_chapter)
            if f.fact_id not in excluded_fact_ids
        ]
    by_entity = _facts_by_entity(entities, facts)

    entries: list[PlannedEntry] = []
    for entity in sorted(entities, key=lambda e: (-e.evidence_count, e.canonical_name)):
        own_facts = by_entity.get(entity.id, [])
        qualifies, _reason = entry_qualification(entity, own_facts)
        if not qualifies:
            continue

        runtime = _render_facts(
            own_facts, with_sources=False, excluded_fact_ids=excluded_fact_ids
        )
        if not runtime.strip():
            # 事实值全为空串之类的边界情况 —— 宁可不出条目，也不产出空条目
            continue
        canonical = _render_facts(own_facts, with_sources=True)
        primary, secondary = _entity_keys(entity)

        flags: list[str] = []
        if len(own_facts) < MIN_ENTITY_FACTS:
            flags.append(
                f"内容偏薄：只在 {len(entity.appearance_chapters)} 个章节出现但仅 {len(own_facts)} 条事实，"
                "疑似抽取遗漏，建议补抽"
            )
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


def plan_character_index(
    entities: list[CanonicalEntity], *, start_chapter: int | None = None
) -> PlannedEntry | None:
    """常驻的紧凑人物索引，让模型知道世界里有谁。

    `start_chapter` 非空时只列**在该章节之前已经出场**的人物。
    严格起始点下把还没登场的人列进索引本身就是剧透（名字本身就是信息）。
    """
    characters = [e for e in entities if e.kind == "character"]
    if start_chapter is not None:
        characters = [
            e
            for e in characters
            if e.first_appearance_chapter is not None
            and e.first_appearance_chapter <= start_chapter
        ]
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
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    *,
    start_chapter: int | None = None,
) -> PlannedEntry | None:
    """常驻的世界概况。

    这才是「概括这个世界」的地方：按势力/地点/核心设定分组，每组挑几个最有
    证据的实体各配**一句**来自原著的说明，其余只列名字。
    早先的实现只输出「地点：A、B、C」这种名字清单，信息量接近零。

    `start_chapter` 非空时说明句只从该章节之前的事实里挑 ——
    否则「世界概况」会用后面的设定介绍一个此刻还不存在的东西。
    """
    by_entity = _facts_by_entity(entities, facts, start_chapter=start_chapter)
    sections: list[tuple[str, str]] = [
        ("faction", "势力"),
        ("place", "地点"),
        ("concept", "核心设定"),
        ("ability", "能力与技术"),
        ("item", "重要物品"),
    ]

    lines: list[str] = []
    name_only: list[str] = []

    for kind, label in sections:
        pool = [e for e in entities if e.kind == kind]
        with_facts = sorted(
            (e for e in pool if by_entity.get(e.id)), key=lambda e: -e.evidence_count
        )
        limit = OVERVIEW_TOP_PER_KIND.get(kind, 4)
        picked = with_facts[:limit]

        if picked:
            lines.append(f"{label}：")
            for entity in picked:
                headline = headline_for(entity, by_entity[entity.id])
                if headline:
                    lines.append(f"　· {entity.canonical_name}：{headline}")
                else:
                    lines.append(f"　· {entity.canonical_name}")

        rest = [e.canonical_name for e in pool if not by_entity.get(e.id)]
        rest += [e.canonical_name for e in with_facts[limit:]]
        name_only.extend(rest)

    if not lines and not name_only:
        return None

    body = "\n".join(lines)
    if name_only:
        extra = "、".join(sorted(dict.fromkeys(name_only))[:OVERVIEW_NAME_ONLY_LIMIT])
        if extra:
            body += f"\n其它提及名称（无独立设定）：{extra}"

    flags: list[str] = []
    if not lines:
        flags.append("没有任何实体带已校验事实，概况退化为名称清单")

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
        quality_flags=flags,
    )


def filter_for_start_chapter(
    entries: list[PlannedEntry], start_chapter: int | None
) -> tuple[list[PlannedEntry], list[PlannedEntry]]:
    """按起始章节切分条目：`(可用, 被屏蔽)`。

    只屏蔽 **`chapter_gated=True`** 的条目（即剧情类）。人物、地点、世界概况
    在世界里本来就存在，与"它在故事里第几章才登场"是两回事 —— 早先按首次出场
    章节过滤，会让"从第 1 章开始"的世界书只剩十几个条目，世界是空的。

    被屏蔽的条目**不删除**，只是不进入该起始点的活动上下文。
    """
    if start_chapter is None:
        return entries, []
    available: list[PlannedEntry] = []
    blocked: list[PlannedEntry] = []
    for entry in entries:
        gated = entry.chapter_gated and entry.valid_from_chapter is not None
        if gated and entry.valid_from_chapter > start_chapter:
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
