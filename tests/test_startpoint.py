"""严格起始点：起点之后的内容**不在文件里**，而不是「在但请别看」。

这一组是 P0-2 那种「承诺」和这里「结构」的分界线。核心断言方式很直接：
给每个章节的事实编一个独有标记串，然后检查起点之后的标记串
在渲染出来的条目正文里**一个都找不到**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern.export.builder import (
    ChapterDigest,
    build_core_rules_entry,
    build_greetings,
    build_plot_entry,
)
from novel_to_tavern.export.startpoint import (
    build_start_state,
    plan_strict,
    resolve_start_point,
)
from novel_to_tavern.extract.schema import EventRecord, FactRecord, RelationRecord, SourceRef
from novel_to_tavern.resolve.entities import CanonicalEntity

TOTAL_CHAPTERS = 5


def _ref(chapter: int) -> SourceRef:
    return SourceRef(
        source_id="s", chapter_id=f"c{chapter}", start_line=1, end_line=2, quote=f"引文{chapter}"
    )


def _marker(chapter: int) -> str:
    """每章独有的标记串。章节过滤一旦失效，它就会出现在起点之前的条目里。"""
    return f"〈第{chapter}章专属内容ZZ{chapter}ZZ〉"


@pytest.fixture
def world():
    """5 章的合成世界：每章一个实体、一条事实、一个事件。"""
    entities = [
        CanonicalEntity(
            id=f"e{ch}",
            kind="character",
            canonical_name=f"人物{ch}",
            appearance_chapters=[ch],
            first_appearance_chapter=ch,
            evidence_count=10 - ch,
            importance=1.0 - ch / 10,
            source_refs=[_ref(ch)],
        )
        for ch in range(TOTAL_CHAPTERS)
    ]
    # 每个实体两条事实 —— 恰好越过 MIN_ENTITY_FACTS，这样「没条目」只可能是
    # 起始点过滤造成的，而不是被事实门槛挡掉。
    facts = [
        FactRecord(
            fact_id=f"f{ch}_{suffix}",
            chunk_id=f"k{ch}",
            source_id="s",
            chapter_id=f"c{ch}",
            chapter_index=ch,
            subject=f"人物{ch}",
            predicate=predicate,
            value=f"{_marker(ch)}他此刻的{predicate}",
            fact_type="canon_fact",
            source_refs=[_ref(ch)],
        )
        for ch in range(TOTAL_CHAPTERS)
        for suffix, predicate in (("a", "state"), ("b", "background"))
    ]
    events = [
        EventRecord(
            event_id=f"ev{ch}",
            chunk_id=f"k{ch}",
            source_id="s",
            chapter_id=f"c{ch}",
            chapter_index=ch,
            order_in_chapter=0,
            title=f"事件{ch}",
            summary=f"{_marker(ch)}发生了一件事",
            fact_type="canon_fact",
            source_refs=[_ref(ch)],
        )
        for ch in range(TOTAL_CHAPTERS)
    ]
    relations = [
        RelationRecord(
            relation_id=f"r{ch}",
            chunk_id=f"k{ch}",
            source_id="s",
            chapter_id=f"c{ch}",
            chapter_index=ch,
            from_entity=f"人物{ch}",
            to_entity="人物0",
            relation="认识",
            source_refs=[_ref(ch)],
        )
        for ch in range(TOTAL_CHAPTERS)
    ]
    digests = [
        ChapterDigest(
            chapter_index=ch,
            label=f"第{ch + 1}章",
            title=f"标题{ch}",
            summary=f"{_marker(ch)}这一章讲了一件事",
        )
        for ch in range(TOTAL_CHAPTERS)
    ]
    return entities, facts, events, relations, digests


# --- 起始点解析 ------------------------------------------------------------


def test_resolve_chapter_start_point():
    start = resolve_start_point(
        mode="chapter", chapter_index=2, digests_chapters=list(range(TOTAL_CHAPTERS))
    )
    assert start.chapter_index == 2
    assert start.total_chapters == TOTAL_CHAPTERS - 1
    assert start.strict is True


def test_resolve_after_ending_uses_the_last_chapter():
    start = resolve_start_point(
        mode="after_ending", chapter_index=None, digests_chapters=list(range(TOTAL_CHAPTERS))
    )
    assert start.chapter_index == TOTAL_CHAPTERS - 1


def test_resolve_beginning_is_before_chapter_one():
    start = resolve_start_point(
        mode="beginning", chapter_index=None, digests_chapters=list(range(TOTAL_CHAPTERS))
    )
    assert start.chapter_index == -1
    assert start.is_beginning


def test_out_of_range_chapter_is_rejected():
    with pytest.raises(ValueError, match="超出范围"):
        resolve_start_point(
            mode="chapter", chapter_index=99, digests_chapters=list(range(TOTAL_CHAPTERS))
        )


def test_missing_chapter_index_is_rejected():
    with pytest.raises(ValueError, match="chapter_index"):
        resolve_start_point(mode="chapter", chapter_index=None, digests_chapters=[0, 1])


# --- 核心保证：起点之后的标记串一个都不出现 ---------------------------------


@pytest.mark.parametrize("start_chapter", [0, 1, 2, 3, 4])
def test_no_future_chapter_marker_survives_in_any_entry(world, start_chapter):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(
        mode="chapter", chapter_index=start_chapter, digests_chapters=list(range(TOTAL_CHAPTERS))
    )
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    entries = [build_core_rules_entry(strict_start=start.chapter_label), *plan.entries]

    rendered = "\n".join(e.content_runtime for e in entries)
    for later in range(start_chapter + 1, TOTAL_CHAPTERS):
        assert _marker(later) not in rendered, (
            f"从第 {start_chapter + 1} 章开始时，第 {later + 1} 章的内容仍出现在条目正文里"
        )
    # 起点及之前的标记串必须在（否则过滤过头，把该有的也删了）
    for earlier in range(start_chapter + 1):
        assert _marker(earlier) in rendered


def test_entities_that_do_not_exist_yet_get_no_entry(world):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="chapter", chapter_index=0, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    titles = {e.title for e in plan.entries}
    assert "人物0" in titles
    for later in range(1, TOTAL_CHAPTERS):
        assert f"人物{later}" not in titles


def test_beginning_start_yields_an_empty_world_and_says_so(world):
    """「第 1 章之前」世界还没被叙述 —— 实体条目全部落空是正确行为。"""
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="beginning", chapter_index=None, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    assert plan.entities_with_entries == 0
    assert plan.facts_excluded == plan.facts_total


def test_plan_diff_records_what_was_dropped_and_why(world):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="chapter", chapter_index=1, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    dropped_titles = {d.title for d in plan.dropped}
    assert {"人物2", "人物3", "人物4"} <= dropped_titles
    assert all(d.reason for d in plan.dropped), "被删的条目必须写明原因"
    assert plan.facts_included == 4  # 前两章各 2 条
    assert plan.facts_excluded == 6


# --- 剧情主线条目 ----------------------------------------------------------


def test_plot_entry_is_truncated_not_merely_labelled(world):
    _, _, _, _, digests = world
    full = build_plot_entry(digests)
    cut = build_plot_entry(digests, upto_chapter=1)
    assert full is not None and cut is not None
    assert len(cut.content_runtime) < len(full.content_runtime)
    for later in range(2, TOTAL_CHAPTERS):
        assert _marker(later) not in cut.content_runtime
    assert _marker(0) in cut.content_runtime and _marker(1) in cut.content_runtime


def test_plot_entry_flags_are_honest_about_strictness(world):
    _, _, _, _, digests = world
    strict = build_plot_entry(digests, upto_chapter=1)
    full = build_plot_entry(digests)
    assert any("已按起始点过滤" in f for f in strict.quality_flags)
    assert any("含全书剧情" in f for f in full.quality_flags)


# --- 开场白 ----------------------------------------------------------------


def test_strict_greetings_offer_only_one_start(world):
    entities, _, _, _, digests = world
    greetings = build_greetings(
        book_title="测试书",
        digests=digests,
        entities=entities,
        timeline=[],
        strict_label="第2章 标题1",
        strict_chapter_index=1,
    )
    assert greetings.alternate_greetings == []
    assert "第2章" in greetings.first_mes
    for later in range(2, TOTAL_CHAPTERS):
        assert _marker(later) not in greetings.first_mes
        assert _marker(later) not in greetings.description


def test_strict_greetings_do_not_name_characters_that_appear_later(world):
    """摘要过滤拦不住人名 —— 名单本身就是剧透。

    这一条是补上的：早先只断言章节摘要标记不泄漏，于是
    「人物3 / 人物4」这类后期角色照样出现在 scenario 的「已出场人物」里，
    测试全绿。名字会随卡送进客户端，所以它和正文一样是剧透面。
    """
    entities, _, _, _, digests = world
    greetings = build_greetings(
        book_title="测试书",
        digests=digests,
        entities=entities,
        timeline=[],
        strict_label="第2章 标题1",
        strict_chapter_index=1,
    )
    rendered = "\n".join(
        [greetings.first_mes, greetings.scenario, greetings.description, greetings.mes_example]
    )
    for later in range(2, TOTAL_CHAPTERS):
        assert f"人物{later}" not in rendered, (
            f"从第 2 章严格开始时，第 {later + 1} 章才出场的「人物{later}」仍出现在开场材料里"
        )
    # 起点及之前的人物必须在，否则就是过滤过头
    assert "人物0" in rendered and "人物1" in rendered


def test_strict_greetings_exclude_entities_with_unknown_first_appearance(world):
    """出场章节未知的实体在严格档里一律不列 —— 不赌。"""
    from novel_to_tavern.resolve.entities import CanonicalEntity

    entities, _, _, _, digests = world
    entities = [
        *entities,
        CanonicalEntity(
            id="eX",
            kind="character",
            canonical_name="无从判断何时出场的人",
            appearance_chapters=[],
            first_appearance_chapter=None,
            evidence_count=99,  # 证据最多，若不过滤必然排在第一位
        ),
    ]
    greetings = build_greetings(
        book_title="测试书",
        digests=digests,
        entities=entities,
        timeline=[],
        strict_label="第2章 标题1",
        strict_chapter_index=1,
    )
    assert "无从判断何时出场的人" not in greetings.scenario


def test_default_greetings_still_list_everyone(world):
    """严格档的过滤不能顺手把默认档也改了。"""
    entities, _, _, _, digests = world
    greetings = build_greetings(book_title="测试书", digests=digests, entities=entities, timeline=[])
    assert "人物0" in greetings.scenario
    assert f"人物{TOTAL_CHAPTERS - 1}" in greetings.scenario


def test_default_greetings_still_offer_two_starts(world):
    entities, _, _, _, digests = world
    greetings = build_greetings(book_title="测试书", digests=digests, entities=entities, timeline=[])
    assert len(greetings.alternate_greetings) == 2


def test_strict_core_rules_say_the_content_does_not_exist(world):
    plain = build_core_rules_entry()
    strict = build_core_rules_entry(strict_start="第2章 标题1")
    assert len(strict.content_runtime) > len(plain.content_runtime)
    assert "没有写进任何条目" in strict.content_runtime
    # 非严格版本不得出现这段话
    assert "没有写进任何条目" not in plain.content_runtime


# --- 起始状态快照 ----------------------------------------------------------


def test_start_state_partitions_facts(world):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="chapter", chapter_index=2, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    state = build_start_state(
        start=start, plan=plan, facts=facts, events=events, relations=relations, knowledge={}
    )
    assert set(state.active_fact_ids).isdisjoint(state.hidden_fact_ids)
    assert len(state.active_fact_ids) == 6  # 第 1–3 章各 2 条
    assert len(state.hidden_fact_ids) == 4
    assert state.facts_included == 6 and state.facts_excluded == 4


def test_start_state_keeps_relationships_up_to_the_start(world):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="chapter", chapter_index=1, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    state = build_start_state(
        start=start, plan=plan, facts=facts, events=events, relations=relations, knowledge={}
    )
    assert len(state.relationships) == 2  # 第 1、2 章各一条
    assert max(r.last_seen_chapter for r in state.relationships) == 1


def test_start_state_serialises_to_json(world, tmp_path: Path):
    entities, facts, events, relations, digests = world
    start = resolve_start_point(mode="chapter", chapter_index=1, digests_chapters=[0, 1, 2, 3, 4])
    plan = plan_strict(entities=entities, facts=facts, events=events, digests=digests, start=start)
    state = build_start_state(
        start=start, plan=plan, facts=facts, events=events, relations=relations, knowledge={}
    )
    payload = json.loads(json.dumps(state.model_dump(mode="json"), ensure_ascii=False))
    assert payload["start_chapter_index"] == 1
    assert payload["strict"] is True
    assert payload["notes"], "快照必须自带口径说明"


# --- 防御：实体 id 撞车会静默顶掉事实 ---------------------------------------


def test_duplicate_entity_ids_are_rejected_not_silently_merged(world):
    """两条实体共用一个 id 时，后者的事实会顶掉前者 —— 必须报错而不是出张错卡。"""
    entities, facts, events, relations, digests = world
    clashing = [
        CanonicalEntity(
            id="same", kind="character", canonical_name="甲",
            appearance_chapters=[0], first_appearance_chapter=0, evidence_count=5,
        ),
        CanonicalEntity(
            id="same", kind="character", canonical_name="乙",
            appearance_chapters=[1], first_appearance_chapter=1, evidence_count=4,
        ),
    ]
    start = resolve_start_point(mode="chapter", chapter_index=1, digests_chapters=[0, 1])
    with pytest.raises(ValueError, match="实体 id 重复"):
        plan_strict(
            entities=clashing, facts=facts[:2], events=[], digests=digests, start=start
        )
