"""世界观、时间线与知识边界（Phase 4）。

「事情发生的时间」与「读者/角色知道它的时间」分开建模；
没有明确时间就不编造绝对日期；冲突只报告，不覆盖。
"""

from __future__ import annotations

from .build import (
    ContradictionFinding,
    KnowledgeItem,
    LeakageFinding,
    TimelineEvent,
    build_knowledge,
    build_timeline,
    check_leakage,
    extract_relative_time,
    find_contradictions,
    relation_timeline,
)
from .runner import (
    CONTRADICTIONS_NAME,
    KNOWLEDGE_NAME,
    LEAKAGE_NAME,
    PLAN_NAME,
    SUMMARY_NAME,
    TIMELINE_NAME,
    TimelineError,
    build,
)
from .worldbible import (
    MIN_ENTITY_CHAPTERS,
    MIN_ENTITY_FACTS,
    PlannedEntry,
    clip_at_sentence,
    entities_skipped_from_worldbook,
    entities_skipped_from_worldbook,
    entry_qualification,
    estimate_tokens,
    filter_for_start_chapter,
    headline_for,
    plan_character_index,
    plan_entity_entries,
    plan_world_overview,
    summarize_plan,
)

__all__ = [
    "CONTRADICTIONS_NAME",
    "KNOWLEDGE_NAME",
    "LEAKAGE_NAME",
    "PLAN_NAME",
    "SUMMARY_NAME",
    "TIMELINE_NAME",
    "ContradictionFinding",
    "KnowledgeItem",
    "LeakageFinding",
    "PlannedEntry",
    "TimelineError",
    "TimelineEvent",
    "build",
    "build_knowledge",
    "build_timeline",
    "check_leakage",
    "clip_at_sentence",
    "entities_skipped_from_worldbook",
    "entry_qualification",
    "MIN_ENTITY_CHAPTERS",
    "MIN_ENTITY_FACTS",
    "entities_skipped_from_worldbook",
    "entry_qualification",
    "estimate_tokens",
    "headline_for",
    "extract_relative_time",
    "filter_for_start_chapter",
    "find_contradictions",
    "plan_character_index",
    "plan_entity_entries",
    "plan_world_overview",
    "relation_timeline",
    "summarize_plan",
]
