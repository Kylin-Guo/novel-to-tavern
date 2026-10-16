"""独立世界书（standalone worldbook）模型。

字段与默认值取自 ST 1.19.0 的 `newWorldInfoEntryDefinition`（42 项），
见 docs/FORMAT_COMPATIBILITY.md §5。

文件结构：`{ "entries": { "<uid 字符串>": {...} } }` —— `entries` 是**对象**，
且服务端强制要求该键存在（`File must contain a world info entries list`）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .position import DEFAULT_DEPTH, DEFAULT_ORDER, DEFAULT_WEIGHT, PromptRole, SelectiveLogic, WiPosition


class WiEntry(BaseModel):
    """独立世界书条目。默认值 = ST 模板默认值，不是猜测。"""

    model_config = ConfigDict(extra="allow")

    uid: int
    key: list[str] = Field(default_factory=list)
    keysecondary: list[str] = Field(default_factory=list)
    comment: str = ""
    content: str = ""
    constant: bool = False
    vectorized: bool = False
    # 注意：ST 模板里 selective 默认是 true（内嵌形态的 convertCharacterBook 却是 false）。
    # 跨格式搬运必须显式写值，所以这里保留 ST 侧默认。
    selective: bool = True
    selectiveLogic: SelectiveLogic = SelectiveLogic.AND_ANY
    addMemo: bool = False
    order: int = DEFAULT_ORDER
    position: WiPosition = WiPosition.before
    disable: bool = False
    ignoreBudget: bool = False
    excludeRecursion: bool = False
    preventRecursion: bool = False
    delayUntilRecursion: int = 0
    probability: int = 100
    useProbability: bool = True
    depth: int = DEFAULT_DEPTH
    outletName: str = ""
    group: str = ""
    groupOverride: bool = False
    groupWeight: int = DEFAULT_WEIGHT
    scanDepth: int | None = None
    caseSensitive: bool | None = None
    matchWholeWords: bool | None = None
    useGroupScoring: bool | None = None
    automationId: str = ""
    role: PromptRole = PromptRole.system
    sticky: int | None = None
    cooldown: int | None = None
    delay: int | None = None
    triggers: list[str] = Field(default_factory=list)


class WorldbookFile(BaseModel):
    """独立世界书文件。

    只输出 `entries`。ST 的世界书文件名即书名，文件内不存 `name`；
    在未能实证之前不添加任何额外顶层键。
    """

    model_config = ConfigDict(extra="allow")

    entries: dict[str, WiEntry] = Field(default_factory=dict)


def entries_from_list(items: list[WiEntry]) -> dict[str, WiEntry]:
    """按 uid 转成 ST 要求的「字符串键对象」。uid 重复时抛错。"""
    result: dict[str, WiEntry] = {}
    for entry in items:
        key = str(entry.uid)
        if key in result:
            raise ValueError(f"uid 重复：{entry.uid}")
        result[key] = entry
    return result


def make_entry(**kwargs: Any) -> WiEntry:
    """便于测试与后续阶段构造条目的薄封装。"""
    return WiEntry(**kwargs)
