"""把世界书规划装配成酒馆可导入的产物。

职责边界：
- **不重新调用模型猜事实**，只整理已校验的 canonical 数据；
- 核心规则、开场白这类"作者写的话"由本模块生成，标为项目自身的设定而非原著内容；
- 最终 JSON 一律由 `tavern.serializer` 序列化。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..extract.schema import SourceRef
from ..resolve.entities import CanonicalEntity
from ..tavern import (
    CharBookPosition,
    EntryDraft,
    build_card_v2,
    build_standalone_worldbook,
)
from ..timeline.build import TimelineEvent
from ..timeline.worldbible import PlannedEntry, estimate_tokens

StartPoint = Literal["beginning", "after_ending"]

#: 世界模拟器的核心运行规则。这是**本项目撰写**的模拟器设定，
#: 不是原著内容，也不冒充原著内容。
CORE_RULES = """这是一个多角色世界模拟器。请遵守以下运行规则：

1. 世界自行运转。NPC 按自己的目标与性格行动，不围着用户转，也不替用户做决定。
2. 用户独占其扮演角色的行动、台词与内心。不要替用户说话或决定其想法。
3. NPC 只知道两件事：截至当前时间点已经发生的事，以及它有合法渠道获知的事。
   没在场、没人告诉它的事，它不知道。
4. 角色的性格、动机与说话方式必须与「人物」条目一致，不得为了剧情方便而改变。
5. 保持连续：时间、地点、伤势、持有物、资源与因果不能凭空跳变。
6. 严格区分四类信息：原著已明确的事实、某个角色**以为**的事实、世界中的传闻、以及本次分支产生的新事件。
   分支新事件不得说成原著设定。
7. 时间点由用户选择。世界书「剧情主线」条目按章标注了原著走向；
   **标注章节晚于当前起始点的内容尚未发生**，NPC 不得据此行动、不得提前知道。
8. 用户若选择从故事开头开始，后续剧情不必按原著发展；原著走向只作参考，不是必然结局。
"""

PLOT_ENTRY_KEYS = [
    "剧情",
    "主线",
    "前情",
    "之前",
    "此前",
    "发生过",
    "后来",
    "结局",
    "回忆",
    "原著",
    "背景",
]

#: 常驻的剧情骨架最多列多少行，超出转成触发条目承载。
MAX_SKELETON_LINES = 12


class ChapterDigest(BaseModel):
    chapter_index: int
    label: str
    summary: str
    title: str = ""


class Greetings(BaseModel):
    first_mes: str
    alternate_greetings: list[str] = Field(default_factory=list)
    mes_example: str = ""
    scenario: str = ""
    description: str = ""


def chapter_label(index: int, title: str = "") -> str:
    return f"第{index + 1}章" + (f" {title}" if title else "")


def build_plot_entry(digests: list[ChapterDigest]) -> PlannedEntry | None:
    """完整剧情走向（逐章），作为触发条目。

    这是"角色卡必须包含当前完整剧情走向"的落点：整条走向都在卡里，
    但按章标注，配合核心规则里的时间纪律使用。
    """
    if not digests:
        return None
    lines = [
        f"{chapter_label(d.chapter_index, d.title)}：{d.summary.strip() or '（无摘要）'}"
        for d in digests
    ]
    body = "原著剧情主线（逐章，按时间顺序）：\n" + "\n".join(lines)
    return PlannedEntry(
        entry_id="wb_plot_main",
        category="concept",
        title="剧情主线（逐章）",
        content_runtime=body,
        content_canonical=body,
        keys=list(PLOT_ENTRY_KEYS),
        always_on=False,
        estimated_tokens=estimate_tokens(body),
        priority=80,
        quality_flags=["含全书剧情，需配合时间纪律使用，避免剧透到起始点之前"],
    )


def plot_skeleton_text(digests: list[ChapterDigest]) -> str:
    """常驻的极简剧情骨架：只给阶段划分，让模型知道故事的大致形态。

    并入核心规则条目，而不是单开一个常驻条目 —— 常驻条目数要留在配置上限内。
    """
    if not digests:
        return ""
    step = max(1, len(digests) // MAX_SKELETON_LINES)
    picked = digests[::step][:MAX_SKELETON_LINES]
    body = "\n".join(
        f"　　{chapter_label(d.chapter_index)}：{(d.summary or d.title).strip()[:60]}"
        for d in picked
    )
    return f"\n剧情阶段（完整逐章走向见「剧情主线」条目，需要时检索它）：\n{body}"


def build_core_rules_entry(digests: list[ChapterDigest]) -> PlannedEntry:
    """常驻的核心规则条目。本项目撰写的模拟器设定 + 剧情骨架。"""
    body = CORE_RULES + plot_skeleton_text(digests)
    return PlannedEntry(
        entry_id="wb_core_rules",
        category="core_rules",
        title="世界运行规则",
        content_runtime=body,
        content_canonical=body,
        keys=[],
        always_on=True,
        estimated_tokens=estimate_tokens(body),
        priority=100,
    )


def _character_roster(entities: list[CanonicalEntity], limit: int = 12) -> str:
    characters = sorted(
        (e for e in entities if e.kind == "character"), key=lambda e: -e.evidence_count
    )[:limit]
    return "、".join(e.canonical_name for e in characters)


def _places(entities: list[CanonicalEntity], limit: int = 8) -> str:
    places = sorted((e for e in entities if e.kind == "place"), key=lambda e: -e.evidence_count)[:limit]
    return "、".join(e.canonical_name for e in places)


def build_greetings(
    *,
    book_title: str,
    digests: list[ChapterDigest],
    entities: list[CanonicalEntity],
    timeline: list[TimelineEvent],
) -> Greetings:
    """三个开场：一个让用户选起点，两个分别对应两个起点。

    起点信息写进开场白，模型才能知道"现在是哪一刻"。
    """
    if not digests:
        raise ValueError("没有章节摘要，无法生成开场白")

    first = digests[0]
    last = digests[-1]
    roster = _character_roster(entities)
    places = _places(entities)

    opening_event = timeline[0] if timeline else None
    ending_events = [e for e in timeline if e.chapter_index == last.chapter_index][-2:]

    begin_scene = first.summary.strip() or first.title or "故事的开端"
    end_scene = "；".join(e.summary for e in ending_events) or last.summary.strip() or "故事的终章"

    description = (
        f"《{book_title}》世界模拟器。{CORE_RULES}\n"
        f"当前起始时间点由用户在选择开场白时确定。"
    )

    scenario = (
        f"世界：{book_title}。\n"
        f"主要人物：{roster or '（见人物条目）'}\n"
        f"主要地点：{places or '（见地点条目）'}\n"
        f"原著共 {len(digests)} 章，起始时间点由用户选择。"
    )

    first_mes = (
        f"【{book_title} · 世界模拟器】\n\n"
        f"这个世界的走向已经写好，但**从哪一刻开始，由你决定**。请先选一个起点：\n\n"
        f"**1. 从故事的开头开始**（{chapter_label(first.chapter_index, first.title)} 之前）\n"
        f"　　{begin_scene}\n"
        f"　　从这里出发，后续剧情不必按原著发展。\n\n"
        f"**2. 从故事的最终结尾之后开始**（{chapter_label(last.chapter_index, last.title)} 之后）\n"
        f"　　{end_scene}\n"
        f"　　一切已经发生，你从结局之后的那一刻接着往下走。\n\n"
        f"回复 **1** 或 **2** 选择起点，然后告诉我：你要扮演谁？"
        f"（原有人物，或你自己带来的角色都行。）\n"
        f"如果想从中间某一章开始，直接说章节即可。"
    )

    greeting_beginning = (
        f"【起点：故事开头 · {chapter_label(first.chapter_index, first.title)} 之前】\n\n"
        f"{begin_scene}\n\n"
        f"此刻，{roster.split('、')[0] if roster else '故事里的人们'} 还不知道后面会发生什么。"
        f"你也不必照着原著走。\n\n"
        f"先说两件事：\n"
        f"1. 你扮演谁？（可以说一个原著人物，也可以是你自己带来的角色）\n"
        f"2. 你此刻在哪里、正在做什么？"
    )

    greeting_after_ending = (
        f"【起点：全书结局之后 · {chapter_label(last.chapter_index, last.title)} 之后】\n\n"
        f"{end_scene}\n\n"
        f"原著到这里就结束了。所有已经发生的事都已发生，所有人都带着结局留下的东西继续活着。\n\n"
        f"先说两件事：\n"
        f"1. 你扮演谁？\n"
        f"2. 故事结束之后的这段时间，你在哪里、做了什么？"
    )

    example_line = roster.split("、")[0] if roster else "某人"
    mes_example = (
        f"<START>\n"
        f"{{{{user}}}}: 现在是哪一年？发生过什么？\n"
        f"{{{{char}}}}: （先按「剧情主线」条目确认当前起始点，"
        f"只复述**不晚于该章节**的事；晚于起始点的内容尚未发生，不作回答。）\n"
        f"<START>\n"
        f"{{{{user}}}}: {example_line}现在在想什么？\n"
        f"{{{{char}}}}: （以「{example_line}」条目的性格与目标作答，"
        f"只使用该角色在当前位置有合法渠道获知的信息。）"
    )

    return Greetings(
        first_mes=first_mes,
        alternate_greetings=[greeting_beginning, greeting_after_ending],
        mes_example=mes_example,
        scenario=scenario,
        description=description,
    )


def plan_to_drafts(entries: list[PlannedEntry]) -> list[EntryDraft]:
    """把规划条目转成 serializer 的内部草稿。"""
    drafts: list[EntryDraft] = []
    for index, entry in enumerate(entries):
        drafts.append(
            EntryDraft(
                entry_id=entry.entry_id,
                title=entry.title,
                content=entry.content_runtime,
                keys=tuple(entry.keys),
                secondary_keys=tuple(entry.secondary_keys),
                always_on=entry.always_on,
                insertion_order=(index + 1) * 10,
                # 常驻规则放在角色定义之前，人物/事件资料放在之后
                position=(
                    CharBookPosition.before_char if entry.always_on else CharBookPosition.after_char
                ),
                entities=tuple(entry.entities),
                tags=tuple(entry.category for _ in [0]),
            )
        )
    return drafts


def build_exports(
    *,
    book_title: str,
    entries: list[PlannedEntry],
    greetings: Greetings,
    tags: list[str] | None = None,
    creator: str = "novel-to-tavern",
    version: str = "0.1.0",
):
    """返回 `(card, standalone_worldbook)`。"""
    drafts = plan_to_drafts(entries)
    card = build_card_v2(
        name=book_title,
        description=greetings.description,
        drafts=drafts,
        personality="（世界模拟器卡，无单一人格。）",
        scenario=greetings.scenario,
        first_mes=greetings.first_mes,
        mes_example=greetings.mes_example,
        creator_notes=(
            "由 novel-to-tavern 从原著文本生成。所有事实条目均带原文来源引用，"
            "见 run 目录下的 reports/audit.md 与 canonical/。"
        ),
        tags=list(tags or []),
        creator=creator,
        character_version=version,
        alternate_greetings=list(greetings.alternate_greetings),
        book_name=f"{book_title} · 世界书",
        book_description="世界运行规则与人物/地点/剧情资料，关键词触发。",
    )
    worldbook = build_standalone_worldbook(drafts)
    return card, worldbook


def source_refs_of(entries: list[PlannedEntry]) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for entry in entries:
        refs.extend(entry.source_refs)
    return refs
