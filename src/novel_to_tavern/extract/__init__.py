"""分块原子事实抽取（Phase 2）。

模型只负责给内容与引文；行号、来源引用与 canon 资格由代码判定。
"""

from __future__ import annotations

from .evidence import (
    MAX_QUOTE_CHARS,
    MIN_QUOTE_CHARS,
    EvidenceStats,
    QuoteCheck,
    locate_quote,
    normalize_for_match,
)
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .runner import (
    EXTRACTION_DIR,
    INDEX_NAME,
    ExtractionError,
    ExtractionRunner,
    ExtractionRunResult,
    cache_key,
    parse_json_response,
    run_extraction,
)
from .schema import (
    CANON,
    ChunkExtraction,
    EntityKind,
    EventRecord,
    FactRecord,
    FactType,
    MentionRecord,
    RawChunkExtraction,
    RelationRecord,
    ReviewStatus,
    SourceRef,
)

__all__ = [
    "CANON",
    "EXTRACTION_DIR",
    "INDEX_NAME",
    "MAX_QUOTE_CHARS",
    "MIN_QUOTE_CHARS",
    "QuoteCheck",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "ChunkExtraction",
    "EntityKind",
    "EventRecord",
    "EvidenceStats",
    "ExtractionError",
    "ExtractionRunResult",
    "ExtractionRunner",
    "FactRecord",
    "FactType",
    "MentionRecord",
    "RawChunkExtraction",
    "RelationRecord",
    "ReviewStatus",
    "SourceRef",
    "build_user_prompt",
    "cache_key",
    "locate_quote",
    "normalize_for_match",
    "parse_json_response",
    "run_extraction",
]
