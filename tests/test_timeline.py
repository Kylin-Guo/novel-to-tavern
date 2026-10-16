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
    build_timeline,
    check_leakage,
    estimate_tokens,
    extract_relative_time,
    filter_for_start_chapter,
    find_contradictions,
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
    [("第二天清晨", "第二天"), ("三年之后", None), ("当晚", "当晚"), ("没有时间词", None)],
)
def test_relative_markers(text, expected):
    assert extract_relative_time(text) == expected


def test_revealed_at_chapter_is_the_statement_chapter():
    timeline = build_timeline([_event("e1", 7)])
    assert timeline[0].revealed_at_chapter == 7


# --- 知识边界 -------------------------------------------------------------


def test_only_participants_know_an_event():
    events = [_event("e1", 2, participants=["甲", "乙"])]
    knowledge = build_knowledge(events, [])
    assert set(knowledge) == {"甲", "乙"}
    assert knowledge["甲"][0].acquired_at_chapter == 2
    assert knowledge["甲"][0].basis == "present_at_event"


def test_non_participants_do_not_gain_knowledge():
    """不采用「事件发生后所有人都知道」的假设。"""
    events = [_event("e1", 2, participants=["甲"])]
    knowledge = build_knowledge(events, [])
    assert "丙" not in knowledge


def test_subject_of_fact_knows_its_own_fact():
    knowledge = build_knowledge([], [_fact("f1", "甲", "identity", "骑士")])
    assert knowledge["甲"][0].basis == "subject_of_fact"


def test_needs_review_items_do_not_enter_knowledge():
    events = [_event("e1", 2, participants=["甲"])]
    events[0].review_status = "needs_review"
    assert build_knowledge(events, []) == {}


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


def test_every_entity_gets_an_entry():
    entities = [_entity(f"ent_{i:04d}", f"角色{i}") for i in range(30)]
    entries = plan_entity_entries(entities, [])
    assert len(entries) == 30


def test_entity_entry_keys_include_name_and_aliases():
    """别名/称号必须能单独触发条目，否则只用称号提到角色时会漏。"""
    entity = _entity("ent_0001", "西泽尔", aliases=["红龙", "殿下"])
    entry = plan_entity_entries([entity], [])[0]
    assert entry.keys == ["西泽尔", "红龙", "殿下"]
    assert entry.secondary_keys == []


def test_entity_entry_content_uses_only_accepted_canon_facts():
    entity = _entity("ent_0001", "甲")
    facts = [
        _fact("f1", "甲", "identity", "骑士"),
        _fact("f2", "甲", "identity", "王子", fact_type="rumor"),
        _fact("f3", "甲", "goal", "复仇", review_status="needs_review"),
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


def test_world_overview_lists_places_and_factions():
    entities = [
        _entity("ent_0001", "君士坦丁堡", kind="place"),
        _entity("ent_0002", "红龙骑士团", kind="faction"),
    ]
    entry = plan_world_overview(entities, [])
    assert entry.always_on
    assert "君士坦丁堡" in entry.content_runtime
    assert "红龙骑士团" in entry.content_runtime


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
