"""字段映射黄金断言。

这些断言就是"不许再猜字段"的落地点：改映射必须先改这里，并同步
docs/FORMAT_COMPATIBILITY.md。
"""

from __future__ import annotations

import json

from novel_to_tavern.tavern import (
    FIELD_MAP_EMBEDDED_TO_STANDALONE,
    CharBookPosition,
    EntryDraft,
    build_card_v2,
    build_standalone_worldbook,
    dumps,
    to_plain,
    validate_parity,
)

DRAFT = EntryDraft(
    entry_id="character_x",
    title="某角色",
    content="某角色的说明。",
    keys=("甲", "乙"),
    secondary_keys=("灰港",),
    insertion_order=30,
    position=CharBookPosition.after_char,
)

ALWAYS_ON = EntryDraft(
    entry_id="rules",
    title="世界运行规则",
    content="规则正文。",
    always_on=True,
    insertion_order=10,
    position=CharBookPosition.before_char,
)

DRAFTS = [ALWAYS_ON, DRAFT]


def _embedded():
    card = build_card_v2(name="测试卡", description="描述", drafts=DRAFTS)
    return card.data.character_book.entries


def _standalone():
    book = build_standalone_worldbook(DRAFTS)
    return [book.entries[str(i)] for i in range(len(DRAFTS))]


def test_embedded_uses_string_position_standalone_uses_number():
    embedded, standalone = _embedded()[1], _standalone()[1]
    assert embedded.position == "after_char"
    assert isinstance(embedded.position, str)
    assert standalone.position == 1
    assert isinstance(standalone.position, int)


def test_before_char_maps_to_zero_only_in_embedded_form():
    embedded, standalone = _embedded()[0], _standalone()[0]
    assert embedded.position == "before_char"
    assert standalone.position == 0


def test_key_field_names_differ():
    embedded, standalone = _embedded()[1], _standalone()[1]
    assert embedded.keys == ["甲", "乙"]
    assert standalone.key == ["甲", "乙"]
    assert standalone.keysecondary == ["灰港"]
    assert embedded.secondary_keys == ["灰港"]


def test_enabled_and_disable_are_inverted():
    card = build_card_v2(
        name="测试卡",
        description="",
        drafts=[EntryDraft(entry_id="d", title="t", content="c", keys=("k",), enabled=False)],
    )
    embedded = card.data.character_book.entries[0]
    standalone = build_standalone_worldbook(
        [EntryDraft(entry_id="d", title="t", content="c", keys=("k",), enabled=False)]
    ).entries["0"]
    assert embedded.enabled is False
    assert standalone.disable is True
    # 反向：默认启用时 disable 必须是 false。
    assert _embedded()[1].enabled is True
    assert _standalone()[1].disable is False


def test_insertion_order_maps_to_order():
    assert _embedded()[1].insertion_order == 30
    assert _standalone()[1].order == 30


def test_entry_id_maps_to_uid():
    assert [e.id for e in _embedded()] == [0, 1]
    assert [e.uid for e in _standalone()] == [0, 1]
    assert sorted(build_standalone_worldbook(DRAFTS).entries) == ["0", "1"]


def test_title_goes_to_comment_and_name_is_never_emitted():
    for entry in _embedded():
        assert entry.comment
        assert "name" not in (entry.model_extra or {})
    assert _embedded()[1].comment == "某角色"
    assert _standalone()[1].comment == "某角色"


def test_empty_title_falls_back_to_entry_id_so_memo_always_exists():
    entry = EntryDraft(entry_id="no_title", title="", content="c", keys=("k",))
    embedded = build_card_v2(name="卡", description="", drafts=[entry]).data.character_book.entries[0]
    assert embedded.comment == "no_title"


def test_fields_without_target_meaning_are_not_emitted():
    """name / priority / case_sensitive / use_regex 不属于本项目输出集。"""
    embedded_json = json.loads(dumps(build_card_v2(name="卡", description="", drafts=DRAFTS)))
    entry_keys = set(embedded_json["data"]["character_book"]["entries"][0])
    assert "priority" not in entry_keys
    assert "case_sensitive" not in entry_keys
    assert "use_regex" not in entry_keys
    assert "uid" not in entry_keys


def test_always_on_maps_to_constant_in_both_forms():
    assert _embedded()[0].constant is True
    assert _standalone()[0].constant is True
    # 非常驻条目在两种形态里都不应写成 constant=True
    assert _embedded()[1].constant in (None, False)
    assert _standalone()[1].constant is False


def test_standalone_entry_carries_the_full_st_template():
    """独立世界书保留 ST 的 34 个模板字段，且默认值取自源码。"""
    entry = to_plain(_standalone()[1], exclude_none=False)
    assert len(entry) == 34
    assert entry["depth"] == 4  # DEFAULT_DEPTH
    assert entry["groupWeight"] == 100  # DEFAULT_WEIGHT
    assert entry["selectiveLogic"] == 0  # AND_ANY
    assert entry["probability"] == 100
    assert entry["useProbability"] is True
    assert entry["order"] == 30
    assert entry["addMemo"] is True


def test_embedded_form_omits_unset_optionals():
    entry = to_plain(_embedded()[0])
    assert "secondary_keys" not in entry
    assert "selective" not in entry


def test_field_map_is_consistent_with_real_output():
    """对照表必须覆盖内嵌输出集的每一个跨格式字段。"""
    assert FIELD_MAP_EMBEDDED_TO_STANDALONE["enabled"] == "disable"
    assert FIELD_MAP_EMBEDDED_TO_STANDALONE["keys"] == "key"
    assert FIELD_MAP_EMBEDDED_TO_STANDALONE["id"] == "uid"
    assert FIELD_MAP_EMBEDDED_TO_STANDALONE["insertion_order"] == "order"

    embedded = to_plain(_embedded()[1])
    standalone = to_plain(_standalone()[1], exclude_none=False)
    for source, target in FIELD_MAP_EMBEDDED_TO_STANDALONE.items():
        if source in embedded:
            assert target in standalone, f"{source} → {target} 缺失"


def test_serializer_output_passes_parity_check():
    card = build_card_v2(name="测试卡", description="", drafts=DRAFTS)
    report = validate_parity(card, build_standalone_worldbook(DRAFTS))
    assert report.errors == []
    assert report.ok


def test_parity_check_catches_a_flipped_polarity():
    """故意把内嵌 enabled 翻掉，parity 必须报错而不是放过。"""
    card = build_card_v2(name="测试卡", description="", drafts=DRAFTS)
    card.data.character_book.entries[1].enabled = False
    report = validate_parity(card, build_standalone_worldbook(DRAFTS))
    assert not report.ok
    assert any("极性" in e for e in report.errors)
