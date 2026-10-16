"""SillyTavern Character Card V2 与内嵌 character_book 的模型。

字段集来自 ST 1.19.0 源码核对，见 docs/FORMAT_COMPATIBILITY.md §2–§4。
本模块只描述**格式**，不含任何小说内容或抽取逻辑。

解析策略：`extra="allow"` —— V2 规范要求"已存在的可选字段不得被破坏"。
把未知字段挡在外面是 `validator.validate_card(strict=True)` 的职责，
而不是在解析阶段静默丢弃他人卡里的数据。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .position import CharBookPosition, coerce_char_book_position

SPEC_NAME: Literal["chara_card_v2"] = "chara_card_v2"
SPEC_VERSION: Literal["2.0"] = "2.0"


class CharacterBookEntry(BaseModel):
    """内嵌 character_book 的一个条目（数组元素，不是对象成员）。"""

    model_config = ConfigDict(extra="allow")

    # --- 必填：不写就是错的，所以不给默认值 ---
    id: int = Field(description="唯一整数 id；ST 用它作 uid，缺失时回退数组下标")
    keys: list[str] = Field(description="主触发词")
    content: str = Field(description="条目正文")
    enabled: bool = Field(description="缺省会被 ST 判为 disabled，故必填")
    insertion_order: int
    position: CharBookPosition

    # --- 本项目固定输出 ---
    comment: str = Field(default="", description="条目标题/备注；name 不被 ST 读取")
    extensions: dict[str, Any] = Field(default_factory=dict)

    # --- 可选 ---
    secondary_keys: list[str] | None = None
    selective: bool | None = None
    constant: bool | None = None

    @field_validator("position", mode="before")
    @classmethod
    def _check_position(cls, value: object) -> CharBookPosition:
        return coerce_char_book_position(value)


class CharacterBook(BaseModel):
    """内嵌 `data.character_book`。"""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    description: str = ""
    scan_depth: int | None = None
    token_budget: int | None = None
    recursive_scanning: bool | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)
    entries: list[CharacterBookEntry] = Field(default_factory=list)


class CharData(BaseModel):
    """`data` 字段。只列本项目会输出的键；多出来的键在解析时保留。"""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    tags: list[str] = Field(default_factory=list)
    creator: str = ""
    character_version: str = ""
    alternate_greetings: list[str] = Field(default_factory=list)
    character_book: CharacterBook | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class CardV2(BaseModel):
    """完整角色卡。`spec` / `spec_version` 是字面量，写错直接构造失败。"""

    model_config = ConfigDict(extra="allow")

    spec: Literal["chara_card_v2"] = SPEC_NAME
    spec_version: Literal["2.0"] = SPEC_VERSION
    data: CharData
