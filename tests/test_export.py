"""导出：开场白可选起点、完整剧情在卡内、校验不过就不产出。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.export import (
    CARD_NAME,
    CORE_RULES,
    PLOT_ENTRY_KEYS,
    PLOT_ENTRY_MUST_NOT_TRIGGER,
    WORLDBOOK_AFTER_END,
    WORLDBOOK_BEGINNING,
    WORLDBOOK_NAME,
    ChapterDigest,
    ExportError,
    build_core_rules_entry,
    build_exports,
    build_greetings,
    build_plot_entry,
    export,
    plan_to_drafts,
)
from novel_to_tavern.extract.schema import EventRecord, FactRecord, RelationRecord, SourceRef
from novel_to_tavern.resolve import CanonicalEntity
from novel_to_tavern.tavern import CardV2, validate_card, validate_parity
from novel_to_tavern.tavern.wi_standalone import WorldbookFile
from novel_to_tavern.timeline.build import TimelineEvent
from novel_to_tavern.timeline.worldbible import PlannedEntry


def _digests(n: int = 10) -> list[ChapterDigest]:
    return [
        ChapterDigest(
            chapter_index=i,
            label=f"第{i + 1}章",
            summary=f"第{i + 1}章发生的事情概述。",
            title=f"标题{i + 1}",
        )
        for i in range(n)
    ]


def _entity(eid: str, name: str, kind="character", evidence=5, aliases=()):
    return CanonicalEntity(
        id=eid, kind=kind, canonical_name=name, aliases=list(aliases),
        appearance_chapters=[0], first_appearance_chapter=0, evidence_count=evidence, importance=0.5,
    )


def _timeline(n: int = 10) -> list[TimelineEvent]:
    return [
        TimelineEvent(
            event_id=f"e{i}", chapter_index=i, chapter_id=f"c{i}", order_in_chapter=0,
            title=f"事件{i + 1}", summary=f"第{i + 1}章的事件。", participants=["甲"],
            revealed_at_chapter=i,
        )
        for i in range(n)
    ]


# --- 开场白 ---------------------------------------------------------------


def test_greetings_offer_two_explicit_start_points():
    greetings = build_greetings(
        book_title="测试书", digests=_digests(), entities=[_entity("ent_0001", "甲")], timeline=_timeline()
    )
    assert "从故事的开头开始" in greetings.first_mes
    assert "从故事的最终结尾之后开始" in greetings.first_mes
    assert "回复 **1** 或 **2**" in greetings.first_mes
    assert len(greetings.alternate_greetings) == 2


def test_alternate_greetings_name_their_chapter():
    greetings = build_greetings(
        book_title="测试书", digests=_digests(10), entities=[], timeline=_timeline()
    )
    assert "第1章" in greetings.alternate_greetings[0]
    assert "第10章" in greetings.alternate_greetings[1]


def test_greetings_allow_starting_from_any_chapter():
    greetings = build_greetings(
        book_title="测试书", digests=_digests(), entities=[], timeline=_timeline()
    )
    assert "中间某一章" in greetings.first_mes


def test_greetings_require_digests():
    with pytest.raises(ValueError):
        build_greetings(book_title="x", digests=[], entities=[], timeline=[])


# --- 核心规则与剧情 -------------------------------------------------------


def test_core_rules_forbid_leaking_future_events():
    assert "尚未发生" in CORE_RULES
    assert "只知道" in CORE_RULES
    assert "不得" in CORE_RULES


def test_core_rules_forbid_speaking_for_the_user():
    assert "用户独占" in CORE_RULES


def test_plot_entry_contains_every_chapter():
    """「必须包含当前完整剧情走向」：逐章都要在卡里。"""
    entry = build_plot_entry(_digests(30))
    assert entry is not None
    for i in range(30):
        assert f"第{i + 1}章" in entry.content_runtime


def test_plot_entry_is_triggered_not_always_on():
    entry = build_plot_entry(_digests())
    assert entry.always_on is False
    assert entry.keys


def test_core_rules_contain_only_rules_not_a_plot_outline():
    """条目叫「世界运行规则」，内容就该只有规则 —— 不能塞逐章大纲。"""
    from novel_to_tavern.export.builder import CORE_RULES

    entry = build_core_rules_entry()
    assert "第1章" not in entry.content_runtime
    assert "章：" not in entry.content_runtime
    assert CORE_RULES in entry.content_runtime


# --- 主线条目：误触发一次就是 2.5 万字 ---------------------------------------


@pytest.mark.parametrize("message", PLOT_ENTRY_MUST_NOT_TRIGGER)
def test_ordinary_chat_does_not_pull_in_the_whole_plot(message):
    """常见的自然说法一个都不许命中主线条目。

    「剧情主线」条目是整本书的逐章走向。早先的触发词含「剧情」「主线」「前情」，
    于是「这个剧情怎么发展」「主线任务是什么」「前情回顾」全都会把它拉进上下文。
    """
    entry = build_plot_entry(_digests())
    assert entry is not None
    hits = [k for k in entry.keys if k in message]
    assert hits == [], f"{message!r} 命中了主线条目触发词 {hits}（会灌进整本书剧情）"


def test_an_explicit_request_does_trigger_the_plot_entry():
    """收窄不能收成「用户要也要不到」。"""
    entry = build_plot_entry(_digests())
    assert entry is not None
    for message in ("给我原著逐章大纲", "看一下原著大纲", "全书大纲发我", "剧情主线是什么"):
        assert any(k in message for k in entry.keys), f"{message!r} 应当命中主线条目"


def test_plot_keys_are_all_multi_word_compounds():
    """触发词必须都是组合词 —— 单个常用词在中文对白里必然误伤。"""
    for key in PLOT_ENTRY_KEYS:
        assert len(key) >= 4, f"触发词 {key!r} 太短，容易在日常对白里命中"
    for banned in ("剧情", "主线", "前情", "故事线"):
        assert banned not in PLOT_ENTRY_KEYS, f"{banned!r} 是自然对白高频词，不能作触发词"


def test_plot_entry_trigger_cost_is_stated_in_its_flags():
    """卡里要写清楚这个条目有多重，别让用户自己发现。"""
    entry = build_plot_entry(_digests())
    assert entry is not None
    assert entry.quality_flags


# --- 导出物 ---------------------------------------------------------------


def _plan(n_entities: int = 5) -> list[PlannedEntry]:
    entries = [
        PlannedEntry(
            entry_id="wb_overview", category="world_overview", title="世界概况",
            content_runtime="地点：某城", content_canonical="", always_on=True,
        ),
        PlannedEntry(
            entry_id="wb_index_characters", category="character_index", title="人物索引",
            content_runtime="甲、乙", content_canonical="", always_on=True,
        ),
    ]
    for i in range(n_entities):
        entries.append(
            PlannedEntry(
                entry_id=f"wb_entity_ent_{i:04d}", category="character", title=f"角色{i}",
                content_runtime=f"identity：角色{i}的描述", content_canonical="",
                keys=[f"角色{i}"], always_on=False, valid_from_chapter=i,
            )
        )
    return entries


def _greetings() -> object:
    return build_greetings(
        book_title="测试书", digests=_digests(), entities=[_entity("ent_0001", "甲")], timeline=_timeline()
    )


def test_card_and_worldbook_are_consistent():
    card, book = build_exports(book_title="测试书", entries=_plan(), greetings=_greetings())
    assert validate_card(card, strict=True).ok
    assert len(card.data.character_book.entries) == len(book.entries)
    assert validate_parity(card, book).ok


def test_exactly_three_always_on_entries():
    """常驻条目数要留在配置上限内。"""
    from novel_to_tavern.export.builder import build_core_rules_entry

    entries = [build_core_rules_entry(), *_plan()]
    card, _ = build_exports(book_title="测试书", entries=entries, greetings=_greetings())
    always_on = [e for e in card.data.character_book.entries if e.constant]
    assert len(always_on) == 3


def test_always_on_entries_are_placed_before_the_character_block():
    from novel_to_tavern.export.builder import build_core_rules_entry

    entries = [build_core_rules_entry(), *_plan()]
    card, _ = build_exports(book_title="测试书", entries=entries, greetings=_greetings())
    for entry in card.data.character_book.entries:
        if entry.constant:
            assert entry.position == "before_char"
        else:
            assert entry.position == "after_char"


def test_entry_keys_allow_triggering_by_name():
    card, _ = build_exports(book_title="测试书", entries=_plan(), greetings=_greetings())
    keys = {k for e in card.data.character_book.entries for k in e.keys}
    assert "角色0" in keys


def test_every_entry_has_a_readable_title():
    card, _ = build_exports(book_title="测试书", entries=_plan(), greetings=_greetings())
    for entry in card.data.character_book.entries:
        assert entry.comment.strip()


def test_zero_entries_is_rejected_before_writing():
    """没有条目就不该产出卡。"""
    card, _ = build_exports(book_title="测试书", entries=[], greetings=_greetings())
    report = validate_card(card, strict=True)
    assert any("没有任何条目" in w for w in report.warnings)


# --- 端到端 ---------------------------------------------------------------


def _prepare_run(tmp_path: Path, chapters: int = 6) -> Path:
    run = tmp_path / "run"
    for sub in ("canonical", "worldbook", "reports", "extraction"):
        (run / sub).mkdir(parents=True)

    (run / "manifest.json").write_text(
        json.dumps({
            "sources": [{"source_id": "s", "sha256": "abc", "filename": "测试书Ⅰ：某卷.txt"}],
            "config_fingerprint": "fp",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    for i in range(chapters):
        (run / "extraction" / f"ch{i:04d}_p000.json").write_text(
            json.dumps({
                "chunk_id": f"ch{i:04d}_p000", "chapter_index": i, "chapter_title": f"标题{i + 1}",
                "summary": f"第{i + 1}章概述。", "provider": "stub", "prompt_version": "extract-v1",
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    # id 必须互不相同：条目 id 由实体 id 派生，撞 id 会让后面的条目顶掉前面的。
    entities = [_entity("ent_0000", "甲")]
    for i in range(1, chapters):
        entities.append(
            CanonicalEntity(
                id=f"ent_{i:04d}",
                kind="character",
                canonical_name=f"角色{i}",
                appearance_chapters=[i],
                first_appearance_chapter=i,
                evidence_count=5,
                importance=0.5,
            )
        )
    (run / "canonical" / "entities.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in entities], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "canonical" / "timeline.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in _timeline(chapters)], ensure_ascii=False),
        encoding="utf-8",
    )

    # 严格起始点路径要用的逐条事实：每章两条，取值里带该章独有的标记串。
    facts = []
    for i in range(chapters):
        name = "甲" if i == 0 else f"角色{i}"
        for suffix, predicate in (("a", "state"), ("b", "background")):
            facts.append(
                FactRecord(
                    fact_id=f"f{i}_{suffix}", chunk_id=f"ch{i:04d}_p000", source_id="s",
                    chapter_id=f"c{i}", chapter_index=i, subject=name, predicate=predicate,
                    value=f"{_marker(i)}的{predicate}", fact_type="canon_fact",
                    source_refs=[SourceRef(source_id="s", chapter_id=f"c{i}", start_line=1, end_line=2, quote="q")],
                )
            )
    (run / "canonical" / "facts.json").write_text(
        json.dumps([f.model_dump(mode="json") for f in facts], ensure_ascii=False), encoding="utf-8"
    )
    (run / "canonical" / "events.json").write_text(
        json.dumps([
            EventRecord(
                event_id=f"ev{i}", chunk_id=f"ch{i:04d}_p000", source_id="s", chapter_id=f"c{i}",
                chapter_index=i, order_in_chapter=0, title=f"事件{i + 1}",
                summary=f"{_marker(i)}发生的事", fact_type="canon_fact",
                source_refs=[SourceRef(source_id="s", chapter_id=f"c{i}", start_line=1, end_line=2, quote="q")],
            ).model_dump(mode="json")
            for i in range(chapters)
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "canonical" / "relations.json").write_text(
        json.dumps([
            RelationRecord(
                relation_id=f"r{i}", chunk_id=f"ch{i:04d}_p000", source_id="s", chapter_id=f"c{i}",
                chapter_index=i, from_entity="甲", to_entity="甲", relation="自己",
                source_refs=[SourceRef(source_id="s", chapter_id=f"c{i}", start_line=1, end_line=2, quote="q")],
            ).model_dump(mode="json")
            for i in range(chapters)
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "worldbook" / "plan.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in _plan()], ensure_ascii=False),
        encoding="utf-8",
    )
    return run


def _marker(chapter: int) -> str:
    """每章独有的标记串 —— 严格档的对抗性断言靠它。"""
    return f"〈第{chapter + 1}章独有ZZ{chapter}ZZ〉"


def test_export_writes_all_artifacts(tmp_path):
    run = _prepare_run(tmp_path)
    result = export(run, config_module.Config())
    exports = run / "exports"
    for name in (CARD_NAME, WORLDBOOK_NAME, WORLDBOOK_BEGINNING, WORLDBOOK_AFTER_END, "timeline.json", "export_manifest.json"):
        assert (exports / name).is_file(), name
    assert (run / "reports" / "audit.md").is_file()
    assert result["entries"]


def test_exported_card_is_valid_and_parses_back(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    raw = json.loads((run / "exports" / CARD_NAME).read_text(encoding="utf-8"))
    card = CardV2.model_validate(raw)
    assert validate_card(card, strict=True).ok
    assert raw["spec"] == "chara_card_v2"
    assert raw["spec_version"] == "2.0"


def test_standalone_worldbook_parity_holds_on_disk(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    card = CardV2.model_validate(json.loads((run / "exports" / CARD_NAME).read_text(encoding="utf-8")))
    book = WorldbookFile.model_validate(
        json.loads((run / "exports" / WORLDBOOK_NAME).read_text(encoding="utf-8"))
    )
    assert validate_parity(card, book).ok


def test_beginning_worldbook_blocks_later_chapters(tmp_path):
    run = _prepare_run(tmp_path)
    result = export(run, config_module.Config())
    assert result["blocked_begin"]
    begin = WorldbookFile.model_validate(
        json.loads((run / "exports" / WORLDBOOK_BEGINNING).read_text(encoding="utf-8"))
    )
    full = WorldbookFile.model_validate(
        json.loads((run / "exports" / WORLDBOOK_NAME).read_text(encoding="utf-8"))
    )
    assert len(begin.entries) < len(full.entries)


def test_export_manifest_contains_no_credentials(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    text = (run / "exports" / "export_manifest.json").read_text(encoding="utf-8")
    assert "api_key" not in text.lower()
    assert "NOVEL_TAVERN_API_KEY" not in text


def test_audit_states_exactly_how_far_tavo_was_verified(tmp_path):
    """只验证到「导入成功」就不能说更多 —— 触发与剧透纪律都还没验。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "只验证到「导入成功」" in audit
    assert "都还没验证" in audit
    assert "粗估" in audit


def test_audit_states_both_start_points(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "从故事开头开始" in audit
    assert "从故事最终结局之后开始" in audit


def test_export_refuses_when_upstream_missing(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(ExportError, match="缺少上游产物"):
        export(tmp_path / "run", config_module.Config())


def test_export_refuses_without_chapter_digests(tmp_path):
    run = _prepare_run(tmp_path)
    for path in (run / "extraction").glob("*.json"):
        path.unlink()
    with pytest.raises(ExportError, match="没有章节摘要"):
        export(run, config_module.Config())


def test_plan_to_drafts_orders_entries_deterministically():
    drafts = plan_to_drafts(_plan(3))
    assert [d.entry_id for d in drafts] == [e.entry_id for e in _plan(3)]
    assert [d.insertion_order for d in drafts] == sorted(d.insertion_order for d in drafts)


# --- 严格起始点（端到端） --------------------------------------------------


def _all_entry_text(path: Path) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw["data"]["character_book"]["entries"]
    return "\n".join(e.get("content") or "" for e in entries) + "\n" + json.dumps(
        raw["data"].get("first_mes", ""), ensure_ascii=False
    )


def test_strict_export_writes_its_own_artifacts(tmp_path):
    run = _prepare_run(tmp_path)
    result = export(run, config_module.Config(), start_chapter=1)
    assert result["strict"] is not None
    for name in result["strict"]["files"]:
        assert (run / "exports" / name).is_file(), name
    assert result["strict"]["files"][0] == "card_start_chapter_2.json"


def test_strict_card_contains_no_marker_from_later_chapters(tmp_path):
    """核心断言：起点之后的内容**不在文件里**，不是「在但标明别看」。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=1)
    text = _all_entry_text(run / "exports" / "card_start_chapter_2.json")
    for later in range(2, 6):
        assert _marker(later) not in text, f"第 {later + 1} 章的内容泄漏进严格档卡片"
    assert _marker(0) in text and _marker(1) in text


def test_strict_card_carries_fewer_entity_entries_than_the_full_view(tmp_path):
    """严格档的「变小」体现在实体条目数与剧情长度上，不是整卡字符数
    —— 核心规则与开场白无论哪一档都在。"""
    from novel_to_tavern.timeline.worldbible import plan_entity_entries
    from novel_to_tavern.extract.schema import FactRecord
    from novel_to_tavern.resolve import CanonicalEntity

    run = _prepare_run(tmp_path)
    entities = [CanonicalEntity.model_validate(e) for e in json.loads(
        (run / "canonical" / "entities.json").read_text(encoding="utf-8"))]
    facts = [FactRecord.model_validate(f) for f in json.loads(
        (run / "canonical" / "facts.json").read_text(encoding="utf-8"))]

    full = plan_entity_entries(entities, facts)
    cut = plan_entity_entries(entities, facts, start_chapter=1)
    assert 0 < len(cut) < len(full)
    assert {e.title for e in cut} == {"甲", "角色1"}

    full_plot = build_plot_entry(_digests(6))
    cut_plot = build_plot_entry(_digests(6), upto_chapter=1)
    assert len(cut_plot.content_runtime) < len(full_plot.content_runtime)


def test_strict_card_offers_no_alternate_start_points(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=1)
    raw = json.loads((run / "exports" / "card_start_chapter_2.json").read_text(encoding="utf-8"))
    assert raw["data"].get("alternate_greetings") in (None, [])
    assert "从故事的最终结尾之后开始" not in raw["data"]["first_mes"]


def test_strict_card_is_structurally_valid(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=1)
    card = CardV2.model_validate(
        json.loads((run / "exports" / "card_start_chapter_2.json").read_text(encoding="utf-8"))
    )
    assert validate_card(card, strict=True).ok


def test_strict_start_state_records_what_is_hidden(tmp_path):
    run = _prepare_run(tmp_path)
    result = export(run, config_module.Config(), start_chapter=1)
    state = result["strict"]["state"]
    assert state.facts_included == 4  # 第 1–2 章各 2 条
    assert state.facts_excluded == 8
    assert set(state.active_fact_ids).isdisjoint(state.hidden_fact_ids)
    assert state.strict is True


def test_strict_manifest_states_the_guarantee(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=1)
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    block = manifest["strict_start_point"]
    assert block["enabled"] is True
    assert block["facts_excluded"] == 8
    assert "结构性" in block["guarantee"]
    listed = {entry["name"]: entry for entry in manifest["outputs"]}
    for name in block["files"]:
        assert name in listed
        assert listed[name]["exists"] is True
        assert len(listed[name]["sha256"]) == 64


def test_every_output_is_hashed_and_really_exists(tmp_path):
    """只记文件名的话，清单回答不了「我手上这张卡是不是这次生成的」。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))

    imports = run / "exports"
    for entry in manifest["outputs"]:
        assert set(entry) == {"name", "sha256", "bytes", "exists"}
        path = imports / entry["name"]
        assert path.is_file() is entry["exists"]
        if entry["exists"]:
            data = path.read_bytes()
            assert entry["bytes"] == len(data)
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()


def test_default_start_point_declares_no_structural_guarantee(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    block = manifest["strict_start_point"]
    assert block["enabled"] is False
    assert "无结构性保证" in block["guarantee"]


def test_default_export_declares_strict_disabled(tmp_path):
    """没指定起始点时必须如实标注「尽力而为」，不能默认写成有保证。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["strict_start_point"]["enabled"] is False
    assert "尽力而为" in manifest["strict_start_point"]["note"]


def test_strict_audit_reports_dropped_and_truncated(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=1)
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "严格起始点产物（结构性无剧透）" in audit
    assert "删了什么" in audit
    assert "被整条删去的条目" in audit


def test_out_of_range_start_chapter_is_refused(tmp_path):
    run = _prepare_run(tmp_path, chapters=6)
    with pytest.raises(ExportError, match="起始点无效"):
        export(run, config_module.Config(), start_chapter=99)


def test_strict_export_is_deterministic(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config(), start_chapter=2)
    first = (run / "exports" / "card_start_chapter_3.json").read_text(encoding="utf-8")
    export(run, config_module.Config(), start_chapter=2)
    assert (run / "exports" / "card_start_chapter_3.json").read_text(encoding="utf-8") == first


# --- 指标口径 --------------------------------------------------------------


def test_manifest_names_the_location_metric_precisely(tmp_path):
    """「引文定位率」必须叫得像它本来的意思，不能让人读成事实正确率。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    metrics = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))["metrics"]
    assert "quote_location_success_rate" in metrics
    assert "不是事实正确率" in metrics["quote_location_success_rate_meaning"]
    assert metrics["quotes_total"] >= metrics["quotes_located"] >= 0


def test_manifest_says_semantic_check_was_not_executed(tmp_path):
    """没跑 verify 就写「未执行」，不能写 0 分让人以为跑过且全错。"""
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    semantic = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))[
        "metrics"
    ]["semantic_support"]
    assert semantic["executed"] is False
    assert "未执行" in semantic["note"]


def test_audit_states_the_metric_boundary(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "指标口径" in audit
    assert "说明什么" in audit and "不**说明什么" in audit
    assert "引文逐字定位率" in audit
    assert "不是**已人工审校**" in audit or "**不是**「已人工审校」" in audit


# --- 触发与预算报告 --------------------------------------------------------


def test_export_writes_a_trigger_budget_report(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    report = (run / "reports" / "worldbook_budget.md").read_text(encoding="utf-8")
    assert "触发与上下文预算体检" in report
    assert "常驻预算" in report
    assert "最坏情况" in report
    assert "粗估" in report


def test_budget_report_probes_the_protagonist_and_idle_chat(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    report = (run / "reports" / "worldbook_budget.md").read_text(encoding="utf-8")
    assert "探测句" in report
    assert "甲是谁？" in report


def test_budget_report_flags_always_on_over_budget(tmp_path):
    """常驻内容每轮都在上下文里，超预算必须显式报出来。"""
    run = _prepare_run(tmp_path)
    config = config_module.Config()
    config = config.model_copy(
        update={"worldbook": config.worldbook.model_copy(update={"max_always_on_tokens": 1})}
    )
    export(run, config)
    report = (run / "reports" / "worldbook_budget.md").read_text(encoding="utf-8")
    assert "超出上限" in report


# --- 运行溯源 --------------------------------------------------------------


def test_manifest_records_provenance(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    prov = manifest["provenance"]
    assert prov["extraction"]["providers"] == {"stub": 6}
    assert prov["extraction"]["prompt_versions"] == {"extract-v1": 6}
    assert prov["extraction"]["prompt_template_sha256"]
    assert "file" not in prov["extraction"]["providers"]
    assert prov["verification"]["executed"] is False
    assert prov["package_version"]


def test_provenance_notes_when_results_come_from_precomputed_files(tmp_path):
    run = _prepare_run(tmp_path)
    for path in (run / "extraction").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["provider"] = "file"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    export(run, config_module.Config())
    prov = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))[
        "provenance"
    ]
    assert "预生成响应" in prov["extraction"]["provider_note"]


def test_manifest_lists_the_cache_invalidation_keys(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    keys = manifest["provenance"]["cache_invalidation_keys"]
    assert "提示词模板 hash" in keys
    assert "输出 schema 版本" in keys


def test_provenance_records_no_credentials(tmp_path):
    """注释里出现「authorization」这个词没关系，关键是没有真正的凭据形状。"""
    from novel_to_tavern.tavern import validate_no_secrets

    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    text = (run / "exports" / "export_manifest.json").read_text(encoding="utf-8")
    assert validate_no_secrets(text).ok
    lowered = text.lower()
    assert "sk-" not in lowered
    assert "bearer " not in lowered
    assert "api_key_env" not in lowered


# --- 游玩模式 --------------------------------------------------------------


def test_card_description_states_the_play_mode(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    card = json.loads((run / "exports" / CARD_NAME).read_text(encoding="utf-8"))
    assert "游玩模式" in card["data"]["description"]
    assert "分支线" in card["data"]["description"]


def test_manifest_records_the_play_mode_and_its_limits(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    block = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))[
        "play_mode"
    ]
    assert block["mode"] == "branch_start"
    assert "这是设计意图" in block["caveat"]
    assert "canon_fact" in block["canon_policy"]
    assert "只增不改" in block["branch_policy"]


def test_the_canon_mode_admits_it_is_not_plot_level_enforcement():
    """最容易被误读成「强制按原著走」的是 canon_start —— 它必须自己说清楚不是。"""
    from novel_to_tavern.export.playmode import MODE_SPEC

    spec = MODE_SPEC["canon_start"]
    assert "不是" in spec["caveat"]
    assert "分支" in spec["caveat"]


def test_audit_states_the_play_mode(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "## 游玩模式" in audit
    assert "canon 策略" in audit
    assert "分支策略" in audit


@pytest.mark.parametrize("mode,label", [
    ("canon_start", "严格原著线"),
    ("branch_start", "分支线（默认）"),
    ("freeform_start", "自由线"),
])
def test_each_mode_has_its_own_honest_promise(tmp_path, mode, label):
    run = _prepare_run(tmp_path)
    config = config_module.Config()
    config = config.model_copy(
        update={"project": config.project.model_copy(update={"mode": mode})}
    )
    export(run, config)
    card = json.loads((run / "exports" / CARD_NAME).read_text(encoding="utf-8"))
    assert label in card["data"]["description"]


def test_no_mode_promises_that_the_plot_will_be_followed(tmp_path):
    """任何模式都不能承诺「剧情不会偏离原著」—— 用户一开口就已经在分支了。"""
    from novel_to_tavern.export.playmode import MODE_SPEC

    for mode, spec in MODE_SPEC.items():
        blob = spec["promise"] + spec["caveat"]
        for forbidden in ("保证不偏离", "不会偏离原著", "必定遵循原著"):
            assert forbidden not in blob, f"{mode} 的措辞过头了：{forbidden}"


def test_non_canon_fact_types_never_reach_entry_bodies():
    """分支/用户新增的内容与原著事实必须保持可分离。"""
    from novel_to_tavern.resolve.entities import CanonicalEntity
    from novel_to_tavern.timeline.worldbible import plan_entity_entries

    entity = CanonicalEntity(
        id="e1", kind="character", canonical_name="甲",
        appearance_chapters=[0], first_appearance_chapter=0, evidence_count=5,
    )
    ref = SourceRef(source_id="s", chapter_id="c0", start_line=1, end_line=2, quote="q")
    facts = []
    for i, ftype in enumerate(("canon_fact", "canon_fact", "user_added", "reconstructed", "inference", "rumor")):
        facts.append(
            FactRecord(
                fact_id=f"f{i}", chunk_id="ch0_p000", source_id="s", chapter_id="c0",
                chapter_index=0, subject="甲", predicate=f"p{i}", value=f"取值{i}",
                fact_type=ftype, source_refs=[ref],
            )
        )
    entries = plan_entity_entries([entity], facts)
    assert entries
    body = entries[0].content_runtime
    assert "取值0" in body and "取值1" in body
    for leaked in ("取值2", "取值3", "取值4", "取值5"):
        assert leaked not in body, f"{leaked} 不是 canon，不该进条目正文"
