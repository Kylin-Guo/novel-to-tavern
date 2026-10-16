"""证据定位：行号必须由原文搜索得出，不接受模型自报。"""

from __future__ import annotations

import pytest

from novel_to_tavern.extract import (
    MAX_QUOTE_CHARS,
    MIN_QUOTE_CHARS,
    EvidenceStats,
    locate_quote,
    normalize_for_match,
)

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


# --- 「找到了」不等于「只有一处」 ---------------------------------------------


def test_a_quote_that_appears_twice_is_marked_ambiguous():
    """同一句在原文里出现两次时，取第一处是**猜**。必须说出来。"""
    lines = ["他把剑放下了。\n", "中间隔了一行。\n", "他把剑放下了。\n"]
    check = locate_quote(lines, "他把剑放下了。")
    assert check.located is not None
    assert check.ambiguous is True
    assert check.match_count == 2
    assert check.located.match_count == 2
    assert "2 次" in check.reason


def test_a_unique_quote_is_not_marked_ambiguous():
    check = locate_quote(LINES, "铁匠铺的炉子还红着")
    assert check.located is not None
    assert check.ambiguous is False
    assert check.match_count == 1
    assert check.reason == ""


def test_ambiguity_is_counted_across_the_whole_window_not_just_the_first_line():
    """两处命中相隔很远时，第一次匹配的局部上下文看不出来 —— 必须全局计数。"""
    lines = ["甲" * 50 + "目标句子出现了。\n"] + ["无关内容。\n"] * 20 + ["目标句子出现了。\n"]
    check = locate_quote(lines, "目标句子出现了。")
    assert check.ambiguous is True
    assert check.match_count == 2


def test_too_short_a_quote_is_rejected():
    """两个字的引文在长篇里必然多处命中，等于没有来源。"""
    check = locate_quote(LINES, "炉子")
    assert check.located is None
    assert "过短" in check.reason
    assert MIN_QUOTE_CHARS == 4


def test_quote_at_exactly_the_minimum_length_is_accepted():
    lines = ["甲乙丙丁在这里。\n"]
    check = locate_quote(lines, "甲乙丙丁")
    assert check.located is not None


def test_whitespace_does_not_count_toward_the_minimum():
    """「甲 乙 丙」只有 3 个非空白字符 —— 不能靠空格凑长度。"""
    check = locate_quote(LINES, "炉 子 还")
    assert check.located is None
    assert "过短" in check.reason


def test_evidence_stats_track_ambiguity_separately_from_location():
    stats = EvidenceStats()
    stats.add(True)
    stats.add(True, ambiguous=True)
    stats.add(False)
    assert (stats.total, stats.located, stats.unlocated, stats.ambiguous) == (3, 2, 1, 1)
    assert stats.coverage == pytest.approx(2 / 3)
    # 唯一率的分母是**已定位**的条数，找不到的归 coverage 管
    assert stats.unique_rate == pytest.approx(0.5)
