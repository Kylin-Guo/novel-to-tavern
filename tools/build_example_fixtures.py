#!/usr/bin/env python3
"""生成 examples/fixtures/ 下的最小示例产物。

用途有两个：
1. 给出一份**可直接导入 Tavo 做手工实测**的最小角色卡与独立世界书。
2. 用 `--check` 作为回归闸门：committed 的 fixture 必须与当前 serializer 输出一致。

内容全部为本项目自创的玩具设定，不含任何有版权的原文。

用法：
    python tools/build_example_fixtures.py          # 写入文件
    python tools/build_example_fixtures.py --check  # 只校验是否一致
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from novel_to_tavern.tavern import (  # noqa: E402
    CharBookPosition,
    EntryDraft,
    build_card_v2,
    build_standalone_worldbook,
    dumps,
)

FIXTURE_DIR = REPO_ROOT / "examples" / "fixtures"
CARD_PATH = FIXTURE_DIR / "minimal_world_simulator_v2.json"
WORLDBOOK_PATH = FIXTURE_DIR / "minimal_worldbook_standalone.json"

CREATOR = "novel-to-tavern (self-authored fixture)"

WORLD_RULES = (
    "这是一个多角色世界模拟器。世界自行运转，NPC 按自身目标行动，不围绕用户转。"
    "用户独占其扮演角色的行动、台词与内心。"
    "NPC 只知道截至当前时间点、且通过合法渠道获知的事。"
    "保持时间、地点、伤势、物品与因果连续；不得引用未来章节的信息。"
    "所有原著事实之外的内容必须标为分支推演，不得冒充原著设定。"
)

DESCRIPTION = f"{WORLD_RULES}\n\n开局时间点：第一章之前。地点：灰港。"

DRAFTS: list[EntryDraft] = [
    EntryDraft(
        entry_id="world_rules",
        title="世界运行规则",
        content=WORLD_RULES,
        always_on=True,
        insertion_order=10,
        position=CharBookPosition.before_char,
    ),
    EntryDraft(
        entry_id="world_overview",
        title="灰港概览",
        content=(
            "灰港是一座常年被浓雾笼罩的海港城。城中以潮汐钟报时，共十二响。"
            "港口区与上城之间由雾灯塔的灯光划分边界；雾太浓时，塔灯每夜只亮三次。"
        ),
        always_on=True,
        insertion_order=20,
        position=CharBookPosition.before_char,
    ),
    EntryDraft(
        entry_id="character_ling_shuang",
        title="凌霜（巡夜人）",
        content=(
            "凌霜，灰港巡夜人。二十五六岁，惯穿深灰短斗篷，左眉有一道旧疤。"
            "说话简短，习惯先问时间再问事。值夜时随身带一盏铜壳提灯。"
            "她不主动谈起自己的过去；被问到时会把话题转回公务。"
            "（来源：待 Phase 2 补 source_refs；本 fixture 仅用于格式验证。）"
        ),
        keys=("凌霜", "霜姐", "巡夜人"),
        secondary_keys=("灰港",),
        insertion_order=30,
        position=CharBookPosition.after_char,
        entities=("character_ling_shuang",),
    ),
    EntryDraft(
        entry_id="place_grey_harbour",
        title="灰港（地点）",
        content=(
            "港口区：码头、鱼市、潮汐钟楼。夜里只有提灯与塔灯照明。"
            "上城：档案馆、钟楼、巡夜人值房。两区之间有一道旧石阶，雾大时禁止通行。"
        ),
        keys=("灰港", "港口区", "雾灯塔"),
        insertion_order=40,
        position=CharBookPosition.after_char,
        entities=("place_grey_harbour",),
    ),
]


def build_card_text() -> str:
    card = build_card_v2(
        name="灰港纪事 · 世界模拟器",
        description=DESCRIPTION,
        drafts=DRAFTS,
        personality="（世界模拟器卡，无单一人格。）",
        scenario="灰港，第一章之前。用户可扮演本地居民、巡夜人或外来者。",
        first_mes=(
            "雾从码头漫上来，潮汐钟敲了十一响。\n"
            "你站在港口区的石阶下，提灯在几步之外。\n"
            "先说说，你是谁，这个时辰为什么会在这里？"
        ),
        mes_example=(
            "<START>\n{{user}}: 凌霜，今晚塔灯怎么只亮了一次？\n"
            "{{char}}: 凌霜抬眼看塔，把提灯换到左手。"
            "「雾压得低，风也不对。你从哪儿过来的？」\n"
            "<START>\n{{user}}: 我想去上城。\n"
            "{{char}}: 「石阶封了。」她侧身让开半步，没让路。"
            "「等钟响十二下再说。现在过去，出事我不认。」"
        ),
        creator_notes=(
            "Phase 0 格式 fixture。内容为本项目自创，用于验证 V2 卡 + 内嵌 character_book "
            "能否被目标客户端接受。尚未在 Tavo 实测。"
        ),
        system_prompt="",
        post_history_instructions="",
        tags=["世界模拟器", "格式fixture", "自创"],
        creator=CREATOR,
        character_version="0.0.1",
        alternate_greetings=["（备用开场）潮汐钟停在第十一响，雾里有脚步声。你是谁？"],
        book_name="灰港纪事 · 世界书",
        book_description="世界运行规则 + 灰港设定，关键词触发。",
    )
    return dumps(card) + "\n"


def build_worldbook_text() -> str:
    # 独立世界书保留全部模板字段（含 null），与 ST 自己写盘的形态一致 ——
    # 客户端读这些键时用的多是 `entry.x ?? 默认值`，键在但值为 null 最保守。
    return dumps(build_standalone_worldbook(DRAFTS), exclude_none=False) + "\n"


def _targets() -> dict[Path, str]:
    return {CARD_PATH: build_card_text(), WORLDBOOK_PATH: build_worldbook_text()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验已提交的 fixture 是否与当前输出一致")
    args = parser.parse_args(argv)

    drift: list[str] = []
    for path, text in _targets().items():
        if args.check:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != text:
                drift.append(str(path.relative_to(REPO_ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"已写入 {path.relative_to(REPO_ROOT)}")

    if args.check:
        if drift:
            print("fixture 与当前 serializer 输出不一致，请重跑本脚本：", file=sys.stderr)
            for item in drift:
                print(f"  - {item}", file=sys.stderr)
            return 1
        print("fixture 与 serializer 输出一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
