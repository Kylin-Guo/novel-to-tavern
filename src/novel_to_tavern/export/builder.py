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

#: 「剧情主线」的触发词。**只用不会在日常对白里随便出现的词**。
#: 早先版本含「之前 / 后来 / 发生过 / 背景 / 回忆」—— 这些在中文里极常见，
#: 一旦命中就会把整本剧情（2.5 万字）灌进上下文。
PLOT_ENTRY_KEYS = [
    "剧情",
    "主线",
    "前情",
    "剧情走向",
    "原著剧情",
    "故事线",
]


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


def build_plot_entry(
    digests: list[ChapterDigest], *, upto_chapter: int | None = None
) -> PlannedEntry | None:
    """剧情走向（逐章），作为触发条目。

    两种形态：

    - **默认（`upto_chapter=None`）**：整本书的走向都在条目里，
      `valid_from_chapter` 设为末章，配合核心规则的时间纪律使用。
    - **严格起始点（`upto_chapter=N`）**：只渲染到第 N 章为止。
      起始点之后的内容**根本不写进条目** —— 这是结构性保证，
      而不是靠提示词要求模型自觉。

    条目键在两处都会命中「剧情」等词，所以严格档必须真的删内容，不能只加标注。
    """
    if not digests:
        return None

    selected = [d for d in digests if upto_chapter is None or d.chapter_index <= upto_chapter]
    if not selected:
        return None

    lines = [
        f"{chapter_label(d.chapter_index, d.title)}：{d.summary.strip() or '（无摘要）'}"
        for d in selected
    ]
    strict = upto_chapter is not None
    header = "原著剧情主线（逐章，按时间顺序）："
    if strict:
        header = (
            f"原著剧情主线（截至第 {upto_chapter + 1} 章，按时间顺序）。"
            "此后的事尚未发生："
        )
    body = header + "\n" + "\n".join(lines)

    flags = []
    if strict:
        flags.append(f"已按起始点过滤：只含第 1–{upto_chapter + 1} 章，后续剧情不在条目内")
    else:
        flags.append("含全书剧情，需配合时间纪律使用，避免剧透到起始点之前")

    return PlannedEntry(
        entry_id="wb_plot_main",
        category="concept",
        title="剧情主线（逐章）",
        content_runtime=body,
        content_canonical=body,
        keys=list(PLOT_ENTRY_KEYS),
        always_on=False,
        valid_from_chapter=(
            max(d.chapter_index for d in selected) if strict else max(d.chapter_index for d in digests)
        ),
        chapter_gated=True,
        estimated_tokens=estimate_tokens(body),
        priority=80,
        quality_flags=flags,
    )


#: 严格起始点卡片追加到规则末尾的一段。规则本身不变，只是把「时间纪律」
#: 从「要求模型自觉」换成「内容本来就不在」。
STRICT_START_NOTE = """
本卡为**严格起始点**版本，起点已固定：{label}。起始点之后的内容
**没有写进任何条目** —— 不是要求你忽略，是它们不在你的资料里。
若用户问到起始点之后的事，如实回答「尚未发生 / 我不知道」，不要推测原著后续。"""


def build_core_rules_entry(*, strict_start: str = "") -> PlannedEntry:
    """常驻的核心规则条目。

    只放**运行规则**。原先还把逐章剧情骨架塞在这里，结果是：条目叫「世界运行规则」，
    内容却是一份被 `[:60]` 硬切、句子断在半截的章节大纲 —— 名实不符且难读。
    剧情走向由「剧情主线」条目负责；概括世界由「世界概况」条目负责。

    `strict_start` 非空时（严格起始点卡）在末尾追加一段说明，告诉模型
    后续内容不存在而不是「存在但你不许看」。
    """
    body = CORE_RULES + (STRICT_START_NOTE.format(label=strict_start) if strict_start else "")
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
    strict_label: str = "",
    strict_chapter_index: int | None = None,
) -> Greetings:
    """默认产出三个开场：一个让用户选起点，两个分别对应两个起点。

    `strict_label` 非空时（严格起始点卡）改成**只描述那一个起点**，
    并且不再提供 alternate_greetings —— 那张卡里根本没有别的起点可选，
    给了按钮反而是误导。
    """
    if not digests:
        raise ValueError("没有章节摘要，无法生成开场白")

    if strict_label:
        return _build_strict_greetings(
            book_title=book_title,
            digests=digests,
            entities=entities,
            strict_label=strict_label,
            strict_chapter_index=strict_chapter_index,
        )

    first = digests[0]
    last = digests[-1]
    roster = _character_roster(entities)
    places = _places(entities)

    opening_event = timeline[0] if timeline else None
    ending_events = [e for e in timeline if e.chapter_index == last.chapter_index][-2:]

    def join_scenes(parts: list[str]) -> str:
        """拼接片段时先去掉片段末尾已有的句读，避免出现「。；」这种重复标点。"""
        cleaned = [p.strip().rstrip("。；;，, ") for p in parts if p and p.strip()]
        return "；".join(cleaned)

    begin_scene = first.summary.strip() or first.title or "故事的开端"
    end_scene = (
        join_scenes([e.summary for e in ending_events])
        or last.summary.strip()
        or "故事的终章"
    )

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
        f"此刻，{roster.split('、')[0] if roster else '故事里的人们'}还不知道后面会发生什么。"
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


def _build_strict_greetings(
    *,
    book_title: str,
    digests: list[ChapterDigest],
    entities: list[CanonicalEntity],
    strict_label: str,
    strict_chapter_index: int | None,
) -> Greetings:
    """严格起始点卡的单一开场。

    这里**不复述该章节之后**的任何剧情：场景描述只用到起始点为止的章节摘要。
    """
    roster = _character_roster(entities)
    places = _places(entities)

    if strict_chapter_index is None:
        visible = digests
    else:
        visible = [d for d in digests if d.chapter_index <= strict_chapter_index]

    scene = ""
    if visible:
        tail = visible[-1]
        scene = tail.summary.strip() or tail.title or ""
    if not scene:
        scene = "故事尚未开始。"

    upto_note = (
        f"本卡只包含到「{strict_label}」为止的内容，之后的事尚未发生。"
        "你可以自由行动，世界会按自己的逻辑推进；不必遵循原著后续。"
    )

    description = (
        f"《{book_title}》世界模拟器（严格起始点：{strict_label}）。"
        f"{CORE_RULES}{STRICT_START_NOTE.format(label=strict_label)}\n"
        f"当前时间点：{strict_label}。"
    )
    scenario = (
        f"世界：{book_title}。\n"
        f"当前时间点：{strict_label}。\n"
        f"已出场人物：{roster or '（见人物条目）'}\n"
        f"已提及地点：{places or '（见地点条目）'}"
    )
    first_mes = (
        f"【{book_title} · 世界模拟器】\n"
        f"【起点：{strict_label}】\n\n"
        f"{scene}\n\n"
        f"{upto_note}\n\n"
        f"先说两件事：\n"
        f"1. 你扮演谁？（可以说一个已出场人物，也可以是你自己带来的角色）\n"
        f"2. 你此刻在哪里、正在做什么？"
    )
    mes_example = (
        f"<START>\n"
        f"{{{{user}}}}: 后来会发生什么？\n"
        f"{{{{char}}}}: （本卡的时间点固定在「{strict_label}」。"
        f"之后的事尚未发生，如实回答不知道，不推测。）\n"
        f"<START>\n"
        f"{{{{user}}}}: {roster.split('、')[0] if roster else '某人'}现在在想什么？\n"
        f"{{{{char}}}}: （以该人物的性格与目标作答，只使用此刻有合法渠道获知的信息。）"
    )
    return Greetings(
        first_mes=first_mes,
        alternate_greetings=[],
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
