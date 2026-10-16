"""实体归一：只按字面与显式别名合并，相似名一律进复核队列。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern.extract.schema import ChunkExtraction, MentionRecord, SourceRef
from novel_to_tavern.resolve import (
    CanonicalEntity,
    ResolutionError,
    cluster_mentions,
    is_role_noun,
    load_extractions,
    normalize_name,
    propose_merges,
    resolve,
)
from novel_to_tavern.resolve.entities import alias_links

REF = SourceRef(source_id="s", chapter_id="c1", start_line=1, end_line=2, quote="证据")


def _mention(mid: str, name: str, kind: str = "character", aliases=(), chapter: int = 0, chunk="ch1_p000"):
    return MentionRecord(
        mention_id=mid,
        chunk_id=chunk,
        source_id="s",
        chapter_id=f"c{chapter}",
        chapter_index=chapter,
        name=name,
        aliases=list(aliases),
        kind=kind,
        source_refs=[REF],
    )


def _extraction(index: int, mentions, facts=(), events=(), relations=()) -> ChunkExtraction:
    return ChunkExtraction(
        chunk_id=f"ch{index:03d}_p000",
        chapter_id=f"c{index}",
        source_id="s",
        chapter_index=index,
        mentions=list(mentions),
        facts=list(facts),
        events=list(events),
        relations=list(relations),
    )


def _write_run(tmp_path: Path, extractions) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "extraction").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for item in extractions:
        (run_dir / "extraction" / f"{item.chunk_id}.json").write_text(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
        )
    return run_dir


# --- 归一化与泛称 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("西泽尔", "西泽尔"),
        (" 西泽尔 ", "西泽尔"),
        ("西泽尔·冯·莱因哈特", "西泽尔冯莱因哈特"),
        ("ＣＣＶ", "ccv"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_punctuation_only_names_normalize_to_empty():
    assert normalize_name("……") == ""


@pytest.mark.parametrize("noun", ["少年", "少女", "士兵", "众人", "骑士", "他"])
def test_role_nouns_are_recognized(noun):
    assert is_role_noun(noun)


def test_proper_nouns_are_not_role_nouns():
    assert not is_role_noun("西泽尔")
    assert not is_role_noun("教皇尤利乌斯")


def test_role_nouns_are_excluded_from_clustering():
    mentions = [_mention("m1", "少年"), _mention("m2", "西泽尔")]
    clusters, excluded = cluster_mentions(mentions)
    assert [c.key for c in clusters] == ["西泽尔"]
    assert [m.name for m in excluded] == ["少年"]


def test_same_name_clusters_together():
    mentions = [_mention("m1", "西泽尔"), _mention("m2", "西泽尔"), _mention("m3", "帕西")]
    clusters, _ = cluster_mentions(mentions)
    by_key = {c.key: c for c in clusters}
    assert len(by_key["西泽尔"].mention_ids) == 2
    assert len(by_key["帕西"].mention_ids) == 1


# --- 合并候选：一律 needs_review ------------------------------------------


def test_substring_names_are_proposed_but_never_auto_merged():
    mentions = [_mention("m1", "帕西"), _mention("m2", "帕西瓦尔")]
    clusters, _ = cluster_mentions(mentions)
    decisions = propose_merges(clusters)
    assert decisions
    assert all(d.decision == "needs_review" for d in decisions)
    assert any("字面包含" in s for d in decisions for s in d.match_signals)


def test_similar_names_are_not_merged_into_one_entity(tmp_path):
    """同名不同人 / 近名不同人：不能因为长得像就合并。"""
    run_dir = _write_run(
        tmp_path,
        [
            _extraction(0, [_mention("m1", "帕西")]),
            _extraction(1, [_mention("m2", "帕西瓦尔")]),
        ],
    )
    result = resolve(run_dir)
    names = {e.canonical_name for e in result.entities}
    assert names == {"帕西", "帕西瓦尔"}
    assert result.review_queue


def test_single_chunk_alias_claim_goes_to_review_not_merge():
    """抽取器只在一处顺口说"X 又名 Y"，不足以据此合并两个实体。"""
    mentions = [
        _mention("m1", "西泽尔", aliases=["红龙"], chunk="ch1_p000"),
        _mention("m2", "红龙", chunk="ch1_p000"),
    ]
    clusters, _ = cluster_mentions(mentions)
    accepted, review = alias_links(clusters, mentions)
    assert accepted == {}
    assert len(review) == 1
    assert review[0].decision == "needs_review"
    assert "独立断言" in review[0].match_signals[0]


def test_alias_asserted_in_two_chunks_is_merged():
    mentions = [
        _mention("m1", "西泽尔", aliases=["红龙"], chunk="ch1_p000"),
        _mention("m2", "红龙", chunk="ch1_p000"),
        _mention("m3", "西泽尔", aliases=["红龙"], chunk="ch9_p000"),
    ]
    clusters, _ = cluster_mentions(mentions)
    accepted, review = alias_links(clusters, mentions)
    assert accepted == {"西泽尔": ["红龙"]}
    assert review == []


def test_character_merged_with_non_character_is_refused():
    """把一个人和一个组织当成同一实体几乎一定是抽取错误。"""
    mentions = [
        _mention("m1", "佛朗哥", aliases=["枢机会"], kind="character", chunk="ch1_p000"),
        _mention("m2", "枢机会", kind="faction", chunk="ch1_p000"),
        _mention("m3", "佛朗哥", aliases=["枢机会"], kind="character", chunk="ch5_p000"),
        _mention("m4", "枢机会", kind="faction", chunk="ch5_p000"),
    ]
    clusters, _ = cluster_mentions(mentions)
    accepted, review = alias_links(clusters, mentions)
    assert accepted == {}
    assert review and "类别不兼容" in review[0].match_signals[0]


def test_alias_merge_is_recorded_with_a_signal(tmp_path):
    run_dir = _write_run(
        tmp_path,
        [
            _extraction(0, [_mention("m1", "西泽尔", aliases=["红龙"]), _mention("m2", "红龙")]),
            _extraction(1, [_mention("m3", "西泽尔", aliases=["红龙"], chunk="ch2_p000")]),
        ],
    )
    result = resolve(run_dir)
    merged = [d for d in result.decisions if d.decision == "merge"]
    assert merged
    assert "别名" in merged[0].match_signals[0]
    entity = next(e for e in result.entities if e.canonical_name == "西泽尔")
    assert "红龙" in entity.aliases


def test_refused_alias_keeps_two_entities(tmp_path):
    run_dir = _write_run(
        tmp_path,
        [_extraction(0, [_mention("m1", "秘银", aliases=["秘金"]), _mention("m2", "秘金")])],
    )
    result = resolve(run_dir)
    assert {e.canonical_name for e in result.entities} == {"秘银", "秘金"}
    assert any("独立断言" in d.match_signals[0] for d in result.review_queue)


# --- 档案汇总 -------------------------------------------------------------


def _entity_payload():
    from novel_to_tavern.extract.schema import EventRecord, FactRecord, RelationRecord

    facts = [
        FactRecord(
            fact_id="f1", chunk_id="ch000_p000", source_id="s", chapter_id="c0", chapter_index=0,
            subject="西泽尔", predicate="identity", value="红龙骑士团团长",
            fact_type="canon_fact", source_refs=[REF],
        ),
        FactRecord(
            fact_id="f2", chunk_id="ch001_p000", source_id="s", chapter_id="c1", chapter_index=1,
            subject="西泽尔", predicate="state", value="受伤", fact_type="canon_fact", source_refs=[REF],
        ),
    ]
    events = [
        EventRecord(
            event_id="e1", chunk_id="ch001_p000", source_id="s", chapter_id="c1", chapter_index=1,
            order_in_chapter=0, title="决斗", summary="与人对决", participants=["西泽尔", "帕西"],
            fact_type="canon_fact", source_refs=[REF],
        )
    ]
    relations = [
        RelationRecord(
            relation_id="r1", chunk_id="ch000_p000", source_id="s", chapter_id="c0", chapter_index=0,
            from_entity="西泽尔", to_entity="帕西", relation="兄弟", source_refs=[REF],
        )
    ]
    return facts, events, relations


def test_entity_profile_aggregates_facts_events_relations(tmp_path):
    facts, events, relations = _entity_payload()
    run_dir = _write_run(
        tmp_path,
        [
            _extraction(0, [_mention("m1", "西泽尔", chapter=0), _mention("m2", "帕西", chapter=0)],
                        facts=facts[:1], relations=relations),
            _extraction(1, [_mention("m3", "西泽尔", chapter=1), _mention("m4", "帕西", chapter=1)],
                        facts=facts[1:], events=events),
        ],
    )
    result = resolve(run_dir)
    xizeer = next(e for e in result.entities if e.canonical_name == "西泽尔")
    assert xizeer.first_appearance_chapter == 0
    assert xizeer.appearance_chapters == [0, 1]
    assert len(xizeer.fact_ids) == 2
    assert len(xizeer.event_ids) == 1
    assert len(xizeer.relation_ids) == 1
    assert xizeer.evidence_count > 0


def test_importance_is_normalized_to_the_top_entity(tmp_path):
    run_dir = _write_run(
        tmp_path,
        [
            _extraction(0, [_mention("m1", "西泽尔"), _mention("m2", "帕西")]),
            _extraction(1, [_mention("m3", "西泽尔"), _mention("m4", "西泽尔", chunk="ch2_p000")]),
        ],
    )
    result = resolve(run_dir)
    assert max(e.importance for e in result.entities) == 1.0
    assert all(0 < e.importance <= 1.0 for e in result.entities)


# --- 不丢实体 -------------------------------------------------------------


def test_no_entity_is_silently_dropped(tmp_path):
    """每个非泛称名字都必须出现在某个实体里，或被记入复核队列。"""
    names = ["西泽尔", "帕西", "赛兰", "尤利乌斯", "红龙", "灰港"]
    run_dir = _write_run(
        tmp_path,
        [_extraction(i, [_mention(f"m{i}", n)]) for i, n in enumerate(names)],
    )
    result = resolve(run_dir)
    covered = {e.canonical_name for e in result.entities}
    assert covered == set(names)
    assert len(result.entities) == len(names)


def test_entities_can_be_loaded_from_the_written_files(tmp_path):
    run_dir = _write_run(tmp_path, [_extraction(0, [_mention("m1", "西泽尔")])])
    resolve(run_dir)
    raw = json.loads((run_dir / "canonical" / "entities.json").read_text(encoding="utf-8"))
    entities = [CanonicalEntity.model_validate(item) for item in raw]
    assert entities[0].canonical_name == "西泽尔"


def test_canonical_files_are_written(tmp_path):
    run_dir = _write_run(tmp_path, [_extraction(0, [_mention("m1", "西泽尔")])])
    resolve(run_dir)
    for name in ("entities.json", "merge_decisions.json", "review_queue.json", "facts.json", "events.json", "relations.json"):
        assert (run_dir / "canonical" / name).is_file(), name
    assert (run_dir / "reports" / "entity_resolution.md").is_file()


# --- 错误路径 -------------------------------------------------------------


def test_missing_extraction_dir_raises(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(ResolutionError, match="extraction"):
        load_extractions(tmp_path / "run")


def test_empty_extraction_dir_raises(tmp_path):
    run_dir = _write_run(tmp_path, [])
    with pytest.raises(ResolutionError, match="没有任何分块结果"):
        load_extractions(run_dir)


def test_no_mentions_at_all_raises(tmp_path):
    run_dir = _write_run(tmp_path, [_extraction(0, [])])
    with pytest.raises(ResolutionError, match="没有任何实体提及"):
        resolve(run_dir)


def test_invalid_json_in_extraction_is_not_swallowed(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "extraction").mkdir(parents=True)
    (run_dir / "extraction" / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_extractions(run_dir)
