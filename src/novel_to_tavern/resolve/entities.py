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


def alias_links(clusters: list[NameCluster], mentions: list[MentionRecord]) -> dict[str, list[str]]:
    """找出**有原文依据**的别名关系：某聚类里显式列出了另一个聚类的名字。

    返回 `{cluster_key: [被并入的 cluster_key, ...]}`。
    """
    by_key = {c.key: c for c in clusters}
    links: dict[str, list[str]] = {}

    for mention in mentions:
        owner = normalize_name(mention.name)
        if owner not in by_key:
            continue
        for alias in mention.aliases:
            target = normalize_name(alias)
            if target and target != owner and target in by_key:
                links.setdefault(owner, [])
                if target not in links[owner]:
                    links[owner].append(target)

    return links


class ResolutionResult(BaseModel):
    entities: list[CanonicalEntity]
    decisions: list[MergeDecision]
    review_queue: list[MergeDecision]
    excluded_role_nouns: list[str]
    alias_merged: dict[str, list[str]]
