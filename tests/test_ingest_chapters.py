"""章节检测：重复标题折叠、区段无缝铺满、fallback 退路。"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_tavern.ingest import (
    build_chapter_index,
    find_headings,
    merge_duplicate_headings,
    read_source,
    rebuild_text,
)

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return read_source(SAMPLE, source_id="sample").lines


def _index(lines, **kwargs):
    return build_chapter_index(lines, source_id="sample", **kwargs)


def test_headings_are_found(lines):
    headings = find_headings(lines)
    # 夹具里每章标题出现两次（站点导航 + 正文标题）
    assert len(headings) == 6
    assert [h.raw for h in headings[:2]] == ["第1章 起风（1）", "第1章 起风（1）"]


def test_duplicate_headings_are_merged_keeping_the_later_one(lines):
    merged, dropped, duplicate_map = merge_duplicate_headings(find_headings(lines))
    assert len(merged) == 3
    assert len(dropped) == 3
    for keep, drop in zip(merged, dropped):
        assert keep.line_index > drop.line_index  # 保留正文标题，丢掉导航标题
    # 每个保留标题都记录了自己被折叠掉的那一行
    assert set(duplicate_map) == {h.line_index for h in merged}
    assert all(len(v) == 1 for v in duplicate_map.values())


def test_chapters_are_indexed_with_metadata(lines):
    index = _index(lines)
    assert index.detection.strategy == "regex"
    assert len(index.chapters) == 3
    titles = [c.title for c in index.chapters]
    assert titles == ["起风（1）", "起风（2）", "落雪"]
    assert [c.number for c in index.chapters] == ["1", "2", "3"]
    assert all(c.char_count > 0 for c in index.chapters)
    assert all(c.duplicate_heading_lines for c in index.chapters)


def test_chapter_bodies_do_not_contain_site_noise(lines):
    """正文起点必须是真正的标题行，不能把「未知」那行吃进来。"""
    index = _index(lines)
    for chapter in index.chapters:
        assert lines[chapter.start_line].strip().startswith(f"第{chapter.number}章")
        assert "未知" not in lines[chapter.start_line]


def test_regions_tile_the_whole_file_without_gaps_or_overlap(lines):
    index = _index(lines)
    covered = sorted((r.start_line, r.end_line) for r in index.regions)
    cursor = 0
    for start, end in covered:
        assert start == cursor, f"行 {cursor}–{start} 未被覆盖"
        cursor = end
    assert cursor == len(lines)


def test_regions_rebuild_the_original_text_exactly(lines):
    index = _index(lines)
    assert rebuild_text(lines, index.regions) == "".join(lines)


def test_site_noise_and_front_matter_are_recorded_not_deleted(lines):
    index = _index(lines)
    kinds = {r.kind for r in index.regions}
    assert "front_matter" in kinds
    assert "site_noise" in kinds


def test_fallback_when_no_headings_exist():
    plain = [f"这是第 {i} 行普通文字。\n" for i in range(200)]
    index = build_chapter_index(plain, source_id="plain", target_chars=100)
    assert index.detection.strategy == "fallback"
    assert index.detection.notes  # 必须说明为什么降级
    assert len(index.chapters) > 1
    assert rebuild_text(plain, index.regions) == "".join(plain)
    assert sum(c.char_count for c in index.chapters) == sum(len(line) for line in plain)


def test_explicit_rule_fails_loudly_instead_of_silently_falling_back():
    plain = ["没有标题\n"] * 50
    with pytest.raises(ValueError, match="只找到"):
        build_chapter_index(plain, source_id="plain", strategy="regex")


def test_custom_pattern_is_honoured():
    text = ["## 第一节\n", "正文甲\n", "## 第二节\n", "正文乙\n"]
    index = build_chapter_index(
        text, source_id="md", pattern=r"^##\s*(.+)$", strategy="regex"
    )
    assert index.detection.strategy == "regex"
    assert [c.title for c in index.chapters] == ["第一节", "第二节"]


def test_headings_inside_body_are_not_matched_mid_line():
    text = ["第1章 甲\n", "他说「这是第3章里的话」。\n", "第2章 乙\n", "正文\n"]
    headings = find_headings(text)
    assert [h.line_index for h in headings] == [0, 2]
