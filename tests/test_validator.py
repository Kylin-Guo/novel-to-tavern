"""校验器规则：错误 / 警告的分界，以及密钥扫描。"""

from __future__ import annotations

import pytest

from novel_to_tavern import secrets
from novel_to_tavern.tavern import (
    CharBookPosition,
    EntryDraft,
    PositionTypeError,
    build_card_v2,
    build_standalone_worldbook,
    dumps,
    validate_card,
    validate_no_secrets,
    validate_worldbook,
)


def _card(**draft_kwargs):
    base = {"entry_id": "e", "title": "标题", "content": "正文", "keys": ("关键词",)}
    base.update(draft_kwargs)
    return build_card_v2(name="卡", description="", drafts=[EntryDraft(**base)])


def test_clean_card_has_no_findings():
    report = validate_card(_card(), strict=True)
    assert report.ok
    assert report.warnings == []


def test_empty_name_is_an_error():
    card = _card()
    card.data.name = ""
    assert not validate_card(card).ok


def test_duplicate_ids_are_an_error():
    card = build_card_v2(
        name="卡",
        description="",
        drafts=[
            EntryDraft(entry_id="a", title="A", content="x", keys=("k1",)),
            EntryDraft(entry_id="b", title="B", content="y", keys=("k2",)),
        ],
    )
    card.data.character_book.entries[1].id = card.data.character_book.entries[0].id
    report = validate_card(card)
    assert any("id 重复" in e for e in report.errors)


def test_entry_without_keys_and_not_constant_warns():
    report = validate_card(_card(keys=()))
    assert any("永远不会被触发" in w for w in report.warnings)
    assert report.ok  # 警告不阻断导出


def test_serializer_sets_selective_when_secondary_keys_present():
    card = _card(keys=("主",), secondary_keys=("次",))
    assert card.data.character_book.entries[0].selective is True


def test_secondary_keys_without_selective_warns():
    """外部卡常见写法：写了 secondary_keys 却忘了 selective。"""
    card = _card(keys=("主",), secondary_keys=("次",))
    card.data.character_book.entries[0].selective = False
    report = validate_card(card)
    assert any("selective" in w for w in report.warnings)


def test_empty_content_warns():
    report = validate_card(_card(content="   "))
    assert any("content 为空" in w for w in report.warnings)


def test_duplicate_trigger_keys_across_entries_warn():
    card = build_card_v2(
        name="卡",
        description="",
        drafts=[
            EntryDraft(entry_id="a", title="A", content="x", keys=("灰港",)),
            EntryDraft(entry_id="b", title="B", content="y", keys=("灰港", "别处")),
        ],
    )
    report = validate_card(card)
    assert any("会一起命中" in w for w in report.warnings)


def test_too_many_always_on_entries_warns():
    card = build_card_v2(
        name="卡",
        description="",
        drafts=[
            EntryDraft(entry_id=f"c{i}", title=f"C{i}", content="x", always_on=True)
            for i in range(4)
        ],
    )
    report = validate_card(card, max_always_on=3)
    assert any("常驻条目" in w for w in report.warnings)


def test_disabled_entries_are_reported():
    report = validate_card(_card(enabled=False))
    assert report.ok
    assert any("enabled=false" in w for w in report.warnings)


def test_unknown_field_warns_by_default_and_errors_when_strict():
    card = _card()
    card.data.character_book.entries[0].__pydantic_extra__ = {"uid": 3}
    assert any("uid" in w for w in validate_card(card).warnings)
    assert any("uid" in e for e in validate_card(card, strict=True).errors)


def test_worldbook_rejects_non_numeric_entry_key():
    worldbook = build_standalone_worldbook([EntryDraft(entry_id="a", title="A", content="x", keys=("k",))])
    worldbook.entries = {"not-a-number": worldbook.entries["0"]}
    report = validate_worldbook(worldbook)
    assert any("十进制字符串" in e for e in report.errors)


def test_worldbook_rejects_key_uid_mismatch():
    worldbook = build_standalone_worldbook([EntryDraft(entry_id="a", title="A", content="x", keys=("k",))])
    worldbook.entries["0"].uid = 5
    report = validate_worldbook(worldbook)
    assert any("键与 uid 不一致" in e for e in report.errors)


def test_worldbook_rejects_empty_entries():
    from novel_to_tavern.tavern import WorldbookFile

    report = validate_worldbook(WorldbookFile())
    assert any("entries 为空" in e for e in report.errors)


def test_secret_scan_catches_registered_key():
    secrets.register_secret("sk-live-abcdefghijklmnop1234")
    report = validate_no_secrets('{"x": "sk-live-abcdefghijklmnop1234"}')
    assert not report.ok


def test_secret_scan_passes_on_clean_text():
    assert validate_no_secrets('{"x": "普通内容"}').ok


def test_serializer_refuses_to_emit_a_registered_secret():
    key = "sk-leak-abcdefghijklmnop9999"
    secrets.register_secret(key)
    card = _card(content=f"不小心写进去的 {key}")
    with pytest.raises(ValueError, match="密钥"):
        dumps(card)


def test_secret_scan_allows_normal_chinese_text():
    """避免脱敏规则误伤：中文正文必须原样保留。"""
    text = "灰港的雾很浓，潮汐钟敲了十一响。"
    assert secrets.redact(text) == text


def test_position_guard_keeps_numeric_out_of_embedded_entries():
    """回归护栏：走 serializer 也不能把数字位置写进内嵌条目。"""
    ok = _card(position=CharBookPosition.after_char)
    assert ok.data.character_book.entries[0].position == "after_char"

    with pytest.raises(PositionTypeError):
        _card(position=1)
