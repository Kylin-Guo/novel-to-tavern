"""导入流水线：manifest 内容、无损校验、续跑、报告。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.ingest import IngestError, ingest, read_source, rebuild_chapter
from novel_to_tavern.ingest.pipeline import MANIFEST_NAME, STATE_NAME, SUMMARY_NAME

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"


def _config(tmp_path: Path, source: Path = SAMPLE, **input_overrides) -> config_module.Config:
    base = config_module.Config()
    return base.model_copy(
        update={
            "project": base.project.model_copy(
                update={"source_path": str(source), "output_root": str(tmp_path / "runs")}
            ),
            "input": base.input.model_copy(
                update={"chunk_target_chars": 200, "chunk_max_chars": 400, **input_overrides}
            ),
        }
    )


def test_ingest_produces_manifest_chapters_and_chunks(tmp_path):
    run_dir, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    assert (run_dir / MANIFEST_NAME).is_file()
    assert (run_dir / STATE_NAME).is_file()
    assert (run_dir / "reports" / SUMMARY_NAME).is_file()

    assert len(manifest.sources) == 1
    assert len(manifest.chapters) == 3
    assert manifest.chunks
    assert all(c.char_count > 0 for c in manifest.chunks)


def test_manifest_does_not_contain_novel_text(tmp_path):
    """manifest 只存位置与 hash，不得把原文写进去。"""
    run_dir, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    raw = (run_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    source = read_source(SAMPLE, source_id="sample_novel")
    for line in source.lines:
        stripped = line.strip()
        if len(stripped) >= 12:
            assert stripped not in raw, f"manifest 里出现了原文：{stripped[:20]}"


def test_chunks_never_cross_chapter_boundaries(tmp_path):
    _, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    by_chapter = {c.chapter_id: (c.start_line, c.end_line) for c in manifest.chapters}
    for chunk in manifest.chunks:
        start, end = by_chapter[chunk.chapter_id]
        assert start <= chunk.start_line < chunk.end_line <= end


def test_chunks_cover_every_chapter_char_exactly_once(tmp_path):
    _, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    source = read_source(SAMPLE, source_id="sample_novel")
    for chapter in manifest.chapters:
        restored = rebuild_chapter(
            source.lines, chapter, manifest.chunks_of(chapter.chapter_id)
        )
        assert restored == "".join(source.lines[chapter.start_line : chapter.end_line])
        assert sum(c.char_count for c in manifest.chunks_of(chapter.chapter_id)) == chapter.char_count


def test_chunked_chars_plus_non_chapter_regions_equal_total(tmp_path):
    """分块只覆盖章节正文；卷首与站点残留不进分块，但必须仍被 region 覆盖。"""
    _, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    source = read_source(SAMPLE, source_id="sample_novel")

    chunked = sum(c.char_count for c in manifest.chunks)
    non_chapter = sum(
        len("".join(source.lines[r.start_line : r.end_line]))
        for r in manifest.regions
        if r.kind != "chapter"
    )
    chapter_regions = sum(
        len("".join(source.lines[r.start_line : r.end_line]))
        for r in manifest.regions
        if r.kind == "chapter"
    )

    assert chapter_regions == chunked
    assert chunked + non_chapter == source.total_chars


def test_report_states_the_unchunked_remainder_accurately(tmp_path):
    run_dir, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    report = (run_dir / "reports" / SUMMARY_NAME).read_text(encoding="utf-8")
    total = sum(s.total_chars for s in manifest.sources)
    chunked = sum(c.char_count for c in manifest.chunks)
    assert f"分块覆盖字符：{chunked}" in report
    assert f"未分块字符：{total - chunked}" in report


def test_chunk_sha256_matches_its_text(tmp_path):
    from novel_to_tavern.ingest import sha256_of

    _, manifest = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    source = read_source(SAMPLE, source_id="sample_novel")
    for chunk in manifest.chunks:
        text = "".join(source.lines[chunk.start_line : chunk.end_line])
        assert chunk.sha256 == sha256_of(text)
        assert chunk.char_count == len(text)


def test_resume_skips_already_processed_sources(tmp_path):
    cfg = _config(tmp_path)
    run_id = "20261016T000000Z_aaaaaa"
    _, first = ingest(cfg, run_id=run_id)
    _, second = ingest(cfg, run_id=run_id, resume=True)

    assert len(second.chapters) == len(first.chapters)
    assert len(second.chunks) == len(first.chunks)
    assert second.chapters == first.chapters


def test_resume_does_not_duplicate_records(tmp_path):
    cfg = _config(tmp_path)
    run_id = "20261016T000000Z_aaaaaa"
    ingest(cfg, run_id=run_id)
    ingest(cfg, run_id=run_id, resume=True)
    ingest(cfg, run_id=run_id, resume=True)
    run_dir = tmp_path / "runs" / run_id
    manifest = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    chunk_ids = [c["chunk_id"] for c in manifest["chunks"]]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert len(manifest["sources"]) == 1


def test_resume_refuses_when_source_changed(tmp_path):
    cfg = _config(tmp_path)
    run_id = "20261016T000000Z_aaaaaa"
    ingest(cfg, run_id=run_id)
    SAMPLE_MODIFIED = tmp_path / "sample_novel.txt"
    SAMPLE_MODIFIED.write_text(
        SAMPLE.read_text(encoding="utf-8") + "第4章 新章\n新增内容。\n", encoding="utf-8"
    )
    with pytest.raises(IngestError):
        ingest(_config(tmp_path, source=SAMPLE_MODIFIED), run_id=run_id, resume=True)


def test_resume_handles_added_source(tmp_path):
    """续跑时新增一个来源，只处理新来源追加记录。"""
    second = tmp_path / "second.txt"
    second.write_text("第1章 甲\n正文甲\n第2章 乙\n正文乙\n", encoding="utf-8")

    cfg = _config(tmp_path, source=tmp_path / "books")
    (tmp_path / "books").mkdir()
    (tmp_path / "books" / "a.txt").write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    run_id = "20261016T000000Z_aaaaaa"
    _, first = ingest(cfg, run_id=run_id)
    assert len(first.sources) == 1

    (tmp_path / "books" / "b.txt").write_text(second.read_text(encoding="utf-8"), encoding="utf-8")
    _, after = ingest(cfg, run_id=run_id, resume=True)
    assert len(after.sources) == 2
    assert len(after.chapters) > len(first.chapters)


def test_oversized_single_line_gets_its_own_chunk_and_a_warning(tmp_path):
    book = tmp_path / "long.txt"
    book.write_text(
        "第1章 长行\n" + "甲" * 900 + "\n第2章 短\n正文\n",
        encoding="utf-8",
    )
    cfg = _config(tmp_path, source=book, chunk_target_chars=100, chunk_max_chars=200)
    _, manifest = ingest(cfg, run_id="20261016T000000Z_aaaaaa")
    assert any("超过 chunk_max_chars" in w for w in manifest.warnings)
    source = read_source(book, source_id="long")
    for chapter in manifest.chapters:
        restored = rebuild_chapter(source.lines, chapter, manifest.chunks_of(chapter.chapter_id))
        assert restored == "".join(source.lines[chapter.start_line : chapter.end_line])


def test_existing_run_is_not_overwritten_without_resume(tmp_path):
    cfg = _config(tmp_path)
    run_id = "20261016T000000Z_aaaaaa"
    ingest(cfg, run_id=run_id)
    from novel_to_tavern.paths import RunDirError

    with pytest.raises(RunDirError):
        ingest(cfg, run_id=run_id, resume=False)


def test_summary_report_is_written_and_mentions_lossless_check(tmp_path):
    run_dir, _ = ingest(_config(tmp_path), run_id="20261016T000000Z_aaaaaa")
    report = (run_dir / "reports" / SUMMARY_NAME).read_text(encoding="utf-8")
    assert "无损性校验" in report
    assert "章节数" in report
