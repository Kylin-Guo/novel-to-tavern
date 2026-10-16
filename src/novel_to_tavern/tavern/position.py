"""位置枚举与跨格式转换。

内嵌 `character_book` 与独立世界书的 `position` **类型不同、枚举不同**，
混用会导致条目静默错位。见 docs/FORMAT_COMPATIBILITY.md §6 陷阱 1。
"""

from __future__ import annotations

from enum import Enum, IntEnum


class CharBookPosition(str, Enum):
    """内嵌 `character_book` 条目的 position —— **字符串**。"""

    before_char = "before_char"
    after_char = "after_char"


class WiPosition(IntEnum):
    """独立世界书条目的 position —— **数字 0–7**（ST `world_info_position`）。"""

    before = 0
    after = 1
    ANTop = 2
    ANBottom = 3
    atDepth = 4
    EMTop = 5
    EMBottom = 6
    outlet = 7


class SelectiveLogic(IntEnum):
    """ST `world_info_logic`。"""

    AND_ANY = 0
    NOT_ALL = 1
    NOT_ANY = 2
    AND_ALL = 3


class PromptRole(IntEnum):
    """条目注入时的角色。"""

    system = 0
    user = 1
    assistant = 2


#: ST 模板默认值（world-info.js:96 `DEFAULT_DEPTH` / `DEFAULT_WEIGHT`）。
DEFAULT_DEPTH = 4
DEFAULT_WEIGHT = 100
#: ST 模板里独立世界书条目的 `order` 默认值。
DEFAULT_ORDER = 100


class PositionTypeError(TypeError):
    """内嵌 position 拿到了数字或其它非法类型。"""


def coerce_char_book_position(value: object) -> CharBookPosition:
    """把内嵌条目的 position 收敛成字符串枚举。

    ST 的判断是 `entry.position === 'before_char' ? 0 : 1` —— 传数字不会报错，
    只会静默变成 `after_char`。所以这里对数字**直接抛错**，不允许"碰巧对"。
    """
    if isinstance(value, CharBookPosition):
        return value
    if isinstance(value, bool) or isinstance(value, int):
        raise PositionTypeError(
            f"内嵌 character_book 的 position 必须是字符串 'before_char'/'after_char'，"
            f"收到数字 {value!r}。数字在 SillyTavern 中会被静默当成 after_char；"
            f"如需数字 0–7 请改用独立世界书（WiPosition）。"
        )
    if isinstance(value, str):
        try:
            return CharBookPosition(value)
        except ValueError as exc:
            raise PositionTypeError(
                f"未知的内嵌 position：{value!r}，只允许 "
                f"{[p.value for p in CharBookPosition]}。"
            ) from exc
    raise PositionTypeError(f"无法识别的 position 类型：{type(value).__name__}")


def char_book_to_wi_position(position: CharBookPosition) -> WiPosition:
    """内嵌字符串位置 → 独立世界书数字位置。

    只有 before/after 两个语义可无损对应；其余数字位置只能从独立世界书侧设置。
    """
    if position is CharBookPosition.before_char:
        return WiPosition.before
    return WiPosition.after
