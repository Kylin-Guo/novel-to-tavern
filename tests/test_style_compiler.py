"""风格编译：六份产物、schema 闸门、分批、压缩预算、指纹、缓存。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.ingest import ingest
from novel_to_tavern.style import (
    StyleCompileError,
    StyleObservation,
    compute_inputs_fingerprint,
    run_style_compile,
)

from style_fixtures import DictProvider, merge_payload, style_profile_payload

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"

ARTIFACTS = (
    "style_profile.json",
    "style_profile.md",
    "runtime_style_prompt.md",
    "style_worldbook_entries.json",
    "style_eval_cases.json",
    "audit.md",
)


def _setup(tmp_path: Path, **style_updates) -> tuple[config_module.Config, Path]:
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
                update={"chunk_target_chars": 100_000, "chunk_max_chars": 200_000}
            ),
            "pipeline": base.pipeline.model_copy(
                update={"cache_dir": str(tmp_path / "cache"), "cache_enabled": True}
            ),
            "style": base.style.model_copy(update=style_updates),
        }
    )
    run_id = "20261020T000000Z_b2c3d4"
    ingest(cfg, run_id=run_id, resume=False)
    return cfg, tmp_path / "runs" / run_id


def _write_observations(run_dir: Path, count: int | None = None) -> list[str]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    ids = [chunk["chunk_id"] for chunk in manifest["chunks"]]
    if count is not None and count != len(ids):
        ids = [f"obs_{index:03d}" for index in range(count)]
    directory = run_dir / "author_style" / "observations"
    directory.mkdir(parents=True, exist_ok=True)
    for index, chunk_id in enumerate(ids):
        observation = StyleObservation(
            chunk_id=chunk_id, chapter_index=index, source_id="sample_novel"
        )
        (directory / f"{chunk_id}.json").write_text(
            json.dumps(observation.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
    return ids


def _responses(*, batches: int = 1, compile_payload=None, compress=None) -> dict:
    responses = {
        f"style_merge_batch_{index:03d}": merge_payload() for index in range(batches)
    }
    responses["style_compile"] = compile_payload or style_profile_payload()
    if compress is not None:
        responses["style_compress"] = compress
    return responses


def test_produces_six_artifacts(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    _write_observations(run_dir)
    provider = DictProvider(_responses())

    profile = run_style_compile(run_dir, cfg, provider)

    for name in ARTIFACTS:
        assert (run_dir / "author_style" / name).is_file(), name
    assert profile.profile_id.startswith("style-")
    assert profile.inputs_fingerprint
    assert profile.created_at
    assert [s.kind for s in profile.source_manifest] == ["novel"]

    entries = json.loads(
        (run_dir / "author_style" / "style_worldbook_entries.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(entries) == 8
    cases = json.loads(
        (run_dir / "author_style" / "style_eval_cases.json").read_text(encoding="utf-8")
    )
    assert len(cases) == 6


def test_profile_schema_enforced(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    _write_observations(run_dir)
    payload = style_profile_payload()
    del payload["genre_tone"]
    provider = DictProvider(_responses(compile_payload=payload))

    with pytest.raises(StyleCompileError, match="不符合 schema"):
        run_style_compile(run_dir, cfg, provider)

    assert provider.chunk_ids.count("style_compile") == 2  # 重试一次后才隔离
    error = run_dir / "author_style" / "_errors" / "style_compile.json"
    assert error.is_file()
    data = json.loads(error.read_text(encoding="utf-8"))
    assert data["chunk_id"] == "style_compile"
    assert "raw_response" in data


def test_merge_batch_count(tmp_path):
    cfg, run_dir = _setup(tmp_path, merge_batch_size=30)
    _write_observations(run_dir, count=65)
    provider = DictProvider(_responses(batches=3))

    run_style_compile(run_dir, cfg, provider)

    merge_calls = [cid for cid in provider.chunk_ids if cid.startswith("style_merge_batch_")]
    assert merge_calls == [
        "style_merge_batch_000",
        "style_merge_batch_001",
        "style_merge_batch_002",
    ]
    merged = sorted((run_dir / "author_style" / "merged").glob("batch_*.json"))
    assert len(merged) == 3


def test_runtime_over_budget_triggers_compress(tmp_path):
    cfg, run_dir = _setup(tmp_path, max_runtime_tokens=20)
    _write_observations(run_dir)
    long_rules = "长" * 100
    provider = DictProvider(
        _responses(
            compile_payload=style_profile_payload(runtime_rules=long_rules),
            compress={"runtime_rules": "短句。", "dropped": ["删掉一条长规则：超出预算"]},
        )
    )

    profile = run_style_compile(run_dir, cfg, provider)

    assert "style_compress" in provider.chunk_ids
    assert profile.runtime_rules == "短句。"
    audit = (run_dir / "author_style" / "audit.md").read_text(encoding="utf-8")
    assert "删掉一条长规则" in audit
    assert "丢弃规律数：1" in audit


def test_compress_still_over_budget_fails(tmp_path):
    cfg, run_dir = _setup(tmp_path, max_runtime_tokens=20)
    _write_observations(run_dir)
    provider = DictProvider(
        _responses(
            compile_payload=style_profile_payload(runtime_rules="长" * 100),
            compress={"runtime_rules": "更长" * 100, "dropped": ["删了一条，但还不够"]},
        )
    )

    with pytest.raises(StyleCompileError, match="仍超过预算"):
        run_style_compile(run_dir, cfg, provider)

    audit = (run_dir / "author_style" / "audit.md").read_text(encoding="utf-8")
    assert "中止原因" in audit
    assert "未截断" in audit
    assert not (run_dir / "author_style" / "style_profile.json").is_file()


def test_fingerprint_changes(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    baseline = compute_inputs_fingerprint(run_dir, cfg)

    tighter = cfg.model_copy(
        update={"style": cfg.style.model_copy(update={"max_runtime_tokens": 100})}
    )
    assert compute_inputs_fingerprint(run_dir, tighter) != baseline

    note = tmp_path / "note.md"
    note.write_text("作者自述：喜欢短句。", encoding="utf-8")
    with_note = cfg.model_copy(
        update={"style": cfg.style.model_copy(update={"supplementary_path": str(note)})}
    )
    assert compute_inputs_fingerprint(run_dir, with_note) != baseline

    manifest_path = run_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["sources"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert compute_inputs_fingerprint(run_dir, cfg) != baseline


def test_second_run_cache_hit(tmp_path):
    cfg, run_dir = _setup(tmp_path)
    _write_observations(run_dir)
    run_style_compile(run_dir, cfg, DictProvider(_responses()))

    second = DictProvider({})
    run_style_compile(run_dir, cfg, second)
    assert second.calls == 0


def test_supplementary_missing_raises(tmp_path):
    cfg, run_dir = _setup(
        tmp_path, supplementary_path=str(tmp_path / "absent.md")
    )
    _write_observations(run_dir)
    provider = DictProvider(_responses())

    with pytest.raises(StyleCompileError, match="不存在"):
        run_style_compile(run_dir, cfg, provider)
