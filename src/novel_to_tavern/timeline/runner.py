"""时间线、知识边界与世界书规划的执行器（Phase 4）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..extract.schema import EventRecord, FactRecord, RelationRecord
from ..resolve.entities import CanonicalEntity
from .build import (
    ContradictionFinding,
    KnowledgeItem,
    LeakageFinding,
    TimelineEvent,
    build_knowledge,
    build_timeline,
    check_leakage,
    find_contradictions,
    knowledge_summary,
    relation_timeline,
)
from .worldbible import (
    MIN_ENTITY_CHAPTERS,
    MIN_ENTITY_FACTS,
    PlannedEntry,
    filter_for_start_chapter,
    entities_skipped_from_worldbook,
    plan_character_index,
    plan_entity_entries,
    plan_world_overview,
    summarize_plan,
)

TIMELINE_NAME = "timeline.json"
KNOWLEDGE_NAME = "knowledge.json"
LEAKAGE_NAME = "leakage.json"
CONTRADICTIONS_NAME = "contradictions.json"
RELATIONS_NAME = "relation_timeline.json"
PLAN_NAME = "plan.json"
SUMMARY_NAME = "timeline_report.md"


class TimelineError(RuntimeError):
    """时间线阶段的致命错误。"""


def _read_json(path: Path):
    if not path.is_file():
        raise TimelineError(f"缺少上游产物：{path}，请先跑 resolve。")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(run_dir: str | Path, *, start_chapter: int | None = None) -> dict:
    run_path = Path(run_dir)
    canonical = run_path / "canonical"

    entities = [
        CanonicalEntity.model_validate(item) for item in _read_json(canonical / "entities.json")
    ]
    facts = [FactRecord.model_validate(item) for item in _read_json(canonical / "facts.json")]
    events = [EventRecord.model_validate(item) for item in _read_json(canonical / "events.json")]
    relations = [
        RelationRecord.model_validate(item) for item in _read_json(canonical / "relations.json")
    ]

    accepted_facts = [f for f in facts if f.review_status == "accepted"]
    accepted_events = [e for e in events if e.review_status == "accepted"]

    timeline = build_timeline(accepted_events)
    knowledge = build_knowledge(accepted_events, accepted_facts)
    contradictions = find_contradictions(facts)
    relation_changes = relation_timeline(relations)

    total_chapters = max((e.chapter_index for e in [*accepted_events, *accepted_facts]), default=0) + 1
    leakage_reports = {
        "start_at_beginning": check_leakage(start_chapter=0, events=accepted_events, facts=accepted_facts),
        "start_at_end": check_leakage(
            start_chapter=total_chapters - 1, events=accepted_events, facts=accepted_facts
        ),
    }

    entries: list[PlannedEntry] = []
    overview = plan_world_overview(entities, facts)
    if overview:
        entries.append(overview)
    index_entry = plan_character_index(entities)
    if index_entry:
        entries.append(index_entry)
    entries.extend(plan_entity_entries(entities, facts))
    skipped_entities = entities_skipped_from_worldbook(entities, facts)
    # 章节事件条目已移除：它们与「剧情主线」内容重复，且触发词取的是该章在场人物，
    # 主要人物出场上百章 → 一句话会同时命中上百条（实测 117 条 ≈ 6 万 token）。

    available, blocked = filter_for_start_chapter(entries, start_chapter)
    plan_stats = summarize_plan(available)

    _write_json(canonical / TIMELINE_NAME, [e.model_dump(mode="json") for e in timeline])
    _write_json(
        canonical / KNOWLEDGE_NAME,
        {name: [item.model_dump(mode="json") for item in items] for name, items in knowledge.items()},
    )
    _write_json(
        canonical / LEAKAGE_NAME,
        {key: [f.model_dump(mode="json") for f in findings] for key, findings in leakage_reports.items()},
    )
    _write_json(canonical / CONTRADICTIONS_NAME, [c.model_dump(mode="json") for c in contradictions])
    _write_json(
        canonical / RELATIONS_NAME,
        {key: [r.model_dump(mode="json") for r in items] for key, items in relation_changes.items()},
    )
    _write_json(run_path / "worldbook" / PLAN_NAME, [e.model_dump(mode="json") for e in available])

    report = _render_report(
        run_path,
        timeline=timeline,
        knowledge=knowledge,
        contradictions=contradictions,
        leakage_reports=leakage_reports,
        entries=available,
        blocked=blocked,
        skipped_entities=skipped_entities,
        plan_stats=plan_stats,
        start_chapter=start_chapter,
        total_chapters=total_chapters,
    )
    (run_path / "reports" / SUMMARY_NAME).write_text(report, encoding="utf-8")

    return {
        "timeline": timeline,
        "knowledge": knowledge,
        "contradictions": contradictions,
        "leakage": leakage_reports,
        "entries": available,
        "blocked_entries": blocked,
        "skipped_entities": skipped_entities,
        "plan_stats": plan_stats,
        "total_chapters": total_chapters,
    }


def _render_report(
    run_dir: Path,
    *,
    timeline: list[TimelineEvent],
    knowledge: dict[str, list[KnowledgeItem]],
    contradictions: list[ContradictionFinding],
    leakage_reports: dict[str, list[LeakageFinding]],
    entries: list[PlannedEntry],
    blocked: list[PlannedEntry],
    skipped_entities: list[tuple[CanonicalEntity, str]],
    plan_stats: dict,
    start_chapter: int | None,
    total_chapters: int,
) -> str:
    lines = [
        "# 时间线、知识边界与世界书规划报告",
        "",
        f"- run_id：`{run_dir.name}`",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- 覆盖章节：{total_chapters}",
        "",
        "## 时间线",
        "",
        f"- 事件数：{len(timeline)}",
        f"- 有明确相对时间表述的事件：{sum(1 for e in timeline if e.relative_time)}",
        f"- 被赋予绝对时间的事件：{sum(1 for e in timeline if e.occurred_at)}"
        "（**始终为 0**：原文未给出绝对时间时本项目不推算）",
        "",
        "## 知识边界",
        "",
        f"- 有知识记录的实体：{knowledge_summary(knowledge)['entities']}",
        f"- 知识记录总数：{knowledge_summary(knowledge)['total']}",
        f"- 其中**候补**（结构上可能知道，原文未确立）：{knowledge_summary(knowledge)['candidates']}",
        "",
        "| 状态 | 条数 | 含义 |",
        "|---|---|---|",
    ]
    _STATUS_MEANING = {
        "knows": "**已确立**：该事实的主语就是它自己",
        "believes": "抽取标注为角色信念",
        "heard_rumor": "抽取标注为传闻",
        "suspects": "抽取标注为推断",
        "does_not_know": "明确不知道",
        "unknown": "原文未确立 —— 默认值",
    }
    stats = knowledge_summary(knowledge)
    for status in ("knows", "believes", "suspects", "heard_rumor", "does_not_know", "unknown"):
        if stats.get(status):
            lines.append(f"| `{status}` | {stats[status]} | {_STATUS_MEANING[status]} |")
    lines += [
        "",
        "> ⚠️ **在场不等于知晓。** 事件参与者只记为**候补**（`candidate`，状态 `unknown`，"
        "`acquired_at_chapter` 留空）：它可能在场，但也可能没看见、没听懂、"
        "或者是在后面的章节里通过信件、报告、传闻、他人转述或自行推断才知道的。",
        "> 本模型**只**把「事实主语是角色自己」这一类当成已确立的知识。",
        "> **没有**采用「事件发生后所有人都知道」这种假设。",
        "> 候补占多数是**正常且诚实**的，不是缺陷。",
        "",
        "> `revealed_at_chapter`（读者看到它的章节）与 `acquired_at_chapter`"
        "（角色可能知道的章节）是两个不同的量，不要混用。",
        "",
        "## 冲突",
        "",
        f"- 同一主语同一谓词出现多值的情况：{len(contradictions)}",
        "",
    ]
    if contradictions:
        lines += ["| 主语 | 谓词 | 取值 | 章节 |", "|---|---|---|---|"]
        for item in contradictions[:30]:
            values = "、".join(item.values[:4])
            chapters = "、".join(str(c + 1) for c in item.chapter_indexes[:6])
            lines.append(f"| {item.subject} | {item.predicate} | {values} | {chapters} |")
        lines.append("")
        lines.append("> 冲突只报告，不自动选一方覆盖。")
        lines.append("")

    lines += [
        "## 未来信息泄漏检查",
        "",
        "从两个起始点分别检查「起始章节之后才出现的内容」有多少：",
        "",
        "| 起始点 | 起始章节 | 被判为未来的条目数 |",
        "|---|---|---|",
        f"| 从故事开头开始 | 第 1 章 | {len(leakage_reports['start_at_beginning'])} |",
        f"| 从故事结尾之后开始 | 第 {total_chapters} 章 | {len(leakage_reports['start_at_end'])} |",
        "",
        "> 这两个数字就是**必须被屏蔽**的内容量：从开头开始时，后面 "
        f"{len(leakage_reports['start_at_beginning'])} 条全部不得进入活动上下文。",
        "> 屏蔽靠条目的 `valid_from_chapter` 实现，源数据不删除。",
        "",
        "## 世界书规划",
        "",
        f"- 规划条目数：{plan_stats['total_entries']}",
        f"- 常驻条目：{plan_stats['always_on_entries']}（约 {plan_stats['always_on_tokens']} token）",
        f"- 触发条目：{plan_stats['triggered_entries']}",
        f"- 全部条目约：{plan_stats['total_tokens']} token",
        f"- 因起始章节设置被屏蔽：{len(blocked)}",
        "",
        "> token 为**粗估**（CJK 约 1 字 1 token，其余约 4 字符 1 token），非具体分词器真实计数。",
        "",
        "| 类别 | 条目数 | 常驻 | 估算 token |",
        "|---|---|---|---|",
    ]
    by_category: dict[str, list[PlannedEntry]] = {}
    for entry in entries:
        by_category.setdefault(entry.category, []).append(entry)
    for category in sorted(by_category, key=lambda c: -len(by_category[c])):
        group = by_category[category]
        lines.append(
            f"| {category} | {len(group)} | {sum(1 for e in group if e.always_on)} | "
            f"{sum(e.estimated_tokens for e in group)} |"
        )

    if skipped_entities:
        lines += [
            "",
            "## 未生成世界书条目的实体",
            "",
            f"共 {len(skipped_entities)} 个实体未生成条目。门槛是「已校验 canon 事实 ≥ "
            f"{MIN_ENTITY_FACTS} 条**或**至少出现在 {MIN_ENTITY_CHAPTERS} 个章节里」，"
            "两者都不满足的只会写出「item：玩具熊」这种零信息空壳。",
            "",
            "> 它们仍保留在 `canonical/entities.json` 里（来源可追溯），"
            "只是不进世界书 —— 不是静默丢弃。",
            "",
        ]
        by_reason: dict[str, list[str]] = {}
        for entity, reason in skipped_entities:
            by_reason.setdefault(reason, []).append(entity.canonical_name)
        for reason in sorted(by_reason, key=lambda k: -len(by_reason[k])):
            names = by_reason[reason]
            preview = "、".join(names[:30]) + ("…" if len(names) > 30 else "")
            lines.append(f"- **{len(names)} 个**（{reason}）：{preview}")

    flagged = [e for e in entries if e.quality_flags]
    if flagged:
        lines += ["", "## 需要人工注意的条目", ""]
        for entry in flagged[:30]:
            lines.append(f"- {entry.title}：{'; '.join(entry.quality_flags)}")

    lines += ["", "> 本报告不含小说原文。", ""]
    return "\n".join(lines)
