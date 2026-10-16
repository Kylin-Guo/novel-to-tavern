"""原文读取：只读、指纹、无损行切分。"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_tavern.ingest import (
    SourceReadError,
    line_offsets,
    read_source,
    sha256_of,
)

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_novel.txt"


def test_lines_rejoin_to_the_exact_original_text():
    """无损重组的基础保证：splitlines(keepends=True) 拼回去必须逐字节相同。"""
    source = read_source(SAMPLE, source_id="sample")
    assert "".join(source.lines) == source.text
    assert source.total_chars == len(source.text)
    assert source.total_lines == len(source.lines)


def test_sha256_matches_raw_bytes():
    source = read_source(SAMPLE, source_id="sample")
    assert source.sha256 == sha256_of(SAMPLE.read_bytes())


def test_source_is_not_modified_by_reading():
    before = SAMPLE.read_bytes()
    read_source(SAMPLE, source_id="sample")
    assert SAMPLE.read_bytes() == before


def test_line_offsets_are_monotonic_and_end_at_total():
    source = read_source(SAMPLE, source_id="sample")
    offsets = line_offsets(source.lines)
    assert len(offsets) == len(source.lines) + 1
    assert offsets[0] == 0
    assert offsets[-1] == source.total_chars
    assert offsets == sorted(offsets)


def test_missing_file_raises(tmp_path):
    with pytest.raises(SourceReadError, match="找不到原文文件"):
        read_source(tmp_path / "nope.txt")


def test_unsupported_suffix_raises(tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(SourceReadError, match="暂不支持的后缀"):
        read_source(path)


def test_wrong_encoding_raises_with_clear_message(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("中文内容".encode("gbk"))
    with pytest.raises(SourceReadError, match="无法按"):
        read_source(path, encoding="utf-8")


def test_newline_style_is_detected(tmp_path):
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes("甲\r\n乙\r\n".encode("utf-8"))
    assert read_source(crlf).newline_style == "crlf"

    lf = tmp_path / "lf.txt"
    lf.write_bytes("甲\n乙\n".encode("utf-8"))
    assert read_source(lf).newline_style == "lf"


def test_source_id_falls_back_to_filename_stem():
    assert read_source(SAMPLE).source_id == "sample_novel"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("天之炽Ⅰ：红龙的归来", "天之炽Ⅰ-红龙的归来"),
        ("book 1 (draft)", "book-1-draft"),
        ("纯中文", "纯中文"),
        ("...", "source"),
        ("a/b\\c", "a-b-c"),
    ],
)
def test_source_ids_are_safe_for_paths_and_ids(name, expected):
    from novel_to_tavern.ingest.source import slugify_source_id

    assert slugify_source_id(name) == expected
