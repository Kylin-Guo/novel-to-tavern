"""黄金集评测：在自创的微型小说上量一次**可复现**的质量。

为什么需要它：`examples/gold/` 之前，这个项目只有「302 项单元测试通过」和
「156 章真实跑过一遍」两种证据 —— 前者测的是代码分支，后者测不出对错
（没有标准答案）。这里补上第三种：一篇**自创**的八章小说 + 手写抽取 + 手标期望，
端到端跑一遍，算出精确率/召回率。

**它测的是管线，不是模型。** 抽取结果是手写的（扮演 `llm.provider = file`），
所以这里的数字说明的是「证据定位、canon 资格、归一、时间线、起始点过滤、
导出」这一串做得对不对 —— 与「模型抽得好不好」是两回事，别混。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.export import export
from novel_to_tavern.export.startpoint import build_start_state, plan_strict, resolve_start_point
from novel_to_tavern.extract import run_extraction
from novel_to_tavern.extract.schema import EventRecord, FactRecord, RelationRecord
from novel_to_tavern.ingest import ingest
from novel_to_tavern.llm.provider import FileProvider
from novel_to_tavern.resolve import CanonicalEntity, resolve
from novel_to_tavern.timeline import build as build_timeline
from novel_to_tavern.timeline.worldbible import plan_entity_entries

GOLD = Path(__file__).resolve().parent.parent / "examples" / "gold"
NOVEL = GOLD / "灰港纪事.txt"
EXTRACTION = GOLD / "extraction.json"
EXPECTATIONS = json.loads((GOLD / "expectations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory) -> dict:
    """把整条流水线在黄金集上跑一遍，返回所有中间产物。

    模块级共享：这一套跑下来不便宜，而所有断言读的是同一份结果。
    """
    work = tmp_path_factory.mktemp("gold")
    config = config_module.Config(
        project=config_module.ProjectConfig(
            source_path=str(NOVEL), output_root=str(work / "runs")
        ),
        # 缓存必须落在 tmp 里。默认的 `./cache` 是**仓库根**下的共享目录：
        # 改了 extraction.json 之后，旧的预生成响应仍会按同一个键命中，
        # 于是测试用新 fixture 的断言去验旧 fixture 的产物 —— 会以非常难懂的方式失败。
        pipeline=config_module.PipelineConfig(cache_dir=str(work / "cache")),
    )

    run_dir, manifest = ingest(config, run_id="20260101T000000Z_a01d01", resume=False)

    # 把「手写抽取」按 chunk_id 摆成 file provider 期望的布局
    precomputed = work / "precomputed"
    precomputed.mkdir()
    by_chapter = {c["chapter_index"]: c for c in _load_extraction()}
    order = manifest.global_chapter_order()
    for chunk in manifest.chunks:
        chapter_index = order[chunk.chapter_id]
        payload = by_chapter[chapter_index]
        precomputed.joinpath(f"{chunk.chunk_id}.json").write_text(
            json.dumps(
                {
                    "summary": payload["summary"],
                    "mentions": payload["mentions"],
                    "facts": payload["facts"],
                    "events": payload["events"],
                    "relations": payload["relations"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    run_extraction(config, run_dir, FileProvider(precomputed), resume=False)
    resolution = resolve(run_dir)
    timeline = build_timeline(run_dir)
    plan = json.loads((run_dir / "worldbook" / "plan.json").read_text(encoding="utf-8"))
    facts = [
        FactRecord.model_validate(item)
        for item in json.loads((run_dir / "canonical" / "facts.json").read_text(encoding="utf-8"))
    ]
    entities = [
        CanonicalEntity.model_validate(item)
        for item in json.loads((run_dir / "canonical" / "entities.json").read_text(encoding="utf-8"))
    ]
    events = [
        EventRecord.model_validate(item)
        for item in json.loads((run_dir / "canonical" / "events.json").read_text(encoding="utf-8"))
    ]
    relations = [
        RelationRecord.model_validate(item)
        for item in json.loads((run_dir / "canonical" / "relations.json").read_text(encoding="utf-8"))
    ]
    export(run_dir, config)
    return {
        "config": config,
        "run_dir": run_dir,
        "manifest": manifest,
        "resolution": resolution,
        "timeline": timeline,
        "plan": plan,
        "facts": facts,
        "entities": entities,
        "events": events,
        "relations": relations,
    }


def _load_extraction() -> list[dict]:
    return json.loads(EXTRACTION.read_text(encoding="utf-8"))["chapters"]


def _entity_names(result: dict) -> set[str]:
    return {e["title"] for e in result["plan"]}


def _worldbook_text(result: dict) -> str:
    card = json.loads(
        (result["run_dir"] / "exports" / "world_simulator_v2.json").read_text(encoding="utf-8")
    )
    return "\n".join(
        e.get("content") or "" for e in card["data"]["character_book"]["entries"]
    )


# --- 抽取本身 --------------------------------------------------------------


def test_every_handwritten_quote_is_locatable(evaluated):
    """黄金集的前提：手写的引文必须逐字存在。有一条定位不到，后面全是噪声。"""
    facts = evaluated["facts"]
    needs_review = [f for f in facts if f.review_status != "accepted"]
    # 只有那条**故意编造**的引文应当失败
    assert len(needs_review) == 1, (
        "除故意编造的那条外，不应有别的引文定位失败："
        f"{[(f.subject, f.value) for f in needs_review]}"
    )
    assert "黑帆商会的旧部" in needs_review[0].value


def test_provider_is_recorded_as_file_not_as_a_live_call(evaluated):
    summary = (evaluated["run_dir"] / "reports" / "extraction_summary.md").read_text(encoding="utf-8")
    assert "file" in summary


# --- 事实：召回 ------------------------------------------------------------


@pytest.mark.parametrize("subject,needle", EXPECTATIONS["facts_must_appear"])
def test_expected_facts_reach_the_worldbook(evaluated, subject, needle):
    text = _worldbook_text(evaluated)
    assert needle in text, f"期望出现在世界书里的事实没出现：{subject} / {needle}"


def test_fabricated_quote_never_reaches_the_worldbook(evaluated):
    """没有证据的内容不进 canon —— 这是整个项目的核心承诺，用黄金集钉住它。"""
    text = _worldbook_text(evaluated)
    for item in EXPECTATIONS["facts_must_not_appear"]:
        assert item["value"] not in text, f"{item['reason']}：{item['value']}"


# --- 事实：精确率 ----------------------------------------------------------


def test_no_needs_review_fact_appears_in_any_entry(evaluated):
    rejected = {f.fact_id for f in evaluated["facts"] if f.review_status != "accepted"}
    assert rejected
    planned = json.loads(
        (evaluated["run_dir"] / "worldbook" / "plan.json").read_text(encoding="utf-8")
    )
    for entry in planned:
        ids = {ref.get("fact_id") for ref in entry.get("source_refs", [])}
        assert not (ids & rejected)


def test_worldbook_contains_no_entity_without_facts(evaluated):
    """零信息空壳条目不得出现。"""
    facts = evaluated["facts"]
    subjects = {f.subject for f in facts if f.review_status == "accepted" and f.fact_type == "canon_fact"}
    for title in _entity_names(evaluated):
        assert title in subjects or title in {"世界概况", "人物索引", "剧情主线（逐章）"}, title


# --- 实体：召回与精确 ------------------------------------------------------


def test_expected_entities_all_get_entries(evaluated):
    names = _entity_names(evaluated)
    missing = [n for n in EXPECTATIONS["entities_expected_in_worldbook"] if n not in names]
    assert missing == [], f"期望生成条目的实体缺了：{missing}"
    recall = 1 - len(missing) / len(EXPECTATIONS["entities_expected_in_worldbook"])
    assert recall == 1.0


def test_entities_without_facts_stay_out(evaluated):
    names = _entity_names(evaluated)
    leaked = [n for n in EXPECTATIONS["entities_expected_absent"] if n in names]
    assert leaked == [], f"这些实体不该生成条目：{leaked}"


def test_alias_is_linked_to_its_owner(evaluated):
    titles = {e["title"] for e in evaluated["plan"]}
    for owner, aliases in EXPECTATIONS["aliases_expected"].items():
        assert owner in titles, owner
        entry = next(e for e in evaluated["plan"] if e["title"] == owner)
        for alias in aliases:
            assert alias in entry["keys"], f"{alias} 没有成为 {owner} 的触发词"


def test_same_character_is_not_split_into_two_entities(evaluated):
    """召回的反面：同一个人不能因为提到方式不同就裂成两个实体。"""
    names = [e.canonical_name for e in evaluated["entities"]]
    assert names.count("凌霜") == 1
    assert names.count("阿澜") == 1


# --- 已知限制：锁定当前行为 ------------------------------------------------


def test_known_limitation_same_name_different_person_is_still_merged(evaluated):
    """码头的老周与灯塔的老周在原文明说是两个人，归一阶段仍会合并。

    这不是「通过」，是把已知限制钉住：将来修好了，这条会失败并提醒更新期望。
    """
    limitation = EXPECTATIONS["known_limitations"][0]
    merged_name = limitation["expected_current_behaviour"]["merged_into_one_entity"]
    matches = [e for e in evaluated["entities"] if e.canonical_name == merged_name]
    assert len(matches) == 1, "归一行为变了 —— 若已能区分同名不同人，请更新期望文件"
    assert len(matches[0].appearance_chapters) >= 2


# --- 时间线与冲突 ----------------------------------------------------------


def test_expected_contradiction_is_reported(evaluated):
    pairs = {
        (c["subject"], c["predicate"])
        for c in json.loads(
            (evaluated["run_dir"] / "canonical" / "contradictions.json").read_text(encoding="utf-8")
        )
    }
    for subject, predicate in EXPECTATIONS["contradictions_expected"]:
        assert (subject, predicate) in pairs, f"没有报出冲突：{subject}.{predicate}"


def test_no_absolute_dates_are_invented(evaluated):
    for event in evaluated["timeline"]["timeline"]:
        assert event.occurred_at is None


def test_relative_time_is_kept_as_written(evaluated):
    relatives = {e.relative_time for e in evaluated["timeline"]["timeline"] if e.relative_time}
    assert relatives, "原文有「三天后」「九天」这类表述，应当被抓到"


# --- 知识边界 --------------------------------------------------------------


def test_knowledge_statuses_match_expectations(evaluated):
    knowledge = json.loads(
        (evaluated["run_dir"] / "canonical" / "knowledge.json").read_text(encoding="utf-8")
    )
    for expected in EXPECTATIONS["knowledge_expected"]:
        statuses = {item["knowledge_status"] for item in knowledge.get(expected["entity"], [])}
        assert expected["status"] in statuses, (
            f"{expected['entity']} 期望有 {expected['status']} 状态"
            f"（{expected['reason']}），实际是 {sorted(statuses)}"
        )


def test_event_participants_are_candidates_not_established_knowledge(evaluated):
    knowledge = json.loads(
        (evaluated["run_dir"] / "canonical" / "knowledge.json").read_text(encoding="utf-8")
    )
    for expected in EXPECTATIONS["knowledge_candidates_expected"]:
        items = [
            item
            for item in knowledge.get(expected["entity"], [])
            if item["item_type"] == expected["item_type"]
        ]
        assert items, f"{expected['entity']} 没有 {expected['item_type']} 记录"
        assert all(item["candidate"] for item in items), expected["reason"]
        assert all(item["acquired_at_chapter"] is None for item in items)


# --- 起始点 ----------------------------------------------------------------


def test_start_point_blocks_the_secret_until_its_reveal_chapter(evaluated):
    """第 4 章才揭示的秘密，在第 1–3 章的严格档里必须一个字都没有。"""
    spec = EXPECTATIONS["start_point_leak_probes"]
    start = resolve_start_point(
        mode="chapter",
        chapter_index=spec["start_chapter_index"],
        digests_chapters=sorted({e.chapter_index for e in evaluated["events"]})
        or list(range(8)),
    )
    plan = plan_strict(
        entities=evaluated["entities"],
        facts=evaluated["facts"],
        events=evaluated["events"],
        digests=[],
        start=start,
    )
    rendered = "\n".join(e.content_runtime for e in plan.entries)
    for marker in spec["markers_that_must_be_absent"]:
        assert marker not in rendered, f"起点之前的条目里出现了后面的内容：{marker}"
    for marker in spec["markers_that_must_be_present"]:
        assert marker in rendered, f"起点之前本该有的内容丢了：{marker}"


def test_start_state_counts_facts_on_both_sides(evaluated):
    start = resolve_start_point(
        mode="chapter", chapter_index=2, digests_chapters=list(range(8))
    )
    plan = plan_strict(
        entities=evaluated["entities"],
        facts=evaluated["facts"],
        events=evaluated["events"],
        digests=[],
        start=start,
    )
    state = build_start_state(
        start=start,
        plan=plan,
        facts=evaluated["facts"],
        events=evaluated["events"],
        relations=evaluated["relations"],
        knowledge={},
    )
    assert state.facts_included + state.facts_excluded == len(evaluated["facts"])
    assert set(state.active_fact_ids).isdisjoint(state.hidden_fact_ids)


# --- 导出 ------------------------------------------------------------------


def test_exported_card_passes_strict_validation(evaluated):
    from novel_to_tavern.tavern import CardV2, validate_card

    card = CardV2.model_validate(
        json.loads(
            (evaluated["run_dir"] / "exports" / "world_simulator_v2.json").read_text(encoding="utf-8")
        )
    )
    assert validate_card(card, strict=True).ok


def test_reports_state_the_metric_boundary(evaluated):
    audit = (evaluated["run_dir"] / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "引文逐字定位率" in audit
    assert "不是事实正确率" in audit or "不**说明什么" in audit


def test_gold_run_is_deterministic(tmp_path):
    """同样的输入 + 同样的手写抽取 → 同样的条目正文。"""
    def run_once(where: Path) -> str:
        config = config_module.Config(
            project=config_module.ProjectConfig(
                source_path=str(NOVEL), output_root=str(where / "runs")
            )
        )
        run_dir, manifest = ingest(config, run_id="20260101T000000Z_de7001", resume=False)
        precomputed = where / "precomputed"
        precomputed.mkdir(parents=True, exist_ok=True)
        by_chapter = {c["chapter_index"]: c for c in _load_extraction()}
        order = manifest.global_chapter_order()
        for chunk in manifest.chunks:
            payload = by_chapter[order[chunk.chapter_id]]
            (precomputed / f"{chunk.chunk_id}.json").write_text(
                json.dumps({k: payload[k] for k in ("summary", "mentions", "facts", "events", "relations")},
                           ensure_ascii=False),
                encoding="utf-8",
            )
        run_extraction(config, run_dir, FileProvider(precomputed), resume=False)
        resolve(run_dir)
        build_timeline(run_dir)
        export(run_dir, config)
        return (run_dir / "exports" / "world_simulator_v2.json").read_text(encoding="utf-8")

    first = run_once(tmp_path / "a")
    second = run_once(tmp_path / "b")
    assert first == second
