"""触发模拟与预算体检。

这一层要挡的是本项目实测踩过的那个坑：一句话提到主角，
命中 **117 条 ≈ 6 万 token**，上下文直接被冲爆 —— 而 JSON 完全合法，
静态校验一条错误都报不出来。
"""

from __future__ import annotations

import pytest

from novel_to_tavern.tavern.triggers import (
    SHARED_KEY_THRESHOLD,
    SUSPICIOUS_KEY_LENGTH,
    audit_triggers,
    key_matches,
    matched_keys,
    simulate,
)
from novel_to_tavern.timeline.worldbible import PlannedEntry


def _entry(eid: str, title: str, keys, *, always_on=False, content="内容", category="character"):
    return PlannedEntry(
        entry_id=eid,
        category=category,
        title=title,
        content_runtime=content,
        content_canonical=content,
        keys=list(keys),
        always_on=always_on,
        estimated_tokens=len(content),
    )


# --- 匹配语义 --------------------------------------------------------------


def test_key_match_is_substring_and_case_insensitive():
    assert key_matches("西泽尔", "西泽尔是谁？")
    assert key_matches("abc", "xxABCxx")
    assert not key_matches("西泽尔", "薇若兰是谁？")


def test_empty_key_never_matches():
    assert not key_matches("", "任何文本")
    assert not key_matches("键", "")


def test_matched_keys_returns_every_hit():
    assert matched_keys(["甲", "乙", "丙"], "甲乙一起走了") == ["甲", "乙"]


# --- 模拟 ------------------------------------------------------------------


def test_constant_entry_is_always_in_context():
    entries = [_entry("wb_core", "规则", [], always_on=True), _entry("wb_a", "甲", ["甲"])]
    probe = simulate(entries, "今天天气不错")
    assert [m.title for m in probe.matched] == ["规则"]
    assert probe.triggered_count == 0


def test_trigger_fires_on_name_in_a_negated_sentence():
    """子串匹配不认识否定 —— 「我没见过甲」一样会命中。这是要实测确认的风险点。"""
    entries = [_entry("wb_a", "甲", ["甲"])]
    assert simulate(entries, "我没见过甲").triggered_count == 1


def test_alias_key_fires_too():
    entries = [_entry("wb_a", "甲", ["甲", "小甲"])]
    matched = simulate(entries, "小甲在哪").matched[0]
    assert "小甲" in matched.matched_keys
    # 顺带暴露子串匹配的一个性质：短名是长名的子串时，两个键会一起命中。
    # 这不是 bug，但设计触发词时要记得 —— 「甲」这种单字主名会连带一切含它的词。
    assert matched.matched_keys == ["甲", "小甲"]


def test_unrelated_chat_does_not_over_trigger():
    entries = [
        _entry("wb_a", "甲", ["甲"]),
        _entry("wb_b", "乙", ["乙"]),
        _entry("wb_core", "规则", [], always_on=True),
    ]
    probe = simulate(entries, "今天天气不错，我们随便聊聊吧。")
    assert probe.triggered_count == 0
    assert len(probe.matched) == 1


def test_the_cascade_that_actually_happened_is_detectable():
    """复现那次事故的形状：一个常用键被上百条条目共用。"""
    entries = [_entry(f"wb_{i}", f"角色{i}", ["西泽尔"]) for i in range(117)]
    probe = simulate(entries, "西泽尔是谁？")
    assert probe.triggered_count == 117
    report = audit_triggers(entries)
    assert any(r.key == "西泽尔" and r.entry_count == 117 for r in report.key_risks)


# --- 体检 ------------------------------------------------------------------


def test_short_keys_are_flagged():
    entries = [_entry("wb_a", "甲", ["王"])]
    report = audit_triggers(entries)
    assert any(r.key == "王" and "太短" in r.reason for r in report.key_risks)
    assert SUSPICIOUS_KEY_LENGTH == 2


def test_shared_keys_are_flagged_as_a_group():
    entries = [_entry(f"wb_{i}", f"角色{i}", ["将军"]) for i in range(SHARED_KEY_THRESHOLD)]
    report = audit_triggers(entries)
    assert any("共用" in r.reason for r in report.key_risks)


def test_a_key_used_by_one_entry_is_not_flagged():
    entries = [_entry("wb_a", "甲", ["西泽尔·博尔吉亚"])]
    assert audit_triggers(entries).key_risks == []


def test_budget_is_split_between_always_on_and_triggered():
    entries = [
        _entry("wb_core", "规则", [], always_on=True, content="x" * 100),
        _entry("wb_a", "甲", ["甲"], content="y" * 50),
    ]
    report = audit_triggers(entries)
    assert report.always_on_entries == 1
    assert report.triggered_entries == 1
    assert report.always_on_tokens == 100
    assert report.total_tokens == 150


def test_worst_case_counts_the_closure_not_just_one_entry():
    entries = [_entry(f"wb_{i}", f"角色{i}", ["甲", unique], content="c" * 100)
               for i, unique in enumerate(["u1", "u2", "u3"])]
    report = audit_triggers(entries)
    assert report.worst_case_entries == 3
    assert report.worst_case_tokens == 300
    assert report.worst_entry_id


def test_worst_case_includes_the_always_on_budget():
    entries = [
        _entry("wb_core", "规则", [], always_on=True, content="x" * 40),
        _entry("wb_a", "甲", ["甲"], content="y" * 10),
    ]
    report = audit_triggers(entries)
    assert report.worst_case_tokens == 50


def test_single_key_entries_are_listed():
    entries = [
        _entry("wb_a", "甲", ["甲"]),
        _entry("wb_b", "乙", ["乙", "小乙"]),
    ]
    assert audit_triggers(entries).single_key_entries == ["甲"]


def test_category_breakdown_sums_to_the_total():
    entries = [
        _entry("wb_a", "甲", ["甲"], category="character", content="a" * 10),
        _entry("wb_b", "某地", ["某地"], category="place", content="b" * 20),
    ]
    report = audit_triggers(entries)
    assert report.by_category == {"character": 1, "place": 1}
    assert report.chars_by_category == {"character": 10, "place": 20}
    assert sum(report.tokens_by_category.values()) == report.total_tokens


def test_report_always_says_the_numbers_are_estimates():
    report = audit_triggers([_entry("wb_a", "甲", ["甲"])])
    joined = " ".join(report.notes)
    assert "粗估" in joined
    assert "近似" in joined


def test_probes_are_simulated_and_carried_in_the_report():
    entries = [_entry("wb_a", "甲", ["甲"]), _entry("wb_core", "规则", [], always_on=True)]
    report = audit_triggers(entries, probes=["甲是谁？", "今天天气不错"])
    assert [p.message for p in report.probes] == ["甲是谁？", "今天天气不错"]
    assert report.probes[0].triggered_count == 1
    assert report.probes[1].triggered_count == 0


def test_no_entries_is_not_an_error():
    report = audit_triggers([])
    assert report.entry_total == 0
    assert report.worst_case_tokens == 0
    assert report.key_risks == []
