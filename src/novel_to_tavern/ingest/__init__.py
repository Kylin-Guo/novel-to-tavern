"""导入与章节索引（Phase 1）。

原文只读；章节与分块的无损性由 `pipeline._validate_and_report` 强制校验。
"""

from __future__ import annotations

from .chapters import (
    DEFAULT_HEADING_PATTERN,
    ChapterIndex,
    ChapterRecord,
    DetectionInfo,
    Heading,
    Region,
    build_chapter_index,
    find_headings,
    merge_duplicate_headings,
    rebuild_text,
)
from .chunker import ChunkPlan, ChunkRecord, chunk_chapter, rebuild_chapter
from .manifest import MANIFEST_SCHEMA_VERSION, Manifest, RunState, SourceRecord, SourceStats
from .pipeline import IngestError, discover_sources, ingest
from .source import SourceReadError, SourceText, line_offsets, read_source, sha256_of

__all__ = [
    "DEFAULT_HEADING_PATTERN",
    "MANIFEST_SCHEMA_VERSION",
    "ChapterIndex",
    "ChapterRecord",
    "ChunkPlan",
    "ChunkRecord",
    "DetectionInfo",
    "Heading",
    "IngestError",
    "Manifest",
    "Region",
    "RunState",
    "SourceReadError",
    "SourceRecord",
    "SourceStats",
    "SourceText",
    "build_chapter_index",
    "chunk_chapter",
    "discover_sources",
    "find_headings",
    "ingest",
    "line_offsets",
    "merge_duplicate_headings",
    "read_source",
    "rebuild_chapter",
    "rebuild_text",
    "sha256_of",
]
