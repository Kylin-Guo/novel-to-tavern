"""逐块风格观察：引文定位、隔离、缓存、续跑、抽样。

全部离线：LLM 一律用 StubProvider 返回预生成 JSON。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.ingest import ingest
from novel_to_tavern.llm import Completion, MissingResponseError
from novel_to_tavern.style import (
    OBSERVATIONS_DIR,
    StyleObserveError,
    StyleObservationRunner,
    run_style_observation,
    select_chunks,
)

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"

#: 原文里真实存在的一句（第 1 章）与一句编造的。
REAL_QUOTE = "北风从山口压下来的时候"
FAKE_QUOTE = "这句引文是编造的不会出现在原文里"


def _payload(*, real=REAL_QUOTE, fake=FAKE_QUOTE) -> dict:
    return {
        "narrative_voice": "第三人称限知，叙述贴着少年的感官。",
        "sentence_rhythm": "句子短，动作之间留出停顿。",
        "description_patterns": "环境先于人物出现。",
        "figurative_language": "比喻克制，多取自然物。",
        "dialogue_patterns": "对白短，常以动作代替回答。",
        "psychological_narration": "内心活动用动作暗示。",
        "scene_pacing": "场景在对话后收束。",
        "notable_motifs": ["风", "灯"],
        "anti_patterns_observed": ["不堆砌形容词"],
        "evidence": [
            {"aspect": "sentence_rhythm", "quote": real},
            {"aspect": "figurative_language", "quote": fake},
        ],
    }


class StubProvider:
    name = "stub"
    endpoint_fingerprint = "stub"

    def __init__(self, payload=None, *, text=None, raise_missing=False):
        self.payload = payload if payload is not None else _payload()
        self.text = text
        self.raise_missing = raise_missing
        self.calls = 0
        self.chunk_ids: list[str] = []

    def complete(self, *, chunk_id, system_prompt, user_prompt):
        self.calls += 1
        self.chunk_ids.append(chunk_id)
        if self.raise_missing:
            raise MissingResponseError(f"no response for {chunk_id}")
        body = self.text if self.text is not None else json.dumps(self.payload, ensure_ascii=False)
        return Completion(text=body, model="stub-model")


def _setup(tmp_path: Path, *, tiny_chunks: bool = False) -> tuple[config_module.Config, Path]:
    base = config_module.Config()
    target = 5 if tiny_chunks else 100_000
    cfg = base.model_copy(
        update={
            "project": base.project.model_copy(
                update={
                    "source_path": str(SAMPLE),
                    "output_root": str(tmp_path / "runs"),
                }
            ),
            "input": base.input.model_copy(
                update={"chunk_target_chars": target, "chunk_max_chars": 200_000}
            ),
            "pipeline": base.pipeline.model_copy(
                update={"cache_dir": str(tmp_path / "cache"), "cache_enabled": True}
            ),
        }
    )
    run_id = "20261020T000000Z_a1b2c3"
    ingest(cfg, run_id=run_id, resume=False)
    return cfg, tmp_path / "runs" / run_id


def _first_chunk(runner: StyleObservationRunner):
    return sorted(runner.manifest.chunks, key=lambda c: c.index)[0]


# --- 落盘与引文 ------------------------------------------------------------


def test_writes_per_chunk_json(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    provider = StubProvider()
    result = run_style_observation(cfg, run_dir, provider, resume=False)

    assert result["ok"] is True
    assert result["failed"] == {}
    for chunk_id in result["done"]:
        path = run_dir / "author_style" / OBSERVATIONS_DIR / f"{chunk_id}.json"
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["chunk_id"] == chunk_id
        assert data["prompt_version"] == "style-observe-v1"
    assert (run_dir / "author_style" / OBSERVATIONS_DIR / "_index.json").is_file()
    assert Path(result["report"]).is_file()


def test_quote_located_and_bad_quote_dropped(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    runner = StyleObservationRunner(cfg, run_dir, StubProvider())
    chunk = _first_chunk(runner)
    observation = runner.process_chunk(chunk.chunk_id)

    assert len(observation.evidence) == 1
    assert observation.quotes_dropped == 1
    located = observation.evidence[0]
    assert located.quote == REAL_QUOTE
    assert chunk.start_line <= located.start_line < located.end_line <= chunk.end_line


def test_bad_json_quarantined_then_raises(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    runner = StyleObservationRunner(cfg, run_dir, StubProvider(text="这不是 JSON"))
    chunk = _first_chunk(runner)
    with pytest.raises(StyleObserveError, match="已隔离"):
        runner.process_chunk(chunk.chunk_id)

    error_path = (
        run_dir / "author_style" / OBSERVATIONS_DIR / "_errors" / f"{chunk.chunk_id}.json"
    )
    assert error_path.is_file()
    data = json.loads(error_path.read_text(encoding="utf-8"))
    assert data["chunk_id"] == chunk.chunk_id
    assert "raw_response" in data


def test_failed_chunk_is_not_written_as_success(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    result = run_style_observation(cfg, run_dir, StubProvider(text="不是 JSON"), resume=False)

    assert result["ok"] is False
    assert result["done"] == []
    assert result["failed"]
    for chunk_id in result["failed"]:
        assert not (
            run_dir / "author_style" / OBSERVATIONS_DIR / f"{chunk_id}.json"
        ).is_file()


def test_missing_precomputed_response_is_a_failure_not_a_swallow(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    result = run_style_observation(
        cfg, run_dir, StubProvider(raise_missing=True), resume=False
    )
    assert result["ok"] is False
    assert all("缺少预生成响应" in reason for reason in result["failed"].values())


# --- 缓存与续跑 ------------------------------------------------------------


def test_cache_hit_skips_engine(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    first = StubProvider()
    run_style_observation(cfg, run_dir, first, resume=False)
    assert first.calls == 3

    second = StubProvider()
    run_style_observation(cfg, run_dir, second, resume=False)
    assert second.calls == 0


def test_cache_invalidation_on_chunk_change(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    run_style_observation(cfg, run_dir, StubProvider(), resume=False)

    manifest_path = run_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["chunks"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    provider = StubProvider()
    run_style_observation(cfg, run_dir, provider, resume=False)
    assert provider.calls == 1


def test_resume_skips_done(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    run_style_observation(cfg, run_dir, StubProvider(), resume=False)

    provider = StubProvider()
    result = run_style_observation(cfg, run_dir, provider, resume=True)
    assert result["skipped"]
    assert provider.calls == 0
    assert result["failed"] == {}


def test_limit_processes_only_the_first_n_chunks(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    provider = StubProvider()
    result = run_style_observation(cfg, run_dir, provider, resume=False, limit=1)
    assert len(result["done"]) == 1
    assert provider.calls == 1


# --- 抽样 ------------------------------------------------------------------


def test_select_chunks_all_when_zero(tmp_path):
    _cfg, run_dir = _setup(tmp_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    from novel_to_tavern.ingest.manifest import Manifest

    parsed = Manifest.model_validate(manifest)
    selected = select_chunks(parsed, 0)
    assert [c.chunk_id for c in selected] == [
        c.chunk_id for c in sorted(parsed.chunks, key=lambda c: c.index)
    ]


def test_select_chunks_spread_deterministic(tmp_path):
    _cfg, run_dir = _setup(tmp_path, tiny_chunks=True)
    from novel_to_tavern.ingest.manifest import Manifest

    manifest = Manifest.model_validate(
        json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    )
    assert len(manifest.chunks) > 5

    first = select_chunks(manifest, 3)
    second = select_chunks(manifest, 3)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    ordered = sorted(manifest.chunks, key=lambda c: c.index)
    assert len(first) == 3
    assert first[0].chunk_id == ordered[0].chunk_id
    assert first[-1].chunk_id == ordered[-1].chunk_id
