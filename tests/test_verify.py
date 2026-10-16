"""语义支持校验：引文存在 ≠ 主张成立。

这一层的存在理由就是那个区别。测试也围绕它：判定要如实落档，
解析失败**不能**被当成通过，没跑过就要写「未执行」而不是 0 分。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern.extract.schema import FactRecord, SourceRef
from novel_to_tavern.llm.provider import Completion, ProviderError
from novel_to_tavern.verify import (
    SemanticReport,
    VerificationError,
    high_impact_facts,
    load_verdicts,
    run_verification,
)
from novel_to_tavern.verify.runner import is_high_impact, render_report
from novel_to_tavern.verify.schema import PROBLEM_VERDICTS


class StubProvider:
    """按 fact_id 返回预置判定的假引擎。"""

    name = "stub"

    def __init__(self, verdicts: dict[str, dict], *, fail: set[str] = frozenset(), garbage: set[str] = frozenset()):
        self.verdicts = verdicts
        self.fail = fail
        self.garbage = garbage
        self.calls: list[str] = []

    def complete(self, *, chunk_id: str, system_prompt: str, user_prompt: str) -> Completion:
        self.calls.append(chunk_id)
        fact_id = chunk_id.removeprefix("verify_")
        if fact_id in self.fail:
            raise ProviderError("模拟调用失败")
        if fact_id in self.garbage:
            return Completion(text="我不知道该说什么", model="stub-1")
        payload = self.verdicts.get(fact_id, {"verdict": "entailed", "reason": "引文直接支持", "confidence": 0.9})
        return Completion(text=json.dumps(payload, ensure_ascii=False), model="stub-1")


def _ref(quote: str = "他在塔上说了那句话。") -> SourceRef:
    return SourceRef(source_id="s", chapter_id="c0", start_line=1, end_line=2, quote=quote)


def _fact(fid: str, *, subject="甲", predicate="state", value="受伤", fact_type="canon_fact", quote="他在塔上说了那句话。"):
    return FactRecord(
        fact_id=fid, chunk_id="ch0_p000", source_id="s", chapter_id="c0", chapter_index=0,
        subject=subject, predicate=predicate, value=value, fact_type=fact_type,
        source_refs=[_ref(quote)] if quote else [],
    )


def _prepare_run(tmp_path: Path, facts: list[FactRecord]) -> Path:
    run = tmp_path / "run"
    (run / "canonical").mkdir(parents=True)
    (run / "reports").mkdir(parents=True)
    (run / "canonical" / "facts.json").write_text(
        json.dumps([f.model_dump(mode="json") for f in facts], ensure_ascii=False), encoding="utf-8"
    )
    return run


# --- 高风险识别 ------------------------------------------------------------


@pytest.mark.parametrize(
    "predicate", ["identity", "death", "secret", "relationship", "ability", "status", "affiliation"]
)
def test_high_impact_predicates_are_flagged(predicate):
    assert is_high_impact(_fact("f1", predicate=predicate))


def test_ordinary_predicates_are_not_flagged():
    assert not is_high_impact(_fact("f1", predicate="location", value="在城堡里"))


def test_high_impact_marker_in_value_is_flagged():
    assert is_high_impact(_fact("f1", predicate="note", value="他其实是叛徒"))


def test_high_impact_facts_filters():
    facts = [
        _fact("f1", predicate="identity"),
        _fact("f2", predicate="location", value="在城堡"),
        _fact("f3", predicate="death"),
    ]
    assert [f.fact_id for f in high_impact_facts(facts)] == ["f1", "f3"]


# --- 判定落档 --------------------------------------------------------------


def test_contradicted_fact_is_excluded(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1"), _fact("f2")])
    provider = StubProvider({
        "f1": {"verdict": "contradicted", "reason": "引文有否定词，主张吃掉了", "confidence": 0.9},
        "f2": {"verdict": "entailed", "reason": "引文直接支持", "confidence": 0.95},
    })
    report = run_verification(run, provider)
    assert report.excluded_fact_ids == ["f1"]
    assert report.counts["contradicted"] == 1
    assert report.counts["entailed"] == 1


def test_partially_supported_is_reported_but_not_excluded(tmp_path):
    """「部分支持」不是「错」，它只是不够 —— 排除它是过度反应，但要报出来。"""
    run = _prepare_run(tmp_path, [_fact("f1")])
    provider = StubProvider({
        "f1": {"verdict": "partially_supported", "reason": "引文说的是猜测", "confidence": 0.7}
    })
    report = run_verification(run, provider)
    assert report.counts["partially_supported"] == 1
    assert report.excluded_fact_ids == []


def test_problem_verdicts_is_exactly_the_exclusion_set():
    assert PROBLEM_VERDICTS == {"contradicted", "insufficient_evidence"}


def test_verification_writes_json_and_report(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    run_verification(run, StubProvider({}))
    assert (run / "verification" / "semantic.json").is_file()
    assert (run / "reports" / "semantic_report.md").is_file()


# --- 失败路径：绝不静默放过 -------------------------------------------------


def test_provider_failure_becomes_insufficient_evidence(tmp_path):
    """调用失败不能当成通过 —— 那正好是「看起来成功」的假报告。"""
    run = _prepare_run(tmp_path, [_fact("f1"), _fact("f2")])
    report = run_verification(run, StubProvider({}, fail={"f1"}))
    verdict = next(v for v in report.verdicts if v.fact_id == "f1")
    assert verdict.verdict == "insufficient_evidence"
    assert "校验调用失败" in verdict.reason
    assert "f1" in report.excluded_fact_ids


def test_unparsable_response_becomes_insufficient_evidence(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    report = run_verification(run, StubProvider({}, garbage={"f1"}))
    assert report.verdicts[0].verdict == "insufficient_evidence"
    assert "无法解析" in report.verdicts[0].reason


def test_fact_without_any_quote_is_flagged_not_skipped(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1", quote="")])
    report = run_verification(run, StubProvider({}))
    assert report.verdicts[0].verdict == "insufficient_evidence"
    assert "没有任何引文" in report.verdicts[0].reason


def test_missing_upstream_facts_file_raises(tmp_path):
    (tmp_path / "run").mkdir()
    with pytest.raises(VerificationError, match="facts.json"):
        run_verification(tmp_path / "run", StubProvider({}))


# --- 抽样与口径 ------------------------------------------------------------


def test_sample_limits_checks_and_says_so(tmp_path):
    run = _prepare_run(tmp_path, [_fact(f"f{i}") for i in range(10)])
    report = run_verification(run, StubProvider({}), sample=3)
    assert report.facts_checked == 3
    assert report.facts_total == 10
    assert any("抽样" in note for note in report.notes)


def test_only_high_impact_restricts_targets(tmp_path):
    facts = [_fact("f1", predicate="identity"), _fact("f2", predicate="location", value="在城堡")]
    run = _prepare_run(tmp_path, facts)
    report = run_verification(run, StubProvider({}), only_high_impact=True)
    assert report.facts_checked == 1
    assert report.verdicts[0].fact_id == "f1"
    assert report.high_impact_total == 1


def test_report_always_states_what_this_layer_does_not_do(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    report = run_verification(run, StubProvider({}))
    text = render_report(report, run_dir=run)
    assert "不替代" in text
    assert "引文 100% 定位" in text


def test_report_names_the_excluded_facts(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    provider = StubProvider({"f1": {"verdict": "contradicted", "reason": "冲突", "confidence": 0.9}})
    report = run_verification(run, provider)
    text = render_report(report, run_dir=run)
    assert "被排除的事实" in text
    assert "f1" in text


def test_load_verdicts_returns_none_when_never_run(tmp_path):
    """没跑过就返回 None —— 不要伪造一份空结果让上层以为跑过了。"""
    (tmp_path / "run").mkdir()
    assert load_verdicts(tmp_path / "run") is None


def test_load_verdicts_round_trips(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    run_verification(run, StubProvider({}))
    loaded = load_verdicts(run)
    assert isinstance(loaded, SemanticReport)
    assert loaded.facts_checked == 1


def test_verifier_label_records_the_model(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1")])
    report = run_verification(run, StubProvider({}))
    assert report.verdicts[0].verifier == "stub:stub-1"


def test_every_verdict_carries_the_quote_it_judged(tmp_path):
    run = _prepare_run(tmp_path, [_fact("f1", quote="他在塔上说了那句话。")])
    report = run_verification(run, StubProvider({}))
    assert report.verdicts[0].quote == "他在塔上说了那句话。"
    assert report.verdicts[0].subject == "甲"


# --- 与下游的衔接 ----------------------------------------------------------


def test_excluded_facts_do_not_reach_entry_bodies():
    """校验结论必须真的影响产物，不能只写在报告里。"""
    from novel_to_tavern.resolve.entities import CanonicalEntity
    from novel_to_tavern.timeline.worldbible import plan_entity_entries

    entity = CanonicalEntity(
        id="e1", kind="character", canonical_name="甲",
        appearance_chapters=[0], first_appearance_chapter=0, evidence_count=5,
    )
    facts = [
        _fact("f1", predicate="state", value="受伤了"),
        _fact("f2", predicate="background", value="出身骑士团"),
        _fact("f3", predicate="ability", value="会用剑"),
    ]
    full = plan_entity_entries([entity], facts)
    assert len(full) == 1
    assert "出身骑士团" in full[0].content_runtime

    filtered = plan_entity_entries([entity], facts, excluded_fact_ids=frozenset({"f2"}))
    assert filtered and "出身骑士团" not in filtered[0].content_runtime
    assert "受伤了" in filtered[0].content_runtime
    assert "会用剑" in filtered[0].content_runtime


def test_excluding_facts_can_drop_an_entity_below_the_threshold():
    """排掉事实可能让实体掉到门槛以下，于是不再出条目 —— 这是对的，
    宁可没有条目，也不要一个只剩边角料的条目。"""
    from novel_to_tavern.resolve.entities import CanonicalEntity
    from novel_to_tavern.timeline.worldbible import plan_entity_entries

    entity = CanonicalEntity(
        id="e1", kind="character", canonical_name="甲",
        appearance_chapters=[0], first_appearance_chapter=0, evidence_count=5,
    )
    facts = [_fact("f1", predicate="state", value="受伤了"), _fact("f2", predicate="background", value="出身骑士团")]
    assert plan_entity_entries([entity], facts)
    assert plan_entity_entries([entity], facts, excluded_fact_ids=frozenset({"f2"})) == []


def test_timeline_marks_the_layer_as_not_executed_when_absent(tmp_path):
    from novel_to_tavern.timeline.runner import _render_report

    text = _render_report(
        tmp_path, timeline=[], knowledge={}, contradictions=[], leakage_reports={
            "start_at_beginning": [], "start_at_end": []
        }, entries=[], blocked=[], skipped_entities=[], plan_stats={
            "total_entries": 0, "always_on_entries": 0, "triggered_entries": 0,
            "always_on_tokens": 0, "total_tokens": 0,
        }, start_chapter=None, total_chapters=1, verdicts=None,
    )
    assert "未执行" in text
    assert "只**做了证据定位" not in text or "没有**做" in text or "**只**做了证据定位" in text


# --- 安全闸：全面失败必须中止，不能静默清空世界书 ---------------------------


def test_all_calls_failing_aborts_instead_of_writing_a_report(tmp_path):
    """下游会按报告把事实排出条目正文 —— 全面失败的结论会静默清空世界书。"""
    run = _prepare_run(tmp_path, [_fact("f1"), _fact("f2")])
    with pytest.raises(VerificationError, match="一条都没调通"):
        run_verification(run, StubProvider({}, fail={"f1", "f2"}))
    assert not (run / "verification" / "semantic.json").exists()


def test_partial_call_failure_still_writes_a_report(tmp_path):
    """部分失败是可以接受的 —— 那几条记为 insufficient_evidence 并写明原因。"""
    run = _prepare_run(tmp_path, [_fact("f1"), _fact("f2"), _fact("f3")])
    report = run_verification(run, StubProvider({}, fail={"f1"}))
    assert report.facts_checked == 3
    assert report.excluded_fact_ids == ["f1"]
    assert (run / "verification" / "semantic.json").is_file()


def test_unparsable_responses_do_not_trip_the_abort_guard(tmp_path):
    """解析失败与调用失败不是一回事：解析失败说明引擎通了，只是答得不对。"""
    run = _prepare_run(tmp_path, [_fact("f1")])
    report = run_verification(run, StubProvider({}, garbage={"f1"}))
    assert report.verdicts[0].verdict == "insufficient_evidence"
