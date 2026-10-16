"""抽取执行器：证据定位、canon 资格、隔离、缓存、续跑、报告。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.extract import (
    EXTRACTION_DIR,
    ExtractionError,
    ExtractionRunner,
    parse_json_response,
    run_extraction,
)
from novel_to_tavern.extract.prompts import PROMPT_VERSION
from novel_to_tavern.ingest import ingest
from novel_to_tavern.llm import MissingResponseError

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"

GOOD = {
    "summary": "少年在北风里沿河堤南行。",
    "mentions": [
        {"name": "少年", "aliases": [], "kind": "character", "quote": "少年把斗篷的领子竖起来"},
        {"name": "铁匠铺", "aliases": [], "kind": "place", "quote": "铁匠铺的炉子还红着"},
    ],
    "facts": [
        {
            "subject": "少年",
            "predicate": "action",
            "value": "沿河堤往南走",
            "fact_type": "canon_fact",
            "quote": "沿着河堤往南走",
        },
        {
            "subject": "少年",
            "predicate": "identity",
            "value": "某个王国的王子",
            "fact_type": "canon_fact",
            "quote": "他其实是失散多年的王子",  # 原文里没有 → 必须被降级
        },
    ],
    "events": [
        {
            "title": "少年离开镇子",
            "summary": "北风吹起时，少年沿河堤南行。",
            "participants": ["少年"],
            "location": "河堤",
            "fact_type": "canon_fact",
            "quote": "少年把斗篷的领子竖起来",
        }
    ],
    "relations": [],
}


class StubProvider:
    name = "stub"

    def __init__(self, payload=None, *, raise_missing=False, text=None):
        self.payload = payload
        self.text = text
        self.raise_missing = raise_missing
        self.calls = 0

    def complete(self, *, chunk_id, system_prompt, user_prompt):
        from novel_to_tavern.llm import Completion

        self.calls += 1
        if self.raise_missing:
            raise MissingResponseError(f"no response for {chunk_id}")
        body = self.text if self.text is not None else json.dumps(self.payload, ensure_ascii=False)
        return Completion(text=body, model="stub-model")


def _setup(tmp_path: Path) -> tuple[config_module.Config, Path]:
    base = config_module.Config()
    cfg = base.model_copy(
        update={
            "project": base.project.model_copy(
                update={
                    "source_path": str(SAMPLE),
                    "output_root": str(tmp_path / "runs"),
                }
            ),
            "input": base.input.model_copy(
                update={"chunk_target_chars": 100000, "chunk_max_chars": 200000}
            ),
            "pipeline": base.pipeline.model_copy(
                update={"cache_dir": str(tmp_path / "cache"), "cache_enabled": True}
            ),
            "llm": base.llm.model_copy(update={"max_concurrent_requests": 2}),
        }
    )
    run_id = "20261016T000000Z_bbbbbb"
    ingest(cfg, run_id=run_id)
    return cfg, tmp_path / "runs" / run_id


# --- 响应解析 -------------------------------------------------------------


def test_parse_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_in_code_fence():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_surrounding_prose():
    assert parse_json_response('好的，结果如下：\n{"a": 1}\n以上。') == {"a": 1}


@pytest.mark.parametrize("bad", ["", "   ", "完全没有 JSON", "{不是合法 JSON}"])
def test_parse_rejects_unusable_responses(bad):
    with pytest.raises(ValueError):
        parse_json_response(bad)


# --- 证据定位与 canon 资格 -------------------------------------------------


def test_located_quotes_become_accepted_source_refs(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    runner = ExtractionRunner(cfg, run_dir, StubProvider(GOOD))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    extraction = runner.process_chunk(chunk_id)

    assert extraction.facts[0].review_status == "accepted"
    ref = extraction.facts[0].source_refs[0]
    assert ref.chapter_id == extraction.chapter_id
    assert ref.start_line < ref.end_line
    assert "沿着河堤往南走" in ref.quote


def test_canon_fact_without_locatable_evidence_is_downgraded(tmp_path):
    """声称是原著事实却找不到证据 → 不能当 canon 用。"""
    cfg, run_dir = _setup(tmp_path)
    runner = ExtractionRunner(cfg, run_dir, StubProvider(GOOD))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    extraction = runner.process_chunk(chunk_id)

    bogus = extraction.facts[1]
    assert bogus.review_status == "needs_review"
    assert bogus.source_refs == []
    assert "无法在原文定位" in bogus.review_note
    assert "需人工复核" in bogus.review_note


def test_mention_without_evidence_is_flagged(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    payload = {
        "summary": "",
        "mentions": [{"name": "路人", "kind": "character", "quote": "一个不存在的人说"}],
        "facts": [],
        "events": [],
        "relations": [],
    }
    runner = ExtractionRunner(cfg, run_dir, StubProvider(payload))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    extraction = runner.process_chunk(chunk_id)
    assert extraction.mentions[0].review_status == "needs_review"


def test_evidence_coverage_reflects_reality(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    runner = ExtractionRunner(cfg, run_dir, StubProvider(GOOD))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    extraction = runner.process_chunk(chunk_id)
    # GOOD 里有 5 条引文，其中 1 条是编的
    assert extraction.evidence_total == 5
    assert extraction.evidence_located == 4
    assert extraction.evidence_coverage == pytest.approx(0.8)


def test_records_carry_chapter_and_chunk_provenance(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    runner = ExtractionRunner(cfg, run_dir, StubProvider(GOOD))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    extraction = runner.process_chunk(chunk_id)
    for record in [*extraction.mentions, *extraction.facts, *extraction.events]:
        assert record.chunk_id == chunk_id
        assert record.source_id == "sample_novel"
        assert record.chapter_index >= 0


# --- 隔离与重试 -----------------------------------------------------------


def test_unparsable_response_is_quarantined_then_raises(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    provider = StubProvider(text="这不是 JSON")
    runner = ExtractionRunner(cfg, run_dir, StubProvider(text="这不是 JSON"))
    chunk_id = sorted(c.chunk_id for c in runner.manifest.chunks)[0]
    with pytest.raises(ExtractionError, match="已隔离"):
        runner.process_chunk(chunk_id)
    assert (run_dir / EXTRACTION_DIR / "_errors" / f"{chunk_id}.txt").is_file()


def test_invalid_response_is_never_written_as_success(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    result = run_extraction(cfg, run_dir, StubProvider(text="nope"))
    assert result.ok is False
    assert result.failed
    assert result.done == []


def test_invalid_json_is_retried_before_quarantine(tmp_path):
    """先给坏响应、再给好响应：应当成功，不隔离。"""
    cfg, run_dir = _setup(tmp_path)

    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def complete(self, *, chunk_id, system_prompt, user_prompt):
            from novel_to_tavern.llm import Completion

            self.calls += 1
            if self.calls % 2 == 1:
                return Completion(text="不是 JSON", model="stub")
            return Completion(text=json.dumps(GOOD, ensure_ascii=False), model="stub")

    result = run_extraction(cfg, run_dir, Flaky())
    assert result.ok
    assert len(result.done) == len(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["chunks"])


# --- 缓存与续跑 -----------------------------------------------------------


def test_second_run_hits_cache_and_does_not_call_provider(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    provider = StubProvider(GOOD)
    run_extraction(cfg, run_dir, provider)
    first_calls = provider.calls

    provider2 = StubProvider(GOOD)
    run_extraction(cfg, run_dir, provider2, resume=False)
    assert provider2.calls == 0  # 全部命中缓存


def test_prompt_version_is_part_of_the_cache_key(tmp_path):
    from novel_to_tavern.extract import cache_key

    base = dict(model="m", provider="p", chunk_sha="abc", temperature=0.1)
    assert cache_key(**base) == cache_key(**base)
    assert cache_key(**base) != cache_key(**{**base, "chunk_sha": "abd"})
    assert cache_key(**base) != cache_key(**{**base, "model": "m2"})
    assert cache_key(**base) != cache_key(**{**base, "temperature": 0.9})


def test_resume_skips_completed_chunks(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    run_extraction(cfg, run_dir, StubProvider(GOOD))
    result = run_extraction(cfg, run_dir, StubProvider(GOOD), resume=True)
    assert result.skipped
    assert result.failed == {}


def test_limit_processes_only_the_first_n_chunks(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    result = run_extraction(cfg, run_dir, StubProvider(GOOD), limit=1)
    assert len(result.done) == 1


def test_missing_precomputed_response_is_reported_not_swallowed(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    result = run_extraction(cfg, run_dir, StubProvider(raise_missing=True))
    assert not result.ok
    assert all("缺少预生成响应" in reason for reason in result.failed.values())


# --- 报告 -----------------------------------------------------------------


def test_report_records_provider_and_coverage(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    run_extraction(cfg, run_dir, StubProvider(GOOD))
    report = (run_dir / "reports" / "extraction_summary.md").read_text(encoding="utf-8")
    assert PROMPT_VERSION in report
    assert "`stub`" in report
    assert "覆盖率" in report
    assert "needs_review" in report or "待人工复核" in report


def test_report_does_not_leak_source_text(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    run_extraction(cfg, run_dir, StubProvider(GOOD))
    report = (run_dir / "reports" / "extraction_summary.md").read_text(encoding="utf-8")
    assert "北风从山口压下来" not in report


def test_prompt_template_hash_is_part_of_the_cache_key():
    """改提示词但忘了改版本号时，缓存必须仍然失效 —— 本项目真踩过这个坑。"""
    import json as _json

    from novel_to_tavern.extract import runner as runner_module

    base = dict(model="m", provider="p", chunk_sha="abc", temperature=0.1)
    before = runner_module.cache_key(**base)

    original = runner_module.SYSTEM_PROMPT
    try:
        runner_module.SYSTEM_PROMPT = original + "\n补充一句。"
        after = runner_module.cache_key(**base)
    finally:
        runner_module.SYSTEM_PROMPT = original

    assert before != after, "提示词模板变了，缓存键却没变"
    assert _json.dumps(base)  # 参数本身没被改动


def test_schema_version_is_part_of_the_cache_key():
    from novel_to_tavern.extract import runner as runner_module

    base = dict(model="m", provider="p", chunk_sha="abc", temperature=0.1)
    before = runner_module.cache_key(**base)
    original = runner_module.SCHEMA_VERSION
    try:
        runner_module.SCHEMA_VERSION = original + 1
        after = runner_module.cache_key(**base)
    finally:
        runner_module.SCHEMA_VERSION = original
    assert before != after
