"""实体归一：把跨章节的提及聚成 canonical 实体。

核心约束（AGENTS.md / DATA_MODEL.md §3）：
**绝不可仅因为名字相似就自动合并。** 低置信度的候选进入人工复核队列，
默认保留为两个实体而不是赌一把。

归一的判定只有两类是"自动"的：
1. 规范化后字面完全相同；
2. 抽取结果里显式标注为彼此的别名（原文有"又名/化名/称号"依据）。
其余（字面包含、编辑距离相近）一律 `needs_review`，不自动合并。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import EntityKind, MentionRecord, SourceRef

#: 泛称/角色名词，不是专有实体，不该建成独立角色。
ROLE_NOUNS = frozenset(
    {
        "他", "她", "它", "他们", "她们", "它们", "我们", "你们", "我", "你",
        "少年", "少女", "孩子", "老人", "老者", "男人", "女人", "众人", "人们",
        "士兵", "骑士", "卫兵", "仆人", "侍从", "商人", "船老大", "路人",
        "对方", "那人", "此人", "有人", "所有人", "每个人", "大家",
        "父亲", "母亲", "哥哥", "姐姐", "弟弟", "妹妹", "皇帝", "国王", "女王",
        "教皇", "神父", "修女", "医生", "军官", "将军", "队长", "首领", "王",
    }
)

_PUNCT = re.compile(r"[\s·・．.、,，。！!？?：:；;「」『』《》〈〉（）()\[\]“”\"'‘’—\-~～]+")


class MergeDecision(BaseModel):
    """一次合并判定的完整记录，可追溯、可回滚。"""

    candidate_names: list[str]
    candidate_entity_ids: list[str]
    match_signals: list[str]
    confidence: float
    decision: Literal["merge", "keep_separate", "needs_review"]
    evidence_refs: list[SourceRef] = Field(default_factory=list)


class CanonicalEntity(BaseModel):
    id: str
    kind: EntityKind
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    appearance_chapters: list[int] = Field(default_factory=list)
    first_appearance_chapter: int | None = None
    mention_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    importance: float = 0.0
    source_refs: list[SourceRef] = Field(default_factory=list)
    review_status: Literal["accepted", "needs_review"] = "accepted"
    merged_from: list[str] = Field(default_factory=list)


def normalize_name(name: str) -> str:
    """归一化用于**比对**的名字。不影响展示用的 canonical_name。"""
    text = unicodedata.normalize("NFKC", name.strip())
    text = _PUNCT.sub("", text)
    return text.casefold()


def is_role_noun(name: str) -> bool:
    return normalize_name(name) in {normalize_name(n) for n in ROLE_NOUNS}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


class NameCluster(BaseModel):
    key: str
    names: list[str]
    mention_ids: list[str]
    kinds: list[EntityKind]
    source_refs: list[SourceRef] = Field(default_factory=list)


def cluster_mentions(mentions: list[MentionRecord]) -> tuple[list[NameCluster], list[MentionRecord]]:
    """按规范化名字聚类。返回 `(聚类结果, 被排除的泛称提及)`。

    聚类只做字面相同的合并 —— 这是**唯一**允许无人工介入的合并依据。
    """
    clusters: dict[str, NameCluster] = {}
    excluded: list[MentionRecord] = []

    for mention in mentions:
        if is_role_noun(mention.name):
            excluded.append(mention)
            continue
        key = normalize_name(mention.name)
        if not key:
            excluded.append(mention)
            continue
        cluster = clusters.setdefault(
            key,
            NameCluster(key=key, names=[], mention_ids=[], kinds=[]),
        )
        if mention.name not in cluster.names:
            cluster.names.append(mention.name)
        cluster.mention_ids.append(mention.mention_id)
        if mention.kind not in cluster.kinds:
            cluster.kinds.append(mention.kind)
        if mention.source_refs and len(cluster.source_refs) < 3:
            cluster.source_refs.append(mention.source_refs[0])

    return list(clusters.values()), excluded


def propose_merges(clusters: list[NameCluster]) -> list[MergeDecision]:
    """在聚类之间提出合并候选。

    只有"字面包含"与"编辑距离 1"两类会被提出，且**一律 needs_review**，
    绝不自动合并。真正自动合并的时机在 `apply_decisions`，且只针对显式别名。
    """
    decisions: list[MergeDecision] = []
    ordered = sorted(clusters, key=lambda c: len(c.key), reverse=True)

    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            if left.key == right.key:
                continue
            signal: str | None = None
            confidence = 0.0

            if len(right.key) >= 2 and right.key in left.key:
                signal = f"字面包含：{right.names[0]!r} 是 {left.names[0]!r} 的一部分"
                confidence = 0.45
            elif min(len(left.key), len(right.key)) >= 3 and _levenshtein(left.key, right.key) == 1:
                signal = f"编辑距离为 1：{left.names[0]!r} / {right.names[0]!r}"
                confidence = 0.4

            if signal is None:
                continue

            decisions.append(
                MergeDecision(
                    candidate_names=[*left.names, *right.names],
                    candidate_entity_ids=[left.key, right.key],
                    match_signals=[signal],
                    confidence=confidence,
                    decision="needs_review",
                    evidence_refs=[*left.source_refs[:1], *right.source_refs[:1]],
                )
            )
            break  # 每个 key 只提一个最可疑的候选，避免 O(n²) 结果爆炸

    return decisions


#: 自动合并要求别名关系至少被这么多个**独立分块**断言过。
#: 抽取器单次声称"X 又名 Y"不足以证明；重复出现才作为自动合并依据。
MIN_ALIAS_CHUNKS = 2

#: 兼容的实体类别。`character` 与其余类别互斥 —— 把一个人和一个组织/物品
#: 当成同一实体几乎一定是抽取错误。
_CHARACTER = "character"


def alias_evidence(clusters: list[NameCluster], mentions: list[MentionRecord]) -> dict[str, dict[str, set[str]]]:
    """收集别名关系的证据：`{owner: {alias: {断言过它的 chunk_id, ...}}}`。"""
    by_key = {c.key: c for c in clusters}
    evidence: dict[str, dict[str, set[str]]] = {}

    for mention in mentions:
        owner = normalize_name(mention.name)
        if owner not in by_key:
            continue
        for alias in mention.aliases:
            target = normalize_name(alias)
            if not target or target == owner or target not in by_key:
                continue
            evidence.setdefault(owner, {}).setdefault(target, set()).add(mention.chunk_id)

    return evidence


def declared_aliases(
    clusters: list[NameCluster], mentions: list[MentionRecord]
) -> dict[str, list[str]]:
    """只作为「别名」出现过、自己从没被单独提及的名字。

    `alias_links` 只能处理**两侧都是已知聚类**的情况 —— 它要比较类别是否兼容。
    但现实里大量称号只以别名的形式出现：抽取器说「凌霜」又名「霜姐」，
    而「霜姐」从来没有作为独立提及出现过。那些称号如果不落到实体上，
    就永远不会成为触发词，「霜姐是谁？」这种问法会漏触发。

    门槛与自动合并一致：同一个别名关系要被 **≥ `MIN_ALIAS_CHUNKS` 个独立分块**
    断言过。类别无从比较，所以不做类别检查 —— 这是个小让步，换来的
    是「别名可触发」这条质量门禁真的成立。
    """
    by_key = {c.key: c for c in clusters}
    collected: dict[str, dict[str, set[str]]] = {}

    for mention in mentions:
        owner = normalize_name(mention.name)
        if owner not in by_key:
            continue
        for alias in mention.aliases:
            target = normalize_name(alias)
            if not target or target == owner or target in by_key:
                continue
            collected.setdefault(owner, {}).setdefault(alias, set()).add(mention.chunk_id)

    return {
        owner: qualified
        for owner, targets in collected.items()
        if (qualified := sorted(
            alias for alias, chunks in targets.items() if len(chunks) >= MIN_ALIAS_CHUNKS
        ))
    }


def kinds_are_compatible(left: NameCluster, right: NameCluster) -> bool:
    """两侧类别是否兼容。人物与非人物一律不兼容。"""
    left_is_char = _CHARACTER in left.kinds
    right_is_char = _CHARACTER in right.kinds
    if left_is_char != right_is_char:
        return False
    return bool(set(left.kinds) & set(right.kinds))


def alias_links(
    clusters: list[NameCluster], mentions: list[MentionRecord]
) -> tuple[dict[str, list[str]], list[MergeDecision]]:
    """把别名关系分成「可自动合并」与「需人工复核」两类。

    只有同时满足两条才自动合并：
    1. 两侧实体类别兼容（人物与非人物不合并）；
    2. 该别名关系被 **≥ `MIN_ALIAS_CHUNKS` 个独立分块**断言过。

    其余一律进复核队列。抽取器只在一处顺口提到的别名不足以据此合并实体。
    """
    by_key = {c.key: c for c in clusters}
    evidence = alias_evidence(clusters, mentions)

    accepted: dict[str, list[str]] = {}
    review: list[MergeDecision] = []

    for owner, targets in evidence.items():
        for target, chunk_ids in targets.items():
            left, right = by_key[owner], by_key[target]
            if not kinds_are_compatible(left, right):
                review.append(
                    MergeDecision(
                        candidate_names=[*left.names, *right.names],
                        candidate_entity_ids=[owner, target],
                        match_signals=[
                            f"抽取器在 {len(chunk_ids)} 个分块里把 {right.names[0]!r} 记为 "
                            f"{left.names[0]!r} 的别名，但类别不兼容"
                            f"（{'/'.join(left.kinds)} vs {'/'.join(right.kinds)}）"
                        ],
                        confidence=0.2,
                        decision="needs_review",
                        evidence_refs=[*left.source_refs[:1], *right.source_refs[:1]],
                    )
                )
                continue
            if len(chunk_ids) < MIN_ALIAS_CHUNKS:
                review.append(
                    MergeDecision(
                        candidate_names=[*left.names, *right.names],
                        candidate_entity_ids=[owner, target],
                        match_signals=[
                            f"抽取器把 {right.names[0]!r} 记为 {left.names[0]!r} 的别名，"
                            f"但只在 {len(chunk_ids)} 个分块里出现，"
                            f"未达 {MIN_ALIAS_CHUNKS} 个独立断言的自动合并门槛"
                        ],
                        confidence=0.35,
                        decision="needs_review",
                        evidence_refs=[*left.source_refs[:1], *right.source_refs[:1]],
                    )
                )
                continue
            accepted.setdefault(owner, []).append(target)

    return accepted, review


class ResolutionResult(BaseModel):
    entities: list[CanonicalEntity]
    decisions: list[MergeDecision]
    review_queue: list[MergeDecision]
    excluded_role_nouns: list[str]
    alias_merged: dict[str, list[str]]
    alias_evidence: dict[str, dict[str, int]] = Field(default_factory=dict)
