"""run manifest：来源、章节索引、分块的版本化记录。

manifest 只存**位置与 hash**，不存原文 —— 原文可从 source path + 行范围重建，
而 manifest 要能被安全地阅读、比对和提交审阅。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .chapters import ChapterRecord, DetectionInfo, Region
from .chunker import ChunkRecord

MANIFEST_SCHEMA_VERSION = 1


class SourceRecord(BaseModel):
    source_id: str
    path: str
    filename: str
    sha256: str
    size_bytes: int
    encoding: str
    newline_style: str
    total_lines: int
    total_chars: int


class SourceStats(BaseModel):
    chapters: int = 0
    chunks: int = 0
    chars: int = 0
    oversized_lines: int = 0


class Manifest(BaseModel):
    schema_version: int = MANIFEST_SCHEMA_VERSION
    parser_version: str
    run_id: str
    created_at: str
    updated_at: str
    config_fingerprint: str
    sources: list[SourceRecord] = Field(default_factory=list)
    detections: dict[str, DetectionInfo] = Field(default_factory=dict)
    regions: list[Region] = Field(default_factory=list)
    chapters: list[ChapterRecord] = Field(default_factory=list)
    chunks: list[ChunkRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, SourceStats] = Field(default_factory=dict)

    def chapters_of(self, source_id: str) -> list[ChapterRecord]:
        return [c for c in self.chapters if c.source_id == source_id]

    def chunks_of(self, chapter_id: str) -> list[ChunkRecord]:
        return [c for c in self.chunks if c.chapter_id == chapter_id]

    def global_chapter_order(self) -> dict[str, int]:
        """章节的**全局**序号：按 manifest 里的来源顺序、来源内章节顺序编号。

        `ChapterRecord.index` 是**来源内**序号，多卷本的每一卷都从 0 开始，
        直接用它会撞号（三卷都从 ch0001 起）。跨卷做时间线、开场白、
        起始点屏蔽都必须用这个全局序号。
        """
        order: dict[str, int] = {}
        counter = 0
        for source in self.sources:
            for chapter in sorted(self.chapters_of(source.source_id), key=lambda c: c.index):
                order[chapter.chapter_id] = counter
                counter += 1
        return order

    def source_display_names(self) -> dict[str, str]:
        """来源的短显示名：文件名主干里书名号之前的部分。"""
        names: dict[str, str] = {}
        for source in self.sources:
            stem = Path(source.filename).stem
            names[source.source_id] = stem.split("：")[0].split(":")[0] or stem
        return names

    def region_coverage(self, source_id: str, total_lines: int) -> tuple[bool, list[str]]:
        """校验该来源的 region 是否无缝铺满 [0, total_lines)。"""
        problems: list[str] = []
        covered = sorted(
            (r.start_line, r.end_line) for r in self.regions if r.source_id == source_id
        )
        cursor = 0
        for start, end in covered:
            if start != cursor:
                problems.append(f"行 {cursor}–{start} 没有被任何区段覆盖（或出现重叠）。")
                cursor = max(cursor, end)
                continue
            cursor = end
        if cursor != total_lines:
            problems.append(f"区段只覆盖到第 {cursor} 行，文件共 {total_lines} 行。")
        return (not problems), problems


class RunState(BaseModel):
    """可续跑状态。中断后用同一 run 目录再跑，只补未完成的来源。"""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    run_id: str
    completed_sources: dict[str, str] = Field(
        default_factory=dict, description="source_id → 处理时的 sha256"
    )
    started_at: str = ""
    updated_at: str = ""


def stats_for_source(
    manifest: Manifest, source_id: str, *, oversized_lines: int = 0
) -> SourceStats:
    chapters = manifest.chapters_of(source_id)
    chunks = [c for c in manifest.chunks if c.source_id == source_id]
    return SourceStats(
        chapters=len(chapters),
        chunks=len(chunks),
        chars=sum(c.char_count for c in chunks),
        oversized_lines=oversized_lines,
    )


def to_jsonable(manifest: Manifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")
