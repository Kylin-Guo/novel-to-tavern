"""风格世界书条目：分组、触发词、unknown 维度、JSON 往返、剧透拦截。"""

from __future__ import annotations

import pytest

from novel_to_tavern.style import (
    STYLE_DIMENSIONS,
    STYLE_ENTRY_GROUPS,
    STYLE_ENTRY_KEYS,
    STYLE_ENTRY_MUST_NOT_TRIGGER,
    StyleLeakError,
    StyleProfile,
    build_style_entries,
    check_style_no_plot_leak,
    load_style_entries,
    write_style_entries,
)
from novel_to_tavern.tavern.triggers import matched_keys
from novel_to_tavern.timeline.worldbible import PlannedEntry

from style_fixtures import style_profile_payload


def _profile(**overrides) -> StyleProfile:
    return StyleProfile.model_validate(style_profile_payload(**overrides))


def test_eight_groups_ids_titles():
    entries = build_style_entries(_profile())
    assert [e.entry_id for e in entries] == [group[0] for group in STYLE_ENTRY_GROUPS]
    assert [e.title for e in entries] == [group[1] for group in STYLE_ENTRY_GROUPS]
    assert len(entries) == 8


def test_all_triggered_not_always_on():
    for entry in build_style_entries(_profile()):
        assert entry.always_on is False
        assert entry.keys == STYLE_ENTRY_KEYS
        assert entry.category == "author_style"
        assert entry.chapter_gated is False
        assert "非 canon" in "".join(entry.quality_flags)


def test_unknown_dimension_group_skipped():
    payload = style_profile_payload()
    payload["sentence_rhythm"] = {"summary": "unknown", "rules": [], "confidence": "unknown"}
    entries = build_style_entries(StyleProfile.model_validate(payload))
    ids = [e.entry_id for e in entries]
    assert "wb_style_rhythm" not in ids
    assert "wb_style_overview" in ids
    assert len(entries) == 7


def test_all_unknown_profile_generates_no_entries():
    payload = style_profile_payload()
    for dim in STYLE_DIMENSIONS:
        payload[dim] = {"summary": "unknown", "rules": [], "confidence": "unknown"}
    payload["genre_tone"] = {"summary": "unknown", "rules": [], "confidence": "unknown"}
    payload["anti_patterns"] = []
    payload["contextual_variants"] = []
    assert build_style_entries(StyleProfile.model_validate(payload)) == []


@pytest.mark.parametrize("message", STYLE_ENTRY_MUST_NOT_TRIGGER)
def test_keys_do_not_match_probes(message):
    hits = matched_keys(STYLE_ENTRY_KEYS, message)
    assert hits == [], f"{message!r} 命中了风格条目的触发词 {hits}"


def test_keys_match_an_explicit_style_request():
    for message in ("这个作者风格是什么", "分析一下叙事风格", "说说语言风格"):
        assert matched_keys(STYLE_ENTRY_KEYS, message), message


def test_entries_json_roundtrip(tmp_path):
    entries = build_style_entries(_profile())
    path = tmp_path / "entries.json"
    write_style_entries(path, entries)
    loaded = load_style_entries(path)
    assert loaded == entries


def _leaky_entry(chapter: int) -> PlannedEntry:
    return PlannedEntry(
        entry_id="wb_style_leak",
        category="author_style",
        title="作者风格：泄漏测试",
        content_runtime=f"这条规则引用了第 {chapter} 章的例子。",
        content_canonical="",
        keys=list(STYLE_ENTRY_KEYS),
        always_on=False,
        priority=40,
        quality_flags=["非 canon"],
    )


def test_leak_check_raises_on_future_chapter():
    with pytest.raises(StyleLeakError, match="第 9 章"):
        check_style_no_plot_leak([_leaky_entry(9)], upto_chapter=5)


def test_leak_check_passes_within_range():
    check_style_no_plot_leak([_leaky_entry(3)], upto_chapter=5)
    check_style_no_plot_leak([_leaky_entry(6)], upto_chapter=5)
