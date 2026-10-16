"""导出前后的结构校验与质量门禁检查。

只做**结构与一致性**检查，不判断小说内容是否正确（那属于 Phase 6 人工审校）。
错误=产物不可用；警告=可能无效或值得人工看一眼。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import secrets
from .spec_v2 import CardV2, CharacterBook, CharacterBookEntry
from .wi_standalone import WiEntry, WorldbookFile

#: V2 规范里确实存在的条目字段。出现集合之外的键通常是写错名字（如把 id 写成 uid）。
KNOWN_V2_ENTRY_FIELDS = frozenset(
    {
        "id",
        "keys",
        "content",
        "enabled",
        "insertion_order",
        "position",
        "comment",
        "extensions",
        "name",
        "priority",
        "case_sensitive",
        "selective",
        "secondary_keys",
        "constant",
    }
)

KNOWN_V2_DATA_FIELDS = frozenset(
    {
        "name",
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "tags",
        "creator",
        "character_version",
        "alternate_greetings",
        "character_book",
        "extensions",
    }
)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "ValidationReport") -> "ValidationReport":
        return ValidationReport(self.errors + other.errors, self.warnings + other.warnings)

    def lines(self) -> list[str]:
        return [f"ERROR {m}" for m in self.errors] + [f"WARN  {m}" for m in self.warnings]


def _unknown_fields(model, known: frozenset[str]) -> list[str]:
    return sorted(set(model.model_extra or {}) - known)


def validate_entry(entry: CharacterBookEntry, index: int, report: ValidationReport, *, strict: bool) -> None:
    where = f"条目[{index}] id={entry.id}"

    if not entry.keys and not entry.constant:
        report.warn(f"{where}：keys 为空且非常驻，永远不会被触发。")
    if not entry.content.strip():
        report.warn(f"{where}：content 为空。")
    if not entry.comment.strip():
        report.warn(f"{where}：comment 为空，客户端里不会有可读的条目标题。")
    if entry.secondary_keys and not entry.selective:
        report.warn(f"{where}：写了 secondary_keys 但 selective 不为真，secondary 不会生效。")

    unknown = _unknown_fields(entry, KNOWN_V2_ENTRY_FIELDS)
    for name in unknown:
        message = f"{where}：字段 {name!r} 不属于 V2 规范（多半是写错了字段名）。"
        report.error(message) if strict else report.warn(message)


def validate_character_book(book: CharacterBook, report: ValidationReport, *, strict: bool) -> None:
    seen_ids: set[int] = set()
    key_owners: dict[str, int] = {}

    for index, entry in enumerate(book.entries):
        if entry.id in seen_ids:
            report.error(f"条目 id 重复：{entry.id}（ST 要求唯一）")
        seen_ids.add(entry.id)
        for key in entry.keys:
            key_owners.setdefault(key, 0)
            key_owners[key] += 1
        validate_entry(entry, index, report, strict=strict)

    if not book.entries:
        report.warn("character_book 没有任何条目。")
    for key, count in sorted(key_owners.items()):
        if count > 1:
            report.warn(f"触发词 {key!r} 同时出现在 {count} 个条目上，会一起命中。")


def validate_card(card: CardV2, *, strict: bool = False, max_always_on: int | None = None) -> ValidationReport:
    """校验一张 V2 卡。`strict=True` 时未知字段也按错误处理。"""
    report = ValidationReport()

    if card.spec != "chara_card_v2":
        report.error(f"spec 必须是 'chara_card_v2'，实际 {card.spec!r}")
    if card.spec_version != "2.0":
        report.error(f"spec_version 必须是字符串 '2.0'，实际 {card.spec_version!r}")
    if not card.data.name.strip():
        report.error("data.name 为空。")

    for name in _unknown_fields(card.data, KNOWN_V2_DATA_FIELDS):
        message = f"data 字段 {name!r} 不属于 V2 规范。"
        report.error(message) if strict else report.warn(message)

    if card.data.character_book is None:
        report.warn("卡里没有 character_book，世界书需单独导入。")
        return report

    validate_character_book(card.data.character_book, report, strict=strict)

    always_on = [e for e in card.data.character_book.entries if e.constant]
    if max_always_on is not None and len(always_on) > max_always_on:
        report.warn(
            f"常驻条目 {len(always_on)} 条，超过配置上限 {max_always_on} 条；"
            "常驻内容会占用每一轮的上下文预算。"
        )

    disabled = [e.id for e in card.data.character_book.entries if not e.enabled]
    if disabled:
        report.warn(f"以下条目 enabled=false，客户端里不会触发：{disabled}")

    return report


def validate_worldbook(worldbook: WorldbookFile, *, strict: bool = False) -> ValidationReport:
    """校验独立世界书。重点是 `entries` 的键与 uid 必须一致。"""
    report = ValidationReport()

    if not worldbook.entries:
        report.error("standalone worldbook 的 entries 为空；服务端要求该键存在且有内容。")

    seen_uids: set[int] = set()
    for key, entry in worldbook.entries.items():
        where = f"entries[{key!r}]"
        if not key.isdigit():
            report.error(f"{where}：键必须是 uid 的十进制字符串。")
        if key != str(entry.uid):
            report.error(f"{where}：键与 uid 不一致（uid={entry.uid}）。")
        if entry.uid in seen_uids:
            report.error(f"uid 重复：{entry.uid}")
        seen_uids.add(entry.uid)

        if not entry.key and not entry.constant:
            report.warn(f"{where}：key 为空且非常驻，永远不会被触发。")
        if not entry.content.strip():
            report.warn(f"{where}：content 为空。")
        if entry.disable:
            report.warn(f"{where}：disable=true，该条目不生效。")
        if entry.addMemo and not entry.comment.strip():
            report.warn(f"{where}：addMemo 为真但 comment 为空。")

        unknown = _unknown_fields(entry, frozenset(WiEntry.model_fields))
        for name in unknown:
            message = f"{where}：字段 {name!r} 不属于独立世界书条目结构。"
            report.error(message) if strict else report.warn(message)

    return report


def validate_parity(card: CardV2, worldbook: WorldbookFile) -> ValidationReport:
    """内嵌与独立世界书必须语义一致（质量门禁 E）。"""
    report = ValidationReport()
    book = card.data.character_book
    if book is None:
        report.error("卡里没有 character_book，无法比对。")
        return report

    if len(book.entries) != len(worldbook.entries):
        report.error(f"条目数不一致：内嵌 {len(book.entries)} 条，独立 {len(worldbook.entries)} 条。")
        return report

    for index, embedded in enumerate(book.entries):
        standalone = worldbook.entries.get(str(index))
        if standalone is None:
            report.error(f"独立世界书缺少 uid={index} 的条目。")
            continue
        where = f"条目[{index}]"
        if embedded.content != standalone.content:
            report.error(f"{where}：content 不一致。")
        if list(embedded.keys) != list(standalone.key):
            report.error(f"{where}：keys/key 不一致。")
        if list(embedded.secondary_keys or []) != list(standalone.keysecondary):
            report.error(f"{where}：secondary_keys/keysecondary 不一致。")
        if embedded.enabled == standalone.disable:
            report.error(f"{where}：enabled 与 disable 极性未正确对应。")
        if embedded.insertion_order != standalone.order:
            report.error(f"{where}：insertion_order 与 order 不一致。")
        if embedded.comment != standalone.comment:
            report.error(f"{where}：comment 不一致。")
        if bool(embedded.constant) != standalone.constant:
            report.error(f"{where}：constant 不一致。")

    return report


def validate_no_secrets(text: str) -> ValidationReport:
    """导出物中不得出现任何已登记密钥或形如密钥的串。"""
    report = ValidationReport()
    for secret in secrets._registered:  # noqa: SLF001 — 同包内共用登记表
        if secret in text:
            report.error("导出内容中检出已登记的 API 密钥。")
            break
    else:
        if secrets.redact(text) != text:
            report.error("导出内容中检出疑似 API 密钥。")
    return report
