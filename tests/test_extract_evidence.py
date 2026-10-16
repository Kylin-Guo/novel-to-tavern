"""证据定位：行号必须由原文搜索得出，不接受模型自报。"""

from __future__ import annotations

import pytest

from novel_to_tavern.extract import MAX_QUOTE_CHARS, locate_quote, normalize_for_match

LINES = [
    "第1章 起风（1）\n",
    "北风从山口压下来的时候，镇上的人正在收摊。\n",
    "铁匠铺的炉子还红着，火星被风卷起来。\n",
    "\n",
    "少年把斗篷的领子竖起来，沿着河堤往南走。\n",
]


def test_exact_quote_is_located_on_its_line():
    check = locate_quote(LINES, "铁匠铺的炉子还红着")
    assert check.located is not None
    assert (check.located.start_line, check.located.end_line) == (2, 3)


def test_quote_is_matched_across_whitespace_differences():
    """换行/空格差异不该让定位失败。"""
    check = locate_quote(LINES, "铁匠铺的炉子还红着， 火星被风卷起来。")
    assert check.located is not None
    assert check.located.start_line == 2


def test_quote_spanning_two_lines_is_located():
    check = locate_quote(LINES, "镇上的人正在收摊。铁匠铺的炉子还红着")
    assert check.located is not None
    assert (check.located.start_line, check.located.end_line) == (1, 3)


def test_fabricated_quote_is_rejected():
    check = locate_quote(LINES, "他们一起喝了很多酒，笑着说起往事")
    assert check.located is None
    assert "找不到" in check.reason


def test_empty_quote_is_rejected():
    assert locate_quote(LINES, "").located is None
    assert locate_quote(LINES, "   ").located is None


def test_overlong_quote_is_rejected():
    check = locate_quote(LINES, "长" * (MAX_QUOTE_CHARS + 1))
    assert check.located is None
    assert "过长" in check.reason


def test_window_restricts_search_to_the_chunk():
    """引文只允许在本分块的行范围内命中，避免跨块误锚。"""
    check = locate_quote(LINES, "铁匠铺的炉子还红着", window=(0, 2))
    assert check.located is None
    check_ok = locate_quote(LINES, "铁匠铺的炉子还红着", window=(0, 3))
    assert check_ok.located is not None


def test_span_limit_prevents_gist_style_quotes():
    """跨越太多行的"引文"其实是概括，应当拒绝。"""
    lines = [f"第{i}行的内容。\n" for i in range(30)]
    check = locate_quote(lines, "第0行的内容。第29行的内容。")
    assert check.located is None


def test_matched_text_is_the_real_source_text():
    check = locate_quote(LINES, "少年把斗篷的领子竖起来")
    assert check.located is not None
    assert "少年把斗篷的领子竖起来" in check.located.matched_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("甲 乙\n丙", "甲乙丙"),
        ("甲\t乙", "甲乙"),
        ("甲乙", "甲乙"),
    ],
)
def test_normalize_strips_all_whitespace(raw, expected):
    assert normalize_for_match(raw) == expected
