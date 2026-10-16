"""导出：开场白可选起点、完整剧情在卡内、校验不过就不产出。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.export import (
    CARD_NAME,
    CORE_RULES,
    WORLDBOOK_AFTER_END,
    WORLDBOOK_BEGINNING,
    WORLDBOOK_NAME,
    ChapterDigest,
    ExportError,
    build_exports,
    build_greetings,
    build_plot_entry,
    export,
    plan_to_drafts,
    plot_skeleton_text,
)
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


def test_plot_skeleton_is_compact():
    text = plot_skeleton_text(_digests(156))
    assert text.count("\n") < 20
    assert "剧情主线" in text


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

    entries = [build_core_rules_entry(_digests()), *_plan()]
    card, _ = build_exports(book_title="测试书", entries=entries, greetings=_greetings())
    always_on = [e for e in card.data.character_book.entries if e.constant]
    assert len(always_on) == 3


def test_always_on_entries_are_placed_before_the_character_block():
    from novel_to_tavern.export.builder import build_core_rules_entry

    entries = [build_core_rules_entry(_digests()), *_plan()]
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

    (run / "canonical" / "entities.json").write_text(
        json.dumps([_entity("ent_0001", "甲").model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "canonical" / "timeline.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in _timeline(chapters)], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "worldbook" / "plan.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in _plan()], ensure_ascii=False),
        encoding="utf-8",
    )
    return run


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


def test_audit_states_tavo_is_untested(tmp_path):
    run = _prepare_run(tmp_path)
    export(run, config_module.Config())
    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "尚未在 Tavo 实测" in audit
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
