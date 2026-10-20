"""把风格档案拆成触发式世界书条目。

- 8 组固定分组，**非常驻**：风格规则只在用户谈到「文风/写作风格」时加载，
  避免 Description 与世界书常驻预算膨胀。
- 条目属于 Runtime 层，不是 canon。
- 严格起始点导出前用 `check_style_no_plot_leak` 拦截章节指涉 ——
  风格条目本不该提到剧情，这是双保险。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..timeline.worldbible import PlannedEntry, estimate_tokens
from . import StyleError
from .schema import StyleProfile

#: `(entry_id, title, 维度列表)`。最后一个分组没有维度，正文来自
#: `anti_patterns` + `contextual_variants`。
STYLE_ENTRY_GROUPS: list[tuple[str, str, list[str]]] = [
    ("wb_style_overview", "作者风格：总体叙事原则", ["narrative_voice", "genre_tone"]),
    ("wb_style_rhythm", "作者风格：句式与段落节奏", ["sentence_rhythm"]),
    ("wb_style_dialogue", "作者风格：对话与潜台词", ["dialogue_patterns"]),
    ("wb_style_psychology", "作者风格：心理描写", ["psychological_narration"]),
    ("wb_style_description", "作者风格：环境与感官描写", ["description_patterns"]),
    ("wb_style_figurative", "作者风格：意象与修辞", ["figurative_language"]),
    ("wb_style_pacing", "作者风格：场景节奏与高潮", ["scene_pacing"]),
    ("wb_style_anti", "作者风格：反模式与风格边界", []),
]

#: 触发词用**组合词**，避免单字在日常对白里命中。
STYLE_ENTRY_KEYS = ["作者风格", "叙事风格", "语言风格", "文风特点", "写作风格"]

#: 这些句子不得命中任何风格条目。加触发词时一并跑一遍。
STYLE_ENTRY_MUST_NOT_TRIGGER = (
    "这个剧情怎么发展？",
    "他的文风如何",
    "这个角色风格独特",
    "今天天气不错",
)

STYLE_ENTRY_FOOTER = "以上为非原著事实的写作风格规则。"


class StyleLeakError(StyleError):
    """风格条目里出现了起始点之后的章节号（严格起始点导出的结构性拦截）。"""


def _render_dimension(profile: StyleProfile, dim: str) -> str | None:
    value = getattr(profile, dim)
    if value.summary == "unknown" and not value.rules:
        return None
    lines = [f"【{dim}】{value.summary}".strip()]
    lines += [f"- {rule}" for rule in value.rules]
    return "\n".join(lines)


def build_style_entries(profile: StyleProfile) -> list[PlannedEntry]:
    """按固定分组生成条目。全组维度都是 unknown 时**不生成**该条目。"""
    entries: list[PlannedEntry] = []

    for entry_id, title, dimensions in STYLE_ENTRY_GROUPS:
        sections: list[str] = []
        if dimensions:
            for dim in dimensions:
                rendered = _render_dimension(profile, dim)
                if rendered:
                    sections.append(rendered)
        else:
            if profile.anti_patterns:
                sections.append(
                    "避免的写法：\n"
                    + "\n".join(f"- {item}" for item in profile.anti_patterns)
                )
            if profile.contextual_variants:
                sections.append(
                    "情境差异：\n"
                    + "\n".join(f"- {item}" for item in profile.contextual_variants)
                )

        if not sections:
            continue

        body = "\n\n".join(sections) + "\n\n" + STYLE_ENTRY_FOOTER
        entries.append(
            PlannedEntry(
                entry_id=entry_id,
                category="author_style",
                title=title,
                content_runtime=body,
                content_canonical=body,
                keys=list(STYLE_ENTRY_KEYS),
                secondary_keys=[],
                always_on=False,
                valid_from_chapter=None,
                chapter_gated=False,
                estimated_tokens=estimate_tokens(body),
                priority=40,
                quality_flags=["非 canon：作者风格资料，由自动蒸馏生成"],
            )
        )
    return entries


def write_style_entries(path: str | Path, entries: list[PlannedEntry]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            [entry.model_dump(mode="json") for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_style_entries(path: str | Path) -> list[PlannedEntry]:
    target = Path(path)
    return [
        PlannedEntry.model_validate(item)
        for item in json.loads(target.read_text(encoding="utf-8"))
    ]


#: 「第 N 章」—— 风格条目里本来就不该出现章节指涉。
_CHAPTER_REF = re.compile(r"第\s*(\d+)\s*章")


def check_style_no_plot_leak(entries: list[PlannedEntry], upto_chapter: int) -> None:
    """严格起始点导出前：风格条目提到起始点之后的章节就中止。

    `upto_chapter` 是 **0 基**章节序号；正文里的「第 N 章」是 1 基，
    所以判定条件是 `N - 1 > upto_chapter`。
    """
    violations: list[str] = []
    for entry in entries:
        for raw in _CHAPTER_REF.findall(entry.content_runtime):
            chapter_number = int(raw)
            if chapter_number - 1 > upto_chapter:
                violations.append(f"{entry.title}（{entry.entry_id}）提到第 {chapter_number} 章")
    if violations:
        raise StyleLeakError(
            "严格起始点导出被拦截：风格条目含起始点之后的章节指涉 —— "
            + "；".join(violations)
        )
