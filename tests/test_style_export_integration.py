"""风格模块与导出的集成：默认关闭即基线、新鲜产物免引擎、过期自动重跑、
严格档剧透拦截、canon 隔离。

全部离线：LLM 一律 `FileProvider` / 预生成响应。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.export import ExportError, export
from novel_to_tavern.extract.schema import EventRecord, FactRecord, RelationRecord, SourceRef
from novel_to_tavern.ingest.source import sha256_of
from novel_to_tavern.llm import build_provider
from novel_to_tavern.resolve import CanonicalEntity
from novel_to_tavern.style import (
    STYLE_ENTRY_KEYS,
    StyleProfile,
    build_style_entries,
    compute_inputs_fingerprint,
    write_style_entries,
)
from novel_to_tavern.tavern import validate_parity
from novel_to_tavern.timeline.build import TimelineEvent
from novel_to_tavern.timeline.worldbible import PlannedEntry

from style_fixtures import merge_payload, observation_payload, style_profile_payload


def _marker(chapter: int) -> str:
    return f"〈第{chapter + 1}章独有ZZ{chapter}ZZ〉"


def _write_novel(path: Path, chapters: int) -> tuple[list[str], list[tuple[int, int]]]:
    lines = ["测试纪事\n", "\n"]
    ranges: list[tuple[int, int]] = []
    for index in range(chapters):
        lines.append(f"第{index + 1}章 章节{index + 1}\n")
        lines.append("\n")
        start = len(lines)
        lines.append(f"{_marker(index)}场景开始。\n")
        lines.append(f"人物{index + 1}在说话。\n")
        lines.append("风从河面吹过来。\n")
        end = len(lines)
        ranges.append((start, end))
        lines.append("\n")
    path.write_text("".join(lines), encoding="utf-8")
    return lines, ranges


def _entity(index: int, name: str) -> CanonicalEntity:
    return CanonicalEntity(
        id=f"ent_{index:04d}",
        kind="character",
        canonical_name=name,
        appearance_chapters=[index],
        first_appearance_chapter=index,
        evidence_count=5,
        importance=0.5,
    )


def _prepare_run(tmp_path: Path, chapters: int = 6) -> Path:
    run = tmp_path / "run"
    for sub in ("canonical", "worldbook", "reports", "extraction"):
        (run / sub).mkdir(parents=True, exist_ok=True)

    novel = tmp_path / "novel.txt"
    lines, ranges = _write_novel(novel, chapters)
    source_sha = sha256_of(novel.read_bytes())

    chapter_records = []
    chunk_records = []
    for index, (start, end) in enumerate(ranges):
        chapter_id = f"ch{index:04d}"
        chapter_records.append(
            {
                "chapter_id": chapter_id,
                "source_id": "src",
                "index": index,
                "number": str(index + 1),
                "level": "章",
                "title": f"章节{index + 1}",
                "region_id": f"r{index}",
                "start_line": start,
                "end_line": end,
                "char_count": sum(len(line) for line in lines[start:end]),
            }
        )
        chunk_records.append(
            {
                "chunk_id": f"src_{chapter_id}_p000",
                "chapter_id": chapter_id,
                "source_id": "src",
                "index": index,
                "ordinal_in_chapter": 0,
                "start_line": start,
                "end_line": end,
                "start_char": 0,
                "end_char": 0,
                "char_count": sum(len(line) for line in lines[start:end]),
                "sha256": sha256_of("".join(lines[start:end])),
            }
        )

    (run / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "parser_version": "test",
                "run_id": run.name,
                "created_at": "",
                "updated_at": "",
                "config_fingerprint": "fp",
                "sources": [
                    {
                        "source_id": "src",
                        "path": str(novel),
                        "filename": novel.name,
                        "sha256": source_sha,
                        "size_bytes": novel.stat().st_size,
                        "encoding": "utf-8",
                        "newline_style": "lf",
                        "total_lines": len(lines),
                        "total_chars": sum(len(line) for line in lines),
                    }
                ],
                "chapters": chapter_records,
                "chunks": chunk_records,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for index in range(chapters):
        (run / "extraction" / f"src_ch{index:04d}_p000.json").write_text(
            json.dumps(
                {
                    "chunk_id": f"src_ch{index:04d}_p000",
                    "chapter_index": index,
                    "chapter_title": f"章节{index + 1}",
                    "summary": f"第{index + 1}章概述。",
                    "provider": "stub",
                    "prompt_version": "extract-v1",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    entities = [_entity(0, "甲")] + [
        _entity(index, f"角色{index}") for index in range(1, chapters)
    ]
    (run / "canonical" / "entities.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in entities], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "canonical" / "timeline.json").write_text(
        json.dumps(
            [
                TimelineEvent(
                    event_id=f"e{index}",
                    chapter_index=index,
                    chapter_id=f"ch{index:04d}",
                    order_in_chapter=0,
                    title=f"事件{index + 1}",
                    summary=f"第{index + 1}章的事件。",
                    participants=["甲"],
                    revealed_at_chapter=index,
                ).model_dump(mode="json")
                for index in range(chapters)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    facts = []
    for index in range(chapters):
        name = "甲" if index == 0 else f"角色{index}"
        for suffix, predicate in (("a", "state"), ("b", "background")):
            facts.append(
                FactRecord(
                    fact_id=f"f{index}_{suffix}",
                    chunk_id=f"src_ch{index:04d}_p000",
                    source_id="src",
                    chapter_id=f"ch{index:04d}",
                    chapter_index=index,
                    subject=name,
                    predicate=predicate,
                    value=f"{_marker(index)}的{predicate}",
                    fact_type="canon_fact",
                    source_refs=[
                        SourceRef(
                            source_id="src",
                            chapter_id=f"ch{index:04d}",
                            start_line=1,
                            end_line=2,
                            quote="q",
                        )
                    ],
                )
            )
    (run / "canonical" / "facts.json").write_text(
        json.dumps([f.model_dump(mode="json") for f in facts], ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "canonical" / "events.json").write_text(
        json.dumps(
            [
                EventRecord(
                    event_id=f"ev{index}",
                    chunk_id=f"src_ch{index:04d}_p000",
                    source_id="src",
                    chapter_id=f"ch{index:04d}",
                    chapter_index=index,
                    order_in_chapter=0,
                    title=f"事件{index + 1}",
                    summary=f"{_marker(index)}发生的事",
                    fact_type="canon_fact",
                    source_refs=[
                        SourceRef(
                            source_id="src",
                            chapter_id=f"ch{index:04d}",
                            start_line=1,
                            end_line=2,
                            quote="q",
                        )
                    ],
                ).model_dump(mode="json")
                for index in range(chapters)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run / "canonical" / "relations.json").write_text(
        json.dumps(
            [
                RelationRecord(
                    relation_id=f"r{index}",
                    chunk_id=f"src_ch{index:04d}_p000",
                    source_id="src",
                    chapter_id=f"ch{index:04d}",
                    chapter_index=index,
                    from_entity="甲",
                    to_entity="甲",
                    relation="自己",
                    source_refs=[
                        SourceRef(
                            source_id="src",
                            chapter_id=f"ch{index:04d}",
                            start_line=1,
                            end_line=2,
                            quote="q",
                        )
                    ],
                ).model_dump(mode="json")
                for index in range(chapters)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = [
        PlannedEntry(
            entry_id="wb_overview",
            category="world_overview",
            title="世界概况",
            content_runtime="地点：某城",
            content_canonical="",
            always_on=True,
        ),
        PlannedEntry(
            entry_id="wb_index_characters",
            category="character_index",
            title="人物索引",
            content_runtime="甲、角色1",
            content_canonical="",
            always_on=True,
        ),
    ]
    for index in range(chapters):
        name = "甲" if index == 0 else f"角色{index}"
        plan.append(
            PlannedEntry(
                entry_id=f"wb_entity_ent_{index:04d}",
                category="character",
                title=name,
                content_runtime=f"identity：{name}的描述",
                content_canonical="",
                keys=[name],
                always_on=False,
                valid_from_chapter=index,
            )
        )
    (run / "worldbook" / "plan.json").write_text(
        json.dumps([entry.model_dump(mode="json") for entry in plan], ensure_ascii=False),
        encoding="utf-8",
    )
    return run


def _enabled() -> config_module.Config:
    base = config_module.Config()
    return base.model_copy(
        update={"style": base.style.model_copy(update={"enabled": True})}
    )


def _write_fresh_artifacts(
    run: Path, cfg: config_module.Config, *, entries=None, runtime_text=None
) -> StyleProfile:
    fingerprint = compute_inputs_fingerprint(run, cfg)
    profile = StyleProfile.model_validate(
        style_profile_payload(
            profile_id=f"style-{fingerprint[:12]}",
            inputs_fingerprint=fingerprint,
            created_at="2026-10-20T00:00:00+00:00",
        )
    )
    base = run / "author_style"
    base.mkdir(parents=True, exist_ok=True)
    (base / "style_profile.json").write_text(
        json.dumps(profile.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    (base / "runtime_style_prompt.md").write_text(
        runtime_text or "写作执行要点：\n旁白用短句；对白留白。\n", encoding="utf-8"
    )
    write_style_entries(
        base / "style_worldbook_entries.json",
        entries if entries is not None else build_style_entries(profile),
    )
    (base / "style_eval_cases.json").write_text("[]\n", encoding="utf-8")
    return profile


def _file_config(cfg: config_module.Config, tmp_path: Path) -> config_module.Config:
    pre = tmp_path / "precomputed"
    pre.mkdir(parents=True, exist_ok=True)
    run = tmp_path / "run"
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    for chunk in manifest["chunks"]:
        (pre / f"{chunk['chunk_id']}.json").write_text(
            json.dumps(observation_payload(), ensure_ascii=False), encoding="utf-8"
        )
    (pre / "style_merge_batch_000.json").write_text(
        json.dumps(merge_payload(), ensure_ascii=False), encoding="utf-8"
    )
    (pre / "style_compile.json").write_text(
        json.dumps(style_profile_payload(), ensure_ascii=False), encoding="utf-8"
    )
    return cfg.model_copy(
        update={
            "llm": cfg.llm.model_copy(
                update={"provider": "file", "precomputed_responses_dir": str(pre)}
            )
        }
    )


def _style_ids(result) -> list[str]:
    return [entry.entry_id for entry in result["entries"] if entry.category == "author_style"]


def test_disabled_is_baseline(tmp_path):
    run = _prepare_run(tmp_path)
    result = export(run, config_module.Config())

    assert "【叙事风格规范】" not in result["card"].data.description
    assert _style_ids(result) == []
    manifest = json.loads((run / "exports" / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["style"] == {"enabled": False}
    assert manifest["rendering"] == {"enabled": False}


def test_enabled_fresh_artifacts_no_provider(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _enabled()
    _write_fresh_artifacts(run, cfg)

    result = export(run, cfg)  # 不传 provider：新鲜产物不需要引擎

    description = result["card"].data.description
    # 用户要求：开头就要写明「尽量模仿作者风格」，并指向世界书里的风格条目。
    assert description.startswith("【写作要求：作者风格】")
    assert "模仿该作品的文风" in description
    assert "世界书" in description and "作者风格：" in description
    assert description.count("【叙事风格规范】") == 1
    assert "旁白用短句" in description
    assert len(_style_ids(result)) == 8

    # 严格起始点档同样把写作要求放在开头。
    strict = export(run, cfg, start_chapter=1)
    strict_description = strict["strict"]["card"].data.description
    assert strict_description.startswith("【写作要求：作者风格】")
    assert strict_description.count("【叙事风格规范】") == 1


def test_enabled_missing_artifacts_auto_runs(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _file_config(_enabled(), tmp_path)

    result = export(run, cfg, provider=build_provider(cfg))

    base = run / "author_style"
    for name in (
        "style_profile.json",
        "style_profile.md",
        "runtime_style_prompt.md",
        "style_worldbook_entries.json",
        "style_eval_cases.json",
        "audit.md",
    ):
        assert (base / name).is_file(), name
    assert "【叙事风格规范】" in result["card"].data.description
    assert _style_ids(result)


def test_stale_artifacts_rerun(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _file_config(_enabled(), tmp_path)
    base = run / "author_style"
    base.mkdir(parents=True, exist_ok=True)
    stale = StyleProfile.model_validate(
        style_profile_payload(profile_id="style-stale", inputs_fingerprint="stale")
    )
    (base / "style_profile.json").write_text(
        json.dumps(stale.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )
    (base / "runtime_style_prompt.md").write_text("旧的规范。\n", encoding="utf-8")

    export(run, cfg, provider=build_provider(cfg))

    refreshed = StyleProfile.model_validate(
        json.loads((base / "style_profile.json").read_text(encoding="utf-8"))
    )
    assert refreshed.inputs_fingerprint != "stale"
    assert refreshed.inputs_fingerprint == compute_inputs_fingerprint(run, cfg)


def test_parity_with_style_entries(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _enabled()
    _write_fresh_artifacts(run, cfg)

    result = export(run, cfg)

    assert validate_parity(result["card"], result["worldbook"]).ok
    assert len(result["card"].data.character_book.entries) == len(
        result["worldbook"].entries
    )


def _leaky_entry() -> PlannedEntry:
    return PlannedEntry(
        entry_id="wb_style_leak",
        category="author_style",
        title="作者风格：泄漏测试",
        content_runtime="这条规则引用了第 9 章的例子。",
        content_canonical="",
        keys=list(STYLE_ENTRY_KEYS),
        always_on=False,
        priority=40,
        quality_flags=["非 canon"],
    )


def test_strict_export_leak_check(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _enabled()
    _write_fresh_artifacts(run, cfg, entries=[_leaky_entry()])

    with pytest.raises(ExportError, match="拦截"):
        export(run, cfg, start_chapter=1)


def test_canon_isolation(tmp_path):
    run = _prepare_run(tmp_path)
    cfg = _enabled()
    _write_fresh_artifacts(run, cfg)
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (run / "canonical").glob("*.json")
    }

    export(run, cfg)

    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (run / "canonical").glob("*.json")
    }
    assert after == before
