"""酒馆目标格式层。

内部数据模型（Phase 2 起建立）在这里经 serializer 映射成 SillyTavern/Tavo
可导入的 JSON。格式依据见 docs/FORMAT_COMPATIBILITY.md，字段不猜。
"""

from __future__ import annotations

from .position import (
    CharBookPosition,
    PositionTypeError,
    PromptRole,
    SelectiveLogic,
    WiPosition,
    char_book_to_wi_position,
    coerce_char_book_position,
)
from .serializer import (
    FIELD_MAP_EMBEDDED_TO_STANDALONE,
    EntryDraft,
    build_card_v2,
    build_character_book,
    build_standalone_worldbook,
    dump_to,
    dumps,
    to_plain,
)
from .spec_v2 import SPEC_NAME, SPEC_VERSION, CardV2, CharData, CharacterBook, CharacterBookEntry
from .validator import (
    ValidationReport,
    validate_card,
    validate_no_secrets,
    validate_parity,
    validate_worldbook,
)
from .wi_standalone import WiEntry, WorldbookFile

__all__ = [
    "SPEC_NAME",
    "SPEC_VERSION",
    "FIELD_MAP_EMBEDDED_TO_STANDALONE",
    "CardV2",
    "CharBookPosition",
    "CharData",
    "CharacterBook",
    "CharacterBookEntry",
    "EntryDraft",
    "PositionTypeError",
    "PromptRole",
    "SelectiveLogic",
    "ValidationReport",
    "WiEntry",
    "WiPosition",
    "WorldbookFile",
    "build_card_v2",
    "build_character_book",
    "build_standalone_worldbook",
    "char_book_to_wi_position",
    "coerce_char_book_position",
    "dump_to",
    "dumps",
    "to_plain",
    "validate_card",
    "validate_no_secrets",
    "validate_parity",
    "validate_worldbook",
]
