#!/usr/bin/env python3
"""check_card.py — 独立校验导出的 Character Card V2 主卡，并打印汇报数字。

用法：
    python3 check_card.py runs/<run_id>/exports/world_simulator_v2.json

导出阶段已做过强制校验（有错不会写文件）；本脚本的价值是**独立复核**那些
「JSON 合法但客户端静默出错」的字段，并把汇报所需的数字（条目数、常驻数、
正文字数）一次算出来。只用标准库。

检查项（与仓库 tests/test_docs_consistency.py 的不变量一致）：
- spec == chara_card_v2 且 spec_version == "2.0"
- data.character_book.entries 非空
- 每条 entry：enabled 显式为 true；position 是字符串且在
  {before_char, after_char}；comment / content 非空
- 非常驻条目必须有非空 keys（否则永不触发）
- entry id 从 0 顺序编号
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_POSITIONS = {"before_char", "after_char"}


def check(path: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    stats: dict = {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"无法读取/解析 JSON：{exc}"], stats

    spec = payload.get("spec")
    if spec != "chara_card_v2":
        errors.append(f"spec 应为 chara_card_v2，实际 {spec!r}")
    if payload.get("spec_version") != "2.0":
        errors.append(f"spec_version 应为 '2.0'，实际 {payload.get('spec_version')!r}")

    data = payload.get("data") or {}
    stats["name"] = data.get("name") or payload.get("name") or "(未命名)"

    book = data.get("character_book") or {}
    entries = book.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("data.character_book.entries 为空或不是数组")
        return errors, stats

    constant = 0
    total_chars = 0
    for i, entry in enumerate(entries):
        label = entry.get("comment") or f"#{i}"
        if entry.get("enabled") is not True:
            errors.append(f"条目未显式启用（enabled!=true）：{label!r}")
        position = entry.get("position")
        if not isinstance(position, str):
            errors.append(
                f"position 不是字符串（写数字 0 会被静默当成 after_char）：{label!r}"
            )
        elif position not in ALLOWED_POSITIONS:
            errors.append(f"position 取值非法 {position!r}：{label!r}")
        if not (entry.get("comment") or "").strip():
            errors.append(f"条目标题（comment）为空：#{i}")
        content = (entry.get("content") or "").strip()
        if not content:
            errors.append(f"条目正文为空：{label!r}")
        if not entry.get("constant") and not entry.get("keys"):
            errors.append(f"非常驻条目没有触发键（永不触发）：{label!r}")
        if entry.get("constant"):
            constant += 1
        total_chars += len(entry.get("content") or "")

    ids = [e.get("id") for e in entries]
    if ids != list(range(len(entries))):
        errors.append("entry id 未从 0 顺序编号")

    stats["entries"] = len(entries)
    stats["constant"] = constant
    stats["triggered"] = len(entries) - constant
    stats["total_chars"] = total_chars
    return errors, stats


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    errors, stats = check(path)

    if stats:
        print(f"卡片名称：{stats.get('name')}")
    if "entries" in stats:
        print(f"条目总数：{stats['entries']}")
        print(f"常驻条目：{stats['constant']}　触发条目：{stats['triggered']}")
        print(f"正文总字数：{stats['total_chars']}")

    if errors:
        print(f"\n未通过（{len(errors)} 项）：")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("\n结构校验通过。注意：这只证明字段合法，不证明客户端里触发/常驻行为正确。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
