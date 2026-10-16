"""内部世界书条目 → 目标 JSON 的唯一映射点。

设计约束（AGENTS.md）：
- 最终 JSON 一律由代码序列化，不允许 LLM 手写。
- 内部 schema 字段**不得**原样塞进最终文件；只写目标格式确有依据的字段。

两种目标形态的字段名、类型与极性都不同，映射集中在本模块，别处不得再写一遍。
见 docs/FORMAT_COMPATIBILITY.md §5.3 与 §6。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import secrets
from .position import (
    DEFAULT_ORDER,
    CharBookPosition,
    char_book_to_wi_position,
    coerce_char_book_position,
)
from .spec_v2 import CardV2, CharData, CharacterBook, CharacterBookEntry
from .wi_standalone import WiEntry, WorldbookFile, entries_from_list

#: 内嵌 character_book → 独立世界书 的字段名对照。
#: 极性相反或类型不同的项在注释里标出，改动前先看 FORMAT_COMPATIBILITY.md。
FIELD_MAP_EMBEDDED_TO_STANDALONE: dict[str, str] = {
    "id": "uid",
    "keys": "key",
    "secondary_keys": "keysecondary",
    "insertion_order": "order",
    "enabled": "disable",  # 极性相反：disable = not enabled
    "position": "position",  # 类型不同：字符串 ↔ 数字 0–7
    "comment": "comment",
    "content": "content",
    "constant": "constant",
    "selective": "selective",
}

#: 目标格式中**不存在**、因此本项目不输出的内嵌字段。
EMBEDDED_FIELDS_NOT_EMITTED: tuple[str, ...] = ("name", "priority", "case_sensitive", "use_regex")

DEFAULT_SCAN_DEPTH = 4
DEFAULT_TOKEN_BUDGET = 900


@dataclass(frozen=True, slots=True)
class EntryDraft:
    """内部条目草稿。字段是项目自有语义，不等于目标格式字段。"""

    entry_id: str
    title: str
    content: str
    keys: tuple[str, ...] = ()
    secondary_keys: tuple[str, ...] = ()
    always_on: bool = False
    enabled: bool = True
    insertion_order: int = DEFAULT_ORDER
    position: CharBookPosition = CharBookPosition.after_char
    entities: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default=())

    def resolved_comment(self) -> str:
        """memo 标题。空标题退回 entry_id —— 没有 comment 就没有 memo。"""
        return self.title or self.entry_id


def to_embedded_entry(draft: EntryDraft, index: int) -> CharacterBookEntry:
    """内部草稿 → 内嵌条目。

    `id` 由调用顺序决定（0 起）。ST 读 `id` 不读 `uid`；顺序变化会改变 id，
    所以草稿的先后必须稳定。
    """
    return CharacterBookEntry(
        id=index,
        keys=list(draft.keys),
        content=draft.content,
        enabled=draft.enabled,
        insertion_order=draft.insertion_order,
        position=coerce_char_book_position(draft.position),
        comment=draft.resolved_comment(),
        extensions={},
        secondary_keys=list(draft.secondary_keys) if draft.secondary_keys else None,
        selective=True if draft.secondary_keys else None,
        constant=True if draft.always_on else None,
    )


def to_standalone_entry(draft: EntryDraft, index: int) -> WiEntry:
    """内部草稿 → 独立世界书条目。

    各字段显式赋值，**不依赖 ST 模板默认值** —— 因为 `selective` 等默认值
    在两种形态之间并不一致。
    """
    comment = draft.resolved_comment()
    return WiEntry(
        uid=index,
        key=list(draft.keys),
        keysecondary=list(draft.secondary_keys),
        comment=comment,
        content=draft.content,
        constant=draft.always_on,
        selective=bool(draft.secondary_keys),
        addMemo=bool(comment),
        order=draft.insertion_order,
        position=char_book_to_wi_position(coerce_char_book_position(draft.position)),
        disable=not draft.enabled,
        triggers=list(draft.tags),
    )


def build_character_book(
    drafts: list[EntryDraft],
    *,
    name: str,
    description: str = "",
    scan_depth: int = DEFAULT_SCAN_DEPTH,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    recursive_scanning: bool = True,
) -> CharacterBook:
    return CharacterBook(
        name=name,
        description=description,
        scan_depth=scan_depth,
        token_budget=token_budget,
        recursive_scanning=recursive_scanning,
        extensions={},
        entries=[to_embedded_entry(draft, i) for i, draft in enumerate(drafts)],
    )


def build_standalone_worldbook(drafts: list[EntryDraft]) -> WorldbookFile:
    items = [to_standalone_entry(draft, i) for i, draft in enumerate(drafts)]
    return WorldbookFile(entries=entries_from_list(items))


def build_card_v2(
    *,
    name: str,
    description: str,
    drafts: list[EntryDraft],
    personality: str = "",
    scenario: str = "",
    first_mes: str = "",
    mes_example: str = "",
    creator_notes: str = "",
    system_prompt: str = "",
    post_history_instructions: str = "",
    tags: list[str] | None = None,
    creator: str = "",
    character_version: str = "0.1.0",
    alternate_greetings: list[str] | None = None,
    book_name: str | None = None,
    book_description: str = "",
    scan_depth: int = DEFAULT_SCAN_DEPTH,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    recursive_scanning: bool = True,
) -> CardV2:
    """组装完整 V2 卡（含内嵌 character_book）。"""
    book = build_character_book(
        drafts,
        name=book_name or f"{name} · 世界书",
        description=book_description,
        scan_depth=scan_depth,
        token_budget=token_budget,
        recursive_scanning=recursive_scanning,
    )
    return CardV2(
        spec="chara_card_v2",
        spec_version="2.0",
        data=CharData(
            name=name,
            description=description,
            personality=personality,
            scenario=scenario,
            first_mes=first_mes,
            mes_example=mes_example,
            creator_notes=creator_notes,
            system_prompt=system_prompt,
            post_history_instructions=post_history_instructions,
            tags=list(tags or []),
            creator=creator,
            character_version=character_version,
            alternate_greetings=list(alternate_greetings or []),
            character_book=book,
            extensions={},
        ),
    )


def to_plain(model: Any, *, exclude_none: bool = True) -> Any:
    """转为可 JSON 序列化的普通结构，枚举落成原始值。

    `exclude_none` 默认开启：内嵌 character_book 的可选字段未设置时**直接省略**，
    而不是写成 `null`（V2 规范里它们是 optional）。
    """
    return model.model_dump(mode="json", exclude_none=exclude_none)


def dumps(
    model: Any,
    *,
    indent: int = 2,
    exclude_none: bool = True,
    assert_no_secrets: bool = True,
) -> str:
    """序列化为严格合法 JSON。

    `assert_no_secrets` 会在写出前扫描已登记的密钥，命中即抛错 ——
    宁可导出失败，也不把凭据写进角色卡。
    """
    text = json.dumps(to_plain(model, exclude_none=exclude_none), ensure_ascii=False, indent=indent)
    if assert_no_secrets:
        for secret in secrets._registered:  # noqa: SLF001 — 同包内共用登记表
            if secret in text:
                raise ValueError("导出内容中检出已登记的 API 密钥，已中止写出。")
    return text


def dump_to(path: str | Path, model: Any, *, indent: int = 2, exclude_none: bool = True) -> Path:
    """写文件（UTF-8、末尾换行）。调用方负责选择未被占用的 run 目录。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        dumps(model, indent=indent, exclude_none=exclude_none) + "\n",
        encoding="utf-8",
    )
    return target
