"""章节标题检测与章节切分。

原文里同一章标题常常出现两次（站点导航栏 + 正文标题），中间还夹着分隔线和
「未知」这类站点残留。本模块把它们显式建模成 `site_noise` 区段，而不是悄悄删掉 ——
原文必须能被无损重组。

检测不确定时用 fallback 切分，并把 strategy 记进 manifest，不假装识别准确。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

#: 默认章节标题：第N章 / 第N节 / 第N回，中文或阿拉伯数字均可。
DEFAULT_HEADING_PATTERN = r"^第\s*([0-9零一二三四五六七八九十百千〇两]+)\s*([章节回])\s*(.*)$"

#: 判定为「同一标题的重复出现」时允许的最大行距。
DEFAULT_DUPLICATE_GAP_LINES = 8

#: 标题数少于该值时认为识别失败，转 fallback。
MIN_HEADINGS = 2

RegionKind = Literal["front_matter", "site_noise", "chapter"]


class Heading(BaseModel):
    line_index: int
    raw: str
    number: str
    level: str
    title: str


class Region(BaseModel):
    """原文的一段连续行。所有 region 按 start_line 排序后必须**无缝铺满**整个文件。"""

    region_id: str
    source_id: str
    kind: RegionKind
    chapter_id: str | None = None
    start_line: int
    end_line: int


class ChapterRecord(BaseModel):
    chapter_id: str
    source_id: str
    index: int = Field(description="全书章节序号，0 起")
    number: str
    level: str
    title: str
    region_id: str
    start_line: int
    end_line: int
    char_count: int
    duplicate_heading_lines: list[int] = Field(default_factory=list)

    @property
    def display_title(self) -> str:
        return f"第{self.number}{self.level} {self.title}".strip()


class DetectionInfo(BaseModel):
    #: `manual` 与 `regex` 必须分得开：前者是用户给定规则、匹配失败会报错，
    #: 后者是工具自己猜的规则。早先两者都写成 `regex`，报告里看不出用的是哪种。
    strategy: Literal["regex", "manual", "fallback"]
    pattern: str
    headings_found: int
    headings_merged: int
    duplicate_headings_removed: int
    notes: list[str] = Field(default_factory=list)


class ChapterIndex(BaseModel):
    detection: DetectionInfo
    regions: list[Region]
    chapters: list[ChapterRecord]


def find_headings(lines: list[str], pattern: str = DEFAULT_HEADING_PATTERN) -> list[Heading]:
    """按行首正则找出所有标题行。只匹配行首，避免把正文里的「第3章」误判为标题。

    自定义正则的约定：有 3 个捕获组时按 `(编号, 级别, 标题)` 解释；
    只有 1 个捕获组时，把 group(1) 当作标题，编号按出现顺序生成。
    """
    compiled = re.compile(pattern)
    groups = compiled.groups
    found: list[Heading] = []
    for index, line in enumerate(lines):
        match = compiled.match(line.strip())
        if not match:
            continue
        if groups >= 3:
            number, level, title = match.group(1), match.group(2), (match.group(3) or "")
        elif groups == 2:
            number, level, title = match.group(1), "", (match.group(2) or "")
        elif groups == 1:
            number, level, title = str(len(found) + 1), "", (match.group(1) or "")
        else:
            number, level, title = str(len(found) + 1), "", match.group(0)
        found.append(
            Heading(
                line_index=index,
                raw=line.strip(),
                number=number,
                level=level,
                title=title.strip(),
            )
        )
    return found


def merge_duplicate_headings(
    headings: list[Heading],
    *,
    max_gap: int = DEFAULT_DUPLICATE_GAP_LINES,
) -> tuple[list[Heading], list[Heading], dict[int, list[int]]]:
    """把「同一标题在很近的距离内出现两次」折叠成一次。

    保留**后面**那一次作为正文起点（前面那次属于站点导航）。

    返回 `(保留的标题, 被折叠掉的标题, {保留标题行号: [被折叠的重复标题行号]})`。
    重复标题在**行位置上**落在两章之间，但**归属上**属于它重复的那一章 ——
    地图让调用方能同时正确处理这两件事。
    """
    kept: list[Heading] = []
    dropped: list[Heading] = []
    duplicate_map: dict[int, list[int]] = {}
    for heading in headings:
        previous = kept[-1] if kept else None
        if (
            previous is not None
            and heading.raw == previous.raw
            and 0 < heading.line_index - previous.line_index <= max_gap
        ):
            kept.pop()
            dropped.append(previous)
            duplicate_map.setdefault(heading.line_index, []).insert(0, previous.line_index)
            kept.append(heading)
            continue
        kept.append(heading)
    return kept, dropped, duplicate_map


def _build_regions_from_headings(
    lines: list[str],
    headings: list[Heading],
    dropped: list[Heading],
    duplicate_map: dict[int, list[int]],
    *,
    source_id: str,
) -> ChapterIndex:
    """按保留的标题铺满整个文件，把重复标题等残留划成 `site_noise`。"""
    total = len(lines)
    dropped_lines = {h.line_index for h in dropped}
    regions: list[Region] = []
    chapters: list[ChapterRecord] = []

    def push(kind: RegionKind, start: int, end: int, chapter_id: str | None = None) -> str | None:
        if end <= start:
            return None
        region_id = f"{source_id}_r{len(regions):04d}"
        regions.append(
            Region(
                region_id=region_id,
                source_id=source_id,
                kind=kind,
                chapter_id=chapter_id,
                start_line=start,
                end_line=end,
            )
        )
        return region_id

    def emit_run(start: int, end: int, default_kind: RegionKind) -> None:
        """铺满 [start, end)。被折叠掉的重复标题行单独标成 site_noise，其余按 default_kind。"""
        pos = start
        while pos < end:
            kind: RegionKind = "site_noise" if pos in dropped_lines else default_kind
            run_end = pos + 1
            while run_end < end and ((run_end in dropped_lines) == (kind == "site_noise")):
                run_end += 1
            push(kind, pos, run_end)
            pos = run_end

    first_heading_line = headings[0].line_index if headings else total
    if first_heading_line > 0:
        emit_run(0, first_heading_line, "front_matter")

    fallback_region_id = f"{source_id}_c0000"
    for order, heading in enumerate(headings):
        next_heading = headings[order + 1] if order + 1 < len(headings) else None
        next_start = next_heading.line_index if next_heading else total
        chapter_id = f"{source_id}_ch{order + 1:04d}"

        # 下一章的导航重复标题在行位置上落在本章尾巴里，必须切出去，
        # 否则本章正文会被上一本书的标题污染。
        trailing_noise = [
            line
            for line in (duplicate_map.get(next_heading.line_index, []) if next_heading else [])
            if heading.line_index < line < next_start
        ]
        body_end = min(trailing_noise) if trailing_noise else next_start

        rid = push("chapter", heading.line_index, body_end, chapter_id)
        char_count = sum(len(lines[i]) for i in range(heading.line_index, body_end))
        chapters.append(
            ChapterRecord(
                chapter_id=chapter_id,
                source_id=source_id,
                index=order,
                number=heading.number,
                level=heading.level,
                title=heading.title,
                region_id=rid or fallback_region_id,
                start_line=heading.line_index,
                end_line=body_end,
                char_count=char_count,
                duplicate_heading_lines=sorted(duplicate_map.get(heading.line_index, [])),
            )
        )
        if body_end < next_start:
            emit_run(body_end, next_start, "site_noise")

    return ChapterIndex(
        detection=DetectionInfo(
            strategy="regex",
            pattern=DEFAULT_HEADING_PATTERN,
            headings_found=len(headings) + len(dropped),
            headings_merged=len(headings),
            duplicate_headings_removed=len(dropped),
        ),
        regions=regions,
        chapters=chapters,
    )


def _fallback_chapters(
    lines: list[str],
    *,
    source_id: str,
    target_chars: int,
    reason: str,
) -> ChapterIndex:
    """识别不到章节时的明确退路：按字符预算在行边界切分。"""
    total = len(lines)
    regions: list[Region] = []
    chapters: list[ChapterRecord] = []

    start = 0
    order = 0
    while start < total:
        end = start
        chars = 0
        while end < total and (chars < target_chars or end == start):
            chars += len(lines[end])
            end += 1
        chapter_id = f"{source_id}_ch{order + 1:04d}"
        region_id = f"{source_id}_c{order:04d}"
        regions.append(
            Region(
                region_id=region_id,
                source_id=source_id,
                kind="chapter",
                chapter_id=chapter_id,
                start_line=start,
                end_line=end,
            )
        )
        chapters.append(
            ChapterRecord(
                chapter_id=chapter_id,
                source_id=source_id,
                index=order,
                number=str(order + 1),
                level="段",
                title="自动分段",
                region_id=region_id,
                start_line=start,
                end_line=end,
                char_count=chars,
            )
        )
        start = end
        order += 1

    return ChapterIndex(
        detection=DetectionInfo(
            strategy="fallback",
            pattern=DEFAULT_HEADING_PATTERN,
            headings_found=0,
            headings_merged=0,
            duplicate_headings_removed=0,
            notes=[reason, f"按 {target_chars} 字符预算在行边界自动分段。"],
        ),
        regions=regions,
        chapters=chapters,
    )


def build_chapter_index(
    lines: list[str],
    *,
    source_id: str,
    pattern: str = DEFAULT_HEADING_PATTERN,
    strategy: Literal["auto", "regex", "manual"] = "auto",
    target_chars: int = 10000,
    duplicate_gap: int = DEFAULT_DUPLICATE_GAP_LINES,
) -> ChapterIndex:
    """构建章节索引。

    `auto`：先按默认正则检测，标题数不足时退回 fallback。
    `regex`/`manual`：用户提供了规则，必须匹配成功，否则报错而不是静默降级。
    """
    headings = find_headings(lines, pattern)
    merged, dropped, duplicate_map = merge_duplicate_headings(headings, max_gap=duplicate_gap)

    if len(merged) >= MIN_HEADINGS:
        index = _build_regions_from_headings(
            lines, merged, dropped, duplicate_map, source_id=source_id
        )
        index.detection.pattern = pattern
        # 如实记录用的是哪条路：manual 是用户给的规则，regex 是工具自己找的。
        index.detection.strategy = "manual" if strategy == "manual" else "regex"
        return index

    if strategy in ("regex", "manual"):
        raise ValueError(
            f"按给定规则只找到 {len(merged)} 个章节标题，不足以切分。"
            f"请检查 chapter_heading_regex，或改用 chapter_detection: auto。"
        )

    reason = (
        f"默认规则只找到 {len(merged)} 个章节标题"
        f"（阈值 {MIN_HEADINGS}），已改用按字符预算的自动分段；"
        "如需精确章节，请在配置里提供 chapter_heading_regex。"
    )
    return _fallback_chapters(lines, source_id=source_id, target_chars=target_chars, reason=reason)


def rebuild_text(lines: list[str], regions: list[Region]) -> str:
    """按 region 无损重组原文。用于校验切分没有丢行或重复行。"""
    ordered = sorted(regions, key=lambda r: r.start_line)
    return "".join("".join(lines[r.start_line : r.end_line]) for r in ordered)
