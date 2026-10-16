"""实体归一与角色档案汇总。

读 `extraction/*.json`，产出 `canonical/` 下的实体表、合并判定、复核队列与报告。

**默认不丢任何实体**：低置信度候选进复核队列，而不是被裁剪或按体量排序丢弃。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..extract.schema import (
    ChunkExtraction,
    EventRecord,
    FactRecord,
    MentionRecord,
    RelationRecord,
    SourceRef,
)
from .entities import (
    CanonicalEntity,
    MergeDecision,
    NameCluster,
    ResolutionResult,
    alias_evidence,
    alias_links,
    cluster_mentions,
    normalize_name,
    propose_merges,
)

CANONICAL_DIR = "canonical"
ENTITIES_NAME = "entities.json"
DECISIONS_NAME = "merge_decisions.json"
REVIEW_NAME = "review_queue.json"
SUMMARY_NAME = "entity_resolution.md"


class ResolutionError(RuntimeError):
    """归一阶段的致命错误。"""


class _UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self._parent = {k: k for k in keys}

    def find(self, key: str) -> str:
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self._parent[b] = a


def load_extractions(run_dir: str | Path) -> list[ChunkExtraction]:
    directory = Path(run_dir) / "extraction"
    if not directory.is_dir():
        raise ResolutionError(f"该 run 没有 extraction 目录：{directory}，请先跑 extract。")
    items: list[ChunkExtraction] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        items.append(ChunkExtraction.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    if not items:
        raise ResolutionError(f"extraction 目录里没有任何分块结果：{directory}")
    return items


def _flatten(extractions: list[ChunkExtraction]):
    mentions: list[MentionRecord] = []
    facts: list[FactRecord] = []
    events: list[EventRecord] = []
    relations: list[RelationRecord] = []
    for item in extractions:
        mentions.extend(item.mentions)
        facts.extend(item.facts)
        events.extend(item.events)
        relations.extend(item.relations)
    return mentions, facts, events, relations


def _build_entity(
    group_keys: list[str],
    clusters: list[NameCluster],
    *,
    entity_id: str,
    mentions: list[MentionRecord],
    facts: list[FactRecord],
    events: list[EventRecord],
    relations: list[RelationRecord],
) -> CanonicalEntity:
    by_key = {c.key: c for c in clusters}
    group = [by_key[k] for k in group_keys if k in by_key]
    group_set = set(group_keys)

    name_counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    chapters: set[int] = set()
    mention_ids: list[str] = []
    refs: list[SourceRef] = []

    for cluster in group:
        for mention in mentions:
            if mention.mention_id in cluster.mention_ids:
                name_counts[mention.name] += 1
                kinds[mention.kind] += 1
                chapters.add(mention.chapter_index)
                mention_ids.append(mention.mention_id)
                refs.extend(mention.source_refs[:1])

    if not name_counts:
        raise ResolutionError(f"聚类 {group_keys} 没有任何提及")

    # canonical 取出现次数最多的写法，次数相同取更长的（通常更完整）
    canonical = max(name_counts, key=lambda n: (name_counts[n], len(n)))
    aliases = sorted(n for n in name_counts if n != canonical)
    kind = kinds.most_common(1)[0][0]

    def key_of(text: str) -> str:
        return normalize_name(text)

    entity_facts = [f for f in facts if key_of(f.subject) in group_set]
    entity_events = [
        e for e in events if any(key_of(p) in group_set for p in e.participants)
    ]
    entity_relations = [
        r for r in relations if key_of(r.from_entity) in group_set or key_of(r.to_entity) in group_set
    ]

    for record in [*entity_facts[:3], *entity_events[:2], *entity_relations[:2]]:
        refs.extend(record.source_refs[:1])

    evidence_count = (
        len(mention_ids) + 2 * len(entity_facts) + 3 * len(entity_events) + len(entity_relations)
    )

    return CanonicalEntity(
        id=entity_id,
        kind=kind,
        canonical_name=canonical,
        aliases=aliases,
        appearance_chapters=sorted(chapters),
        first_appearance_chapter=min(chapters) if chapters else None,
        mention_ids=mention_ids,
        fact_ids=[f.fact_id for f in entity_facts],
        relation_ids=[r.relation_id for r in entity_relations],
        event_ids=[e.event_id for e in entity_events],
        evidence_count=evidence_count,
        importance=0.0,  # 稍后统一归一化
        source_refs=refs[:6],
        review_status="accepted",
        merged_from=sorted(group_keys),
    )


def resolve(run_dir: str | Path) -> ResolutionResult:
    run_path = Path(run_dir)
    extractions = load_extractions(run_path)
    mentions, facts, events, relations = _flatten(extractions)

    if not mentions:
        raise ResolutionError("抽取结果里没有任何实体提及，无法做归一。")

    clusters, excluded = cluster_mentions(mentions)
    links, alias_review = alias_links(clusters, mentions)

    union = _UnionFind([c.key for c in clusters])
    merged_pairs: list[tuple[str, str]] = []
    for owner, targets in links.items():
        for target in targets:
            # 只在「当前还不在同一组」时记录，否则会把已经合并的对重复记一遍
            if union.find(owner) != union.find(target):
                union.union(owner, target)
                merged_pairs.append((owner, target))

    groups: dict[str, list[str]] = {}
    for cluster in clusters:
        groups.setdefault(union.find(cluster.key), []).append(cluster.key)

    entity_id_by_key: dict[str, str] = {}
    entities: list[CanonicalEntity] = []
    ordered_groups = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    for index, group_keys in enumerate(ordered_groups):
        entity_id = f"ent_{index + 1:04d}"
        entity = _build_entity(
            sorted(group_keys),
            clusters,
            entity_id=entity_id,
            mentions=mentions,
            facts=facts,
            events=events,
            relations=relations,
        )
        entities.append(entity)
        for key in group_keys:
            entity_id_by_key[key] = entity_id

    top = max((e.evidence_count for e in entities), default=0) or 1
    for entity in entities:
        entity.importance = round(entity.evidence_count / top, 4)

    decisions = propose_merges(clusters)
    # 已被别名关系合并掉的候选不必再进复核队列
    review_queue = [
        d
        for d in decisions
        if len({entity_id_by_key.get(k) for k in d.candidate_entity_ids}) > 1
    ]
    # 别名关系里不够格自动合并的，连同姓名近似的候选一起进复核队列
    review_queue.extend(alias_review)

    # 显式别名合并也要留下可追溯记录
    alias_decisions: list[MergeDecision] = []
    for owner, target in merged_pairs:
        if entity_id_by_key.get(owner) != entity_id_by_key.get(target):
            continue  # 已经被并进同一个实体，无需单独记录
        alias_decisions.append(
            MergeDecision(
                candidate_names=[owner, target],
                candidate_entity_ids=[owner, target],
                match_signals=["抽取结果显示为彼此别名（有原文依据）"],
                confidence=0.9,
                decision="merge",
                evidence_refs=[],
            )
        )

    result = ResolutionResult(
        entities=entities,
        decisions=[*alias_decisions, *decisions],
        review_queue=review_queue,
        excluded_role_nouns=sorted({m.name for m in excluded}),
        alias_merged={owner: targets for owner, targets in links.items()},
        alias_evidence={
            owner: {target: len(chunks) for target, chunks in targets.items()}
            for owner, targets in alias_evidence(clusters, mentions).items()
        },
    )

    _write_outputs(run_path, result, extractions, facts, events, relations)
    return result


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_outputs(
    run_dir: Path,
    result: ResolutionResult,
    extractions: list[ChunkExtraction],
    facts: list[FactRecord],
    events: list[EventRecord],
    relations: list[RelationRecord],
) -> None:
    out = run_dir / CANONICAL_DIR
    _write_json(out / ENTITIES_NAME, [e.model_dump(mode="json") for e in result.entities])
    _write_json(out / DECISIONS_NAME, [d.model_dump(mode="json") for d in result.decisions])
    _write_json(out / REVIEW_NAME, [d.model_dump(mode="json") for d in result.review_queue])
    _write_json(out / "facts.json", [f.model_dump(mode="json") for f in facts])
    _write_json(out / "events.json", [e.model_dump(mode="json") for e in events])
    _write_json(out / "relations.json", [r.model_dump(mode="json") for r in relations])

    by_kind: Counter[str] = Counter(e.kind for e in result.entities)
    chapter_count = len({c.chapter_index for c in extractions})
    accepted_facts = sum(1 for f in facts if f.review_status == "accepted")
    canon_facts = sum(1 for f in facts if f.fact_type == "canon_fact" and f.review_status == "accepted")

    lines = [
        "# 实体归一与角色档案报告",
        "",
        f"- run_id：`{run_dir.name}`",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- 覆盖章节：{chapter_count}",
        "",
        "## 实体",
        "",
        f"- 实体总数：{len(result.entities)}",
        f"- 已合并（别名依据）：{sum(1 for d in result.decisions if d.decision == 'merge')}",
        f"- 待人工复核的合并候选：{len(result.review_queue)}",
        f"- 被排除的泛称（不是专有实体）：{len(result.excluded_role_nouns)}",
        "",
        "| 类别 | 数量 |",
        "|---|---|",
    ]
    for kind, count in by_kind.most_common():
        lines.append(f"| {kind} | {count} |")

    lines += [
        "",
        "## 事实",
        "",
        f"- 原子事实总数：{len(facts)}",
        f"- 已接受：{accepted_facts}",
        f"- 其中 canon_fact：{canon_facts}",
        f"- 事件：{len(events)}　关系：{len(relations)}",
        "",
        "## 主要实体（按证据量）",
        "",
        "| 实体 | 类别 | 别名数 | 出现章节数 | 事实 | 事件 | 证据量 |",
        "|---|---|---|---|---|---|---|",
    ]
    for entity in sorted(result.entities, key=lambda e: -e.evidence_count)[:40]:
        lines.append(
            f"| {entity.canonical_name} | {entity.kind} | {len(entity.aliases)} | "
            f"{len(entity.appearance_chapters)} | {len(entity.fact_ids)} | "
            f"{len(entity.event_ids)} | {entity.evidence_count} |"
        )

    if result.alias_evidence:
        lines += [
            "",
            "## 别名关系证据（前 30 条，按断言它的分块数排序）",
            "",
            "> 断言数高但未自动合并的，多半是类别冲突或抽取器把称号与实物混为一谈；",
            "> 这些**没有**被合并，需人工判断。",
            "",
            "| 主体 | 被记为别名 | 断言分块数 |",
            "|---|---|---|",
        ]
        pairs = [
            (owner, target, count)
            for owner, targets in result.alias_evidence.items()
            for target, count in targets.items()
        ]
        for owner, target, count in sorted(pairs, key=lambda x: -x[2])[:30]:
            lines.append(f"| {owner} | {target} | {count} |")

    if result.review_queue:
        lines += [
            "",
            "## 待人工复核的合并候选",
            "",
            "> 这些**没有**被自动合并 —— 名字相似不足以证明是同一个实体。",
            "",
        ]
        for decision in result.review_queue[:50]:
            lines.append(
                f"- {' / '.join(decision.candidate_names)}"
                f"（置信度 {decision.confidence}）：{'; '.join(decision.match_signals)}"
            )

    if result.excluded_role_nouns:
        lines += [
            "",
            "## 被排除的泛称",
            "",
            f"{'、'.join(result.excluded_role_nouns[:60])}",
            "",
            "> 这些是「少年」「士兵」这类角色名词，不是专有实体，未建成独立角色。",
        ]

    lines += ["", "> 本报告不含小说原文。", ""]
    (run_dir / "reports" / SUMMARY_NAME).write_text("\n".join(lines), encoding="utf-8")
