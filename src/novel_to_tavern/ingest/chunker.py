"""章节内分块。

约束：
- **不跨章节**：每个 chunk 完整落在单个章节的行范围内。
- **无损**：chunk 是行对齐的，按序拼接可还原该章节的全部文本。
- chunk 只在 manifest 里记录位置与 hash，**不写原文**，避免原文进入产物。
"""

from __future__ import annotations

from pydantic import BaseModel

from .chapters import ChapterRecord
from .source import sha256_of


class ChunkRecord(BaseModel):
    chunk_id: str
    chapter_id: str
    source_id: str
    index: int
    ordinal_in_chapter: int
    start_line: int
    end_line: int
    start_char: int
    end_char: int
    char_count: int
    sha256: str


class ChunkPlan(BaseModel):
    chunks: list[ChunkRecord]
    oversized_lines: list[int] = []


def chunk_chapter(
    lines: list[str],
    offsets: list[int],
    chapter: ChapterRecord,
    *,
    target_chars: int,
    max_chars: int,
    start_index: int = 0,
) -> ChunkPlan:
    """把一个章节按字符预算切成行对齐的块。

    单行超过 `max_chars` 时不切开（切开就无法行对齐无损重组），
    该行独占一块并把行号记进 `oversized_lines`，由调用方在报告里提醒。
    """
    chunks: list[ChunkRecord] = []
    oversized: list[int] = []

    cursor = chapter.start_line
    ordinal = 0
    while cursor < chapter.end_line:
        end = cursor
        chars = 0
        while end < chapter.end_line:
            line_len = len(lines[end])
            # 首行无论多长都必须收下，否则无法行对齐无损重组。
            if end > cursor and chars + line_len > max_chars:
                break
            chars += line_len
            end += 1
            if chars >= target_chars:
                break

        if end - cursor == 1 and len(lines[cursor]) > max_chars:
            oversized.append(cursor)

        text = "".join(lines[cursor:end])
        chunks.append(
            ChunkRecord(
                chunk_id=f"{chapter.chapter_id}_p{ordinal:03d}",
                chapter_id=chapter.chapter_id,
                source_id=chapter.source_id,
                index=start_index + len(chunks),
                ordinal_in_chapter=ordinal,
                start_line=cursor,
                end_line=end,
                start_char=offsets[cursor],
                end_char=offsets[end],
                char_count=len(text),
                sha256=sha256_of(text),
            )
        )
        cursor = end
        ordinal += 1

    return ChunkPlan(chunks=chunks, oversized_lines=oversized)


def rebuild_chapter(lines: list[str], chapter: ChapterRecord, chunks: list[ChunkRecord]) -> str:
    """按 chunk 拼接还原章节文本。用于无损性断言。"""
    ordered = sorted(
        (c for c in chunks if c.chapter_id == chapter.chapter_id),
        key=lambda c: c.start_line,
    )
    return "".join("".join(lines[c.start_line : c.end_line]) for c in ordered)
