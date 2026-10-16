"""世界书与角色卡导出（Phase 5）。

最终 JSON 一律由 `tavern.serializer` 生成；导出前必须通过结构校验与
内嵌/独立条目一致性比对，任一不通过就不写文件。
"""

from __future__ import annotations

from .builder import (
    CORE_RULES,
    PLOT_ENTRY_KEYS,
    PLOT_ENTRY_MUST_NOT_TRIGGER,
    ChapterDigest,
    Greetings,
    build_core_rules_entry,
    build_exports,
    build_greetings,
    build_plot_entry,
    plan_to_drafts,
)
from .runner import (
    AUDIT_NAME,
    BUDGET_NAME,
    CARD_NAME,
    MANIFEST_NAME,
    TIMELINE_NAME,
    WORLDBOOK_AFTER_END,
    WORLDBOOK_BEGINNING,
    WORLDBOOK_NAME,
    ExportError,
    export,
)

__all__ = [
    "AUDIT_NAME",
    "BUDGET_NAME",
    "CARD_NAME",
    "CORE_RULES",
    "MANIFEST_NAME",
    "PLOT_ENTRY_KEYS",
    "PLOT_ENTRY_MUST_NOT_TRIGGER",
    "TIMELINE_NAME",
    "WORLDBOOK_AFTER_END",
    "WORLDBOOK_BEGINNING",
    "WORLDBOOK_NAME",
    "ChapterDigest",
    "EntryDelta",
    "ExportError",
    "Greetings",
    "StartPoint",
    "StartState",
    "StrictPlan",
    "build_start_state",
    "plan_strict",
    "render_budget_report",
    "resolve_start_point",
    "build_core_rules_entry",
    "build_exports",
    "build_greetings",
    "build_plot_entry",
    "export",
    "plan_to_drafts",
]
