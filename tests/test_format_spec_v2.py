"""V2 卡模型：字段必填性、position 类型防线、解析往返。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from novel_to_tavern.tavern import (
    CharBookPosition,
    CardV2,
    CharacterBookEntry,
    PositionTypeError,
    WiPosition,
    char_book_to_wi_position,
    coerce_char_book_position,
)

MINIMAL_ENTRY = {
    "id": 0,
    "keys": ["灰港"],
    "content": "港口的雾。",
    "enabled": True,
    "insertion_order": 10,
    "position": "after_char",
}


def test_minimal_entry_is_accepted():
    entry = CharacterBookEntry(**MINIMAL_ENTRY)
    assert entry.position is CharBookPosition.after_char


def test_enabled_is_required_because_missing_means_disabled():
    """ST 是 disable = !enabled，缺字段会被判成禁用，所以模型不给默认值。"""
    payload = {k: v for k, v in MINIMAL_ENTRY.items() if k != "enabled"}
    with pytest.raises(ValidationError) as excinfo:
        CharacterBookEntry(**payload)
    assert "enabled" in str(excinfo.value)


@pytest.mark.parametrize("bad", [0, 1, 2, True, None])
def test_numeric_position_is_rejected(bad):
    """数字会被 ST 静默当成 after_char，必须直接失败而不是"碰巧对"。"""
    with pytest.raises((PositionTypeError, ValidationError)):
        CharacterBookEntry(**{**MINIMAL_ENTRY, "position": bad})


@pytest.mark.parametrize("bad", ["after", "before", "", "AFTER_CHAR", 0.5])
def test_unknown_position_string_is_rejected(bad):
    with pytest.raises((PositionTypeError, ValidationError)):
        coerce_char_book_position(bad)


def test_coerce_passes_through_enum():
    assert coerce_char_book_position(CharBookPosition.before_char) is CharBookPosition.before_char


def test_position_maps_to_numeric_form_only_for_worldbook():
    assert char_book_to_wi_position(CharBookPosition.before_char) is WiPosition.before
    assert char_book_to_wi_position(CharBookPosition.after_char) is WiPosition.after


def test_before_char_does_not_silently_become_after():
    """回归护栏：这是本项目最容易写错、且不会报错的一处。"""
    entry = CharacterBookEntry(**{**MINIMAL_ENTRY, "position": "before_char"})
    assert entry.position is CharBookPosition.before_char
    assert entry.position.value == "before_char"
    assert entry.position is not CharBookPosition.after_char


def test_spec_fields_are_literal():
    with pytest.raises(ValidationError):
        CardV2(spec="chara_card_v3", spec_version="2.0", data={"name": "x"})
    with pytest.raises(ValidationError):
        CardV2(spec="chara_card_v2", spec_version=2.0, data={"name": "x"})


def test_unknown_fields_are_preserved_not_dropped():
    """V2 规范：已存在的可选字段不得被破坏。"""
    entry = CharacterBookEntry(**{**MINIMAL_ENTRY, "uid": 7, "chub_extra": {"a": 1}})
    extra = entry.model_extra or {}
    assert extra["uid"] == 7
    assert extra["chub_extra"] == {"a": 1}


def test_parse_dump_parse_roundtrip_is_stable(fixtures_dir):
    from novel_to_tavern.tavern import dumps

    raw = json.loads((fixtures_dir.parent.parent / "examples" / "fixtures" / "minimal_world_simulator_v2.json").read_text(encoding="utf-8"))
    first = CardV2.model_validate(raw)
    second = CardV2.model_validate(json.loads(dumps(first)))
    assert dumps(first) == dumps(second)
