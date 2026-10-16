"""时间线、知识边界、泄漏检查与世界书规划。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern.extract.schema import (
    EventRecord,
    FactRecord,
    RelationRecord,
    SourceRef,
)
from novel_to_tavern.resolve import CanonicalEntity
from novel_to_tavern.timeline import (
    TimelineError,
    build,
    build_knowledge,
    knowledge_summary,
    build_timeline,
    check_leakage,
    clip_at_sentence,
    entities_skipped_from_worldbook,
    entry_qualification,
    estimate_tokens,
    extract_relative_time,
    filter_for_start_chapter,
    find_contradictions,
    headline_for,
    plan_character_index,
    plan_entity_entries,
    plan_world_overview,
    summarize_plan,
)
from novel_to_tavern.timeline.worldbible import PlannedEntry

REF = SourceRef(source_id="s", chapter_id="c", start_line=1, end_line=2, quote="证据")


def _event(eid: str, chapter: int, order: int = 0, participants=(), title="事件", summary="概述"):
    return EventRecord(
        event_id=eid,
        chunk_id=f"ch{chapter}_p000",
        source_id="s",
        chapter_id=f"c{chapter}",
        chapter_index=chapter,
        order_in_chapter=order,
        title=title,
        summary=summary,
        participants=list(participants),
        fact_type="canon_fact",
        source_refs=[REF],
    )


def _fact(fid: str, subject: str, predicate: str, value: str, chapter: int = 0, **kw):
    return FactRecord(
        fact_id=fid,
        chunk_id=f"ch{chapter}_p000",
        source_id="s",
        chapter_id=f"c{chapter}",
        chapter_index=chapter,
        subject=subject,
        predicate=predicate,
        value=value,
        fact_type=kw.pop("fact_type", "canon_fact"),
        source_refs=kw.pop("source_refs", [REF]),
        review_status=kw.pop("review_status", "accepted"),
    )


def _entity(eid: str, name: str, kind="character", aliases=(), evidence=5, chapters=(0,)):
    return CanonicalEntity(
        id=eid,
        kind=kind,
        canonical_name=name,
        aliases=list(aliases),
        appearance_chapters=list(chapters),
        first_appearance_chapter=chapters[0] if chapters else None,
        evidence_count=evidence,
        importance=0.5,
    )


# --- 时间线 ---------------------------------------------------------------


def test_timeline_is_sorted_by_chapter_then_order():
    events = [_event("e2", 1, 1), _event("e1", 0, 0), _event("e3", 1, 0)]
    timeline = build_timeline(events)
    assert [e.event_id for e in timeline] == ["e1", "e3", "e2"]


def test_absolute_time_is_never_invented():
    timeline = build_timeline([_event("e1", 0, summary="他们出发了")])
    assert timeline[0].occurred_at is None


def test_relative_time_is_recorded_without_conversion():
    timeline = build_timeline([_event("e1", 0, summary="次日，他们到达港口")])
    assert timeline[0].relative_time == "次日"
    assert timeline[0].occurred_at is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("第二天清晨", "第二天"), ("三年之后", "三年之后"), ("当晚", "当晚"), ("没有时间词", None)],
)
def test_relative_markers(text, expected):
    assert extract_relative_time(text) == expected


def test_revealed_at_chapter_is_the_statement_chapter():
    timeline = build_timeline([_event("e1", 7)])
    assert timeline[0].revealed_at_chapter == 7


# --- 知识边界 -------------------------------------------------------------


def test_event_participants_get_candidates_not_established_knowledge():
    """在场 ≠ 知晓：参与事件只产生**候补**，不产生「已确立的知识」。"""
    events = [_event("e1", 2, participants=["甲", "乙"])]
    knowledge = build_knowledge(events, [])
    assert set(knowledge) == {"甲", "乙"}

    item = knowledge["甲"][0]
    assert item.knowledge_status == "unknown"
    assert item.acquisition_method == "witnessed"
    assert item.basis == "present_at_event"
    assert item.candidate is True
    # 关键：角色**何时**知道留空，不拿事件章节顶上
    assert item.acquired_at_chapter is None
    # 但「读者什么时候看到它」是另一回事，必须填
    assert item.revealed_at_chapter == 2
    assert item.occurred_at_chapter == 2


def test_non_participants_do_not_gain_knowledge():
    """不采用「事件发生后所有人都知道」的假设。"""
    events = [_event("e1", 2, participants=["甲"])]
    knowledge = build_knowledge(events, [])
    assert "丙" not in knowledge


def test_subject_of_fact_knows_its_own_fact():
    """唯一不需要额外证据的知识关系：事实的主语就是它自己。"""
    knowledge = build_knowledge([], [_fact("f1", "甲", "identity", "骑士")])
    item = knowledge["甲"][0]
    assert item.basis == "subject_of_fact"
    assert item.knowledge_status == "knows"
    assert item.acquisition_method == "subject"
    assert item.candidate is False
    assert item.acquired_at_chapter == 0


def test_a_fact_about_someone_does_not_teach_that_someone():
    """事实的对象 ≠ 事实的知情人。主语是甲的事实，说明的是「甲自己」知道。"""
    knowledge = build_knowledge([], [_fact("f1", "甲", "relationship", "与乙是兄弟")])
    assert set(knowledge) == {"甲"}
    assert "乙" not in knowledge


@pytest.mark.parametrize(
    ("fact_type", "status", "method"),
    [
        ("character_belief", "believes", "author_explicit"),
        ("rumor", "heard_rumor", "rumor"),
        ("inference", "suspects", "inferred"),
    ],
)
def test_extraction_marked_types_map_to_their_own_status(fact_type, status, method):
    """抽取器已经区分了信念/传闻/推断，直接沿用，不要压平成一个状态。"""
    fact = _fact("f1", "甲", "state", "某件事")
    fact.fact_type = fact_type
    item = build_knowledge([], [fact])["甲"][0]
    assert item.knowledge_status == status
    assert item.acquisition_method == method
    assert item.basis == "extraction_marked"
    assert item.candidate is (status != "knows")


def test_needs_review_items_do_not_enter_knowledge():
    events = [_event("e1", 2, participants=["甲"])]
    events[0].review_status = "needs_review"
    assert build_knowledge(events, []) == {}


def test_knowledge_summary_counts_by_status_and_candidates():
    events = [_event("e1", 2, participants=["甲", "乙"])]
    facts = [_fact("f1", "甲", "identity", "骑士")]
    summary = knowledge_summary(build_knowledge(events, facts))
    assert summary["total"] == 3
    assert summary["knows"] == 1
    assert summary["unknown"] == 2
    assert summary["candidates"] == 2
    assert summary["entities"] == 2


# --- 泄漏检查 -------------------------------------------------------------


def test_leakage_flags_everything_after_the_start_chapter():
    events = [_event("e1", 0), _event("e2", 9)]
    facts = [_fact("f1", "甲", "identity", "X", chapter=9)]
    findings = check_leakage(start_chapter=0, events=events, facts=facts)
    assert {f.item_id for f in findings} == {"e2", "f1"}
    assert all(f.start_chapter == 0 for f in findings)


def test_nothing_leaks_when_starting_after_the_end():
    events = [_event("e1", 0), _event("e2", 9)]
    assert check_leakage(start_chapter=9, events=events, facts=[]) == []


def test_leakage_explains_why():
    findings = check_leakage(start_chapter=0, events=[_event("e2", 9)], facts=[])
    assert "第 10 章" in findings[0].reason
    assert "第 1 章" in findings[0].reason


# --- 冲突 -----------------------------------------------------------------


def test_contradictions_are_reported_not_resolved():
    facts = [
        _fact("f1", "甲", "identity", "骑士", chapter=0),
        _fact("f2", "甲", "identity", "王子", chapter=5),
    ]
    findings = find_contradictions(facts)
    assert len(findings) == 1
    assert set(findings[0].values) == {"骑士", "王子"}
    assert "不自动" in findings[0].note or "需人工" in findings[0].note


def test_non_canon_facts_do_not_raise_contradictions():
    facts = [
        _fact("f1", "甲", "identity", "骑士"),
        _fact("f2", "甲", "identity", "王子", fact_type="character_belief"),
    ]
    assert find_contradictions(facts) == []


# --- 世界书规划 -----------------------------------------------------------


def test_entities_without_facts_get_no_entry():
    """一条 canon 事实都没有、又只露一次面的实体不该进世界书。"""
    entities = [_entity("ent_0001", "玩具熊", kind="item")]
    entries = plan_entity_entries(entities, [])
    assert entries == []


def test_entities_skipped_are_reported_not_silently_dropped():
    entities = [_entity("ent_0001", "玩具熊", kind="item"), _entity("ent_0002", "西泽尔")]
    facts = [
        _fact("f1", "西泽尔", "identity", "红龙骑士团团长"),
        _fact("f2", "西泽尔", "goal", "夺回王座"),
    ]
    skipped = entities_skipped_from_worldbook(entities, facts)
    assert [e.canonical_name for e, _ in skipped] == ["玩具熊"]
    assert "没有任何已校验" in skipped[0][1]


def test_two_facts_are_enough_for_an_entry():
    entities = [_entity("ent_0001", "甲", chapters=(0,))]
    facts = [_fact("f1", "甲", "identity", "某人"), _fact("f2", "甲", "goal", "复仇")]
    assert entry_qualification(entities[0], facts)[0] is True
    assert plan_entity_entries(entities, facts)


def test_one_fact_is_not_enough_for_a_one_chapter_entity():
    """只出场一章、只有一条事实 —— 像顺带一提，不值得单开条目。"""
    entities = [_entity("ent_0001", "军徽", kind="item", chapters=(0,))]
    facts = [_fact("f1", "军徽", "appearance", "银色的中校军徽")]
    ok, reason = entry_qualification(entities[0], facts)
    assert ok is False
    assert "顺带一提" in reason


def test_presence_rescues_an_entity_with_few_facts():
    """出场 3 章以上就算抽取没抽够，也该保留 —— 说明故事反复回到它。"""
    entities = [_entity("ent_0001", "教皇国", kind="faction", chapters=(0, 3, 7, 12))]
    facts = [_fact("f1", "教皇国", "background", "西方各国的领袖")]
    ok, reason = entry_qualification(entities[0], facts)
    assert ok is True
    entries = plan_entity_entries(entities, facts)
    assert len(entries) == 1
    assert any("补抽" in f for f in entries[0].quality_flags)


def test_zero_facts_never_gets_an_entry_even_with_many_appearances():
    """出场再多，一条事实都没有就写不出内容 —— 保留只会多出一个空条目。"""
    entities = [_entity("ent_0001", "亚琛", kind="place", chapters=(0, 2, 5, 9, 12))]
    ok, reason = entry_qualification(entities[0], [])
    assert ok is False
    assert "写不出内容" in reason
    assert plan_entity_entries(entities, []) == []


def test_no_entry_is_ever_rendered_empty():
    """兜底断言：任何生成的条目都必须有非空正文。"""
    entities = [_entity("ent_0001", "甲"), _entity("ent_0002", "乙", chapters=(0, 3, 6))]
    facts = [
        _fact("f1", "甲", "identity", "某人"),
        _fact("f2", "甲", "goal", "复仇"),
        _fact("f3", "乙", "identity", "另一人"),
    ]
    for entry in plan_entity_entries(entities, facts):
        assert entry.content_runtime.strip(), entry.title


def test_needs_review_facts_do_not_qualify_an_entity():
    """未通过证据校验的事实不算数，不能靠它把空壳实体撑起来。"""
    entities = [_entity("ent_0001", "玩具熊", kind="item")]
    facts = [_fact("f1", "玩具熊", "identity", "某人的玩偶", review_status="needs_review")]
    assert plan_entity_entries(entities, facts) == []


def test_non_canon_facts_do_not_qualify_an_entity():
    entities = [_entity("ent_0001", "自闭症", kind="concept")]
    facts = [_fact("f1", "自闭症", "identity", "某角色的症状", fact_type="inference")]
    assert plan_entity_entries(entities, facts) == []


def test_clip_at_sentence_does_not_cut_mid_sentence():
    text = "第一句话结束了。第二句话被切断在这里没有结束"
    clipped = clip_at_sentence(text, 12)
    assert clipped.endswith("。")
    assert "第二句话" not in clipped


def test_clip_at_sentence_keeps_short_text_intact():
    assert clip_at_sentence("很短的一句话", 40) == "很短的一句话"


def test_headline_prefers_background_over_action():
    entity = _entity("ent_0001", "甲")
    facts = [
        _fact("f1", "甲", "action", "做了一件不重要的事"),
        _fact("f2", "甲", "background", "出身于北方的商人家庭"),
    ]
    assert headline_for(entity, facts) == "出身于北方的商人家庭"


def test_entity_entry_keys_include_name_and_aliases():
    """别名/称号必须能单独触发条目，否则只用称号提到角色时会漏。"""
    entity = _entity("ent_0001", "西泽尔", aliases=["红龙", "殿下"])
    facts = [
        _fact("f1", "西泽尔", "identity", "红龙骑士团团长"),
        _fact("f2", "西泽尔", "goal", "夺回王座"),
    ]
    entry = plan_entity_entries([entity], facts)[0]
    assert entry.keys == ["西泽尔", "红龙", "殿下"]
    assert entry.secondary_keys == []


def test_entity_entry_content_uses_only_accepted_canon_facts():
    entity = _entity("ent_0001", "甲")
    facts = [
        _fact("f1", "甲", "identity", "骑士"),
        _fact("f2", "甲", "identity", "王子", fact_type="rumor"),
        _fact("f3", "甲", "goal", "复仇", review_status="needs_review"),
        _fact("f4", "甲", "state", "在边境驻守"),
    ]
    entry = plan_entity_entries([entity], facts)[0]
    assert "骑士" in entry.content_runtime
    assert "王子" not in entry.content_runtime
    assert "复仇" not in entry.content_runtime


def test_character_index_is_always_on_and_compact():
    entities = [_entity(f"ent_{i:04d}", f"角色{i}", evidence=10 - i) for i in range(10)]
    entry = plan_character_index(entities)
    assert entry.always_on is True
    assert entry.keys == []
    assert entry.estimated_tokens < 200


def test_character_index_is_none_without_characters():
    assert plan_character_index([_entity("ent_0001", "某地", kind="place")]) is None


def test_world_overview_describes_entities_not_just_names():
    """世界概况要概括世界，不能只是名字清单。"""
    entities = [
        _entity("ent_0001", "君士坦丁堡", kind="place"),
        _entity("ent_0002", "炽天骑士团", kind="faction"),
    ]
    facts = [
        _fact("f1", "君士坦丁堡", "background", "新罗马帝国的首都，皇宫建在临海一角"),
        _fact("f2", "炽天骑士团", "identity", "西方最强的甲胄骑士团"),
    ]
    entry = plan_world_overview(entities, facts)
    assert entry.always_on
    assert "新罗马帝国的首都" in entry.content_runtime
    assert "西方最强的甲胄骑士团" in entry.content_runtime


def test_world_overview_lists_nameless_entities_separately():
    entities = [
        _entity("ent_0001", "君士坦丁堡", kind="place"),
        _entity("ent_0002", "亚琛", kind="place"),
    ]
    facts = [_fact("f1", "君士坦丁堡", "background", "新罗马帝国的首都")]
    entry = plan_world_overview(entities, facts)
    assert "无独立设定" in entry.content_runtime
    assert "亚琛" in entry.content_runtime


def test_world_overview_is_none_without_anything():
    assert plan_world_overview([], []) is None


def test_start_chapter_blocks_future_entries_without_deleting_them():
    entries = [
        PlannedEntry(
            entry_id="plot", category="concept", title="剧情", content_runtime="x",
            content_canonical="x", valid_from_chapter=9, chapter_gated=True,
        ),
        PlannedEntry(
            entry_id="early", category="concept", title="早期剧情", content_runtime="y",
            content_canonical="y", valid_from_chapter=0, chapter_gated=True,
        ),
    ]
    available, blocked = filter_for_start_chapter(entries, 2)
    assert [e.entry_id for e in available] == ["early"]
    assert [e.entry_id for e in blocked] == ["plot"]


def test_entity_entries_are_not_gated_by_first_appearance():
    """角色在世界里本来就存在，不该因为"还没登场"被过滤掉。"""
    entries = [
        PlannedEntry(
            entry_id="late_character", category="character", title="迟到的角色",
            content_runtime="y", content_canonical="y", valid_from_chapter=120,
        ),
    ]
    available, blocked = filter_for_start_chapter(entries, 0)
    assert [e.entry_id for e in available] == ["late_character"]
    assert blocked == []


def test_no_filtering_when_start_chapter_is_unset():
    entries = [
        PlannedEntry(entry_id="b", category="character", title="B", content_runtime="y",
                     content_canonical="y", valid_from_chapter=9)
    ]
    available, blocked = filter_for_start_chapter(entries, None)
    assert available == entries and blocked == []


def test_token_estimate_counts_cjk_differently():
    assert estimate_tokens("中文内容") == 4
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcdefgh") == 2


def test_plan_summary_splits_always_on():
    entries = [
        PlannedEntry(entry_id="a", category="core_rules", title="A", content_runtime="十个字十个字",
                     content_canonical="", always_on=True, estimated_tokens=10),
        PlannedEntry(entry_id="b", category="character", title="B", content_runtime="x",
                     content_canonical="", estimated_tokens=5),
    ]
    stats = summarize_plan(entries)
    assert stats["always_on_entries"] == 1
    assert stats["triggered_entries"] == 1
    assert stats["always_on_tokens"] == 10


# --- 端到端 ---------------------------------------------------------------


def _prepare_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "canonical").mkdir(parents=True)
    (run / "reports").mkdir(parents=True)

    facts = [
        _fact("f1", "西泽尔", "identity", "红龙骑士团团长", chapter=0),
        _fact("f2", "西泽尔", "goal", "夺回王座", chapter=9),
        _fact("f3", "帕西", "identity", "西泽尔的随从", chapter=0),
        _fact("f4", "帕西", "goal", "跟随西泽尔", chapter=0),
        _fact("f5", "迟到的角色", "identity", "第 9 章才登场的人", chapter=9),
        _fact("f6", "迟到的角色", "goal", "有他自己的目的", chapter=9),
    ]
    events = [_event("e1", 0, participants=["西泽尔", "帕西"]), _event("e2", 9, participants=["西泽尔"])]
    relations = [
        RelationRecord(
            relation_id="r1", chunk_id="c", source_id="s", chapter_id="c0", chapter_index=0,
            from_entity="西泽尔", to_entity="帕西", relation="兄弟", source_refs=[REF],
        )
    ]
    entities = [
        _entity("ent_0001", "西泽尔", aliases=["红龙"], chapters=(0, 9)),
        _entity("ent_0002", "帕西", chapters=(0,)),
        _entity("ent_0003", "迟到的角色", chapters=(9,)),
    ]

    for name, payload in (
        ("entities.json", [e.model_dump(mode="json") for e in entities]),
        ("facts.json", [f.model_dump(mode="json") for f in facts]),
        ("events.json", [e.model_dump(mode="json") for e in events]),
        ("relations.json", [r.model_dump(mode="json") for r in relations]),
    ):
        (run / "canonical" / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return run


def test_build_writes_all_artifacts(tmp_path):
    run = _prepare_run(tmp_path)
    result = build(run)
    assert (run / "canonical" / "timeline.json").is_file()
    assert (run / "canonical" / "knowledge.json").is_file()
    assert (run / "canonical" / "leakage.json").is_file()
    assert (run / "canonical" / "contradictions.json").is_file()
    assert (run / "worldbook" / "plan.json").is_file()
    assert (run / "reports" / "timeline_report.md").is_file()
    assert result["timeline"]


def test_report_states_leakage_counts_for_both_start_points(tmp_path):
    run = _prepare_run(tmp_path)
    build(run)
    report = (run / "reports" / "timeline_report.md").read_text(encoding="utf-8")
    assert "从故事开头开始" in report
    assert "从故事结尾之后开始" in report
    assert "始终为 0" in report


def test_report_mentions_token_estimate_is_rough(tmp_path):
    run = _prepare_run(tmp_path)
    build(run)
    report = (run / "reports" / "timeline_report.md").read_text(encoding="utf-8")
    assert "粗估" in report


def test_start_chapter_keeps_the_full_cast(tmp_path):
    """从第 1 章开始时，全部实体条目仍然可用 —— 只是没有剧情屏蔽项。"""
    run = _prepare_run(tmp_path)
    result = build(run, start_chapter=0)
    available_ids = {e.entry_id for e in result["entries"]}
    assert "wb_entity_ent_0003" in available_ids
    assert "wb_entity_ent_0001" in available_ids


def test_missing_upstream_artifact_raises(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(TimelineError, match="缺少上游产物"):
        build(tmp_path / "run")
