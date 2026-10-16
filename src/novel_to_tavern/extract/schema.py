"""原子事实抽取的 schema（Phase 2）。

分两层：
- `Raw*`：期望模型直接产出的形状。**模型只给引文，不给行号。**
- `*Record`：经证据定位后的结果，行号由代码填，带 `source_refs`。

canon 事实必须落到真实原文位置；定位失败的条目一律降级，不冒充原著事实。
详见 docs/DATA_MODEL.md §1–§4。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactType = Literal[
    "canon_fact",
    "character_belief",
    "rumor",
    "inference",
    "user_added",
    "reconstructed",
    "contradiction",
    "unknown",
]

EntityKind = Literal[
    "character", "place", "faction", "item", "ability", "concept", "event",
    #: 模型没给出类型时的落点。**不是**「其它」，是「还不知道」——
    #: 它不能冒充人物，也不会被合并进人物聚类。
    "unknown",
]

ReviewStatus = Literal["accepted", "needs_review", "rejected"]

#: 只有这一类事实可以被无条件写进 canon 总纲。
CANON = "canon_fact"

#: 模型漏字段时的落点。默认取它而不是 `CANON`：
#: 少写一个字段是常见的，而「默认当成原著正史」正好是本项目最不能犯的错 ——
#: 错误的默认值在 JSON 完全合法的情况下不会报任何错。见 docs/REVIEW_RECHECK.md P1-03。
UNKNOWN = "unknown"


class SourceRef(BaseModel):
    source_id: str
    chapter_id: str
    start_line: int
    end_line: int
    #: 命中处的**原文片段**（由代码从原文切出，保证逐字可查）。
    quote: str
    #: 模型给出的**原话**。与 `quote` 分开存：`quote` 是原文（可能含整行），
    #: 这里是模型实际写的那一串，用来核对「模型引的是不是它说的那句」。
    quote_exact: str = ""
    #: 这段引文在原文里出现了多次 → 定位不唯一，取的是最靠前的一处。
    ambiguous: bool = False
    match_count: int = 1


class _Raw(BaseModel):
    """模型输出的基类：容忍多余字段，但不写进最终结果。"""

    model_config = ConfigDict(extra="ignore")


class RawMention(_Raw):
    name: str
    aliases: list[str] = Field(default_factory=list)
    #: 缺省 `unknown` 而不是 `character`：默认成人物等于替模型做了一个它没说过的判断。
    kind: EntityKind = UNKNOWN
    quote: str = ""
    note: str = ""


class RawFact(_Raw):
    subject: str
    predicate: str
    value: str
    fact_type: FactType = UNKNOWN
    quote: str = ""


class RawEvent(_Raw):
    title: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    fact_type: FactType = UNKNOWN
    quote: str = ""


class RawRelation(_Raw):
    from_entity: str
    to_entity: str
    relation: str
    quote: str = ""


class RawChunkExtraction(_Raw):
    """模型对一个 chunk 的完整回答。"""

    summary: str = ""
    mentions: list[RawMention] = Field(default_factory=list)
    facts: list[RawFact] = Field(default_factory=list)
    events: list[RawEvent] = Field(default_factory=list)
    relations: list[RawRelation] = Field(default_factory=list)


class MentionRecord(BaseModel):
    mention_id: str
    chunk_id: str
    source_id: str
    chapter_id: str
    chapter_index: int
    chapter_label: str = ""
    name: str
    aliases: list[str] = Field(default_factory=list)
    kind: EntityKind
    note: str = ""
    source_refs: list[SourceRef] = Field(default_factory=list)
    review_status: ReviewStatus = "accepted"


class FactRecord(BaseModel):
    fact_id: str
    chunk_id: str
    source_id: str
    chapter_id: str
    chapter_index: int
    chapter_label: str = ""
    subject: str
    predicate: str
    value: str
    fact_type: FactType
    source_refs: list[SourceRef] = Field(default_factory=list)
    review_status: ReviewStatus = "accepted"
    review_note: str = ""


class EventRecord(BaseModel):
    event_id: str
    chunk_id: str
    source_id: str
    chapter_id: str
    chapter_index: int
    chapter_label: str = ""
    order_in_chapter: int
    title: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    location: str | None = None
    fact_type: FactType
    source_refs: list[SourceRef] = Field(default_factory=list)
    review_status: ReviewStatus = "accepted"


class RelationRecord(BaseModel):
    relation_id: str
    chunk_id: str
    source_id: str
    chapter_id: str
    chapter_index: int
    chapter_label: str = ""
    from_entity: str
    to_entity: str
    relation: str
    source_refs: list[SourceRef] = Field(default_factory=list)
    review_status: ReviewStatus = "accepted"


class ChunkExtraction(BaseModel):
    """一个 chunk 的校验后结果。"""

    schema_version: int = 1
    chunk_id: str
    chapter_id: str
    source_id: str
    chapter_index: int
    chapter_label: str = ""
    chapter_title: str = ""
    summary: str = ""
    provider: str = ""
    prompt_version: str = ""
    model: str = ""
    input_sha256: str = ""
    output_sha256: str = ""
    mentions: list[MentionRecord] = Field(default_factory=list)
    facts: list[FactRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    relations: list[RelationRecord] = Field(default_factory=list)
    evidence_total: int = 0
    evidence_located: int = 0
    #: 已定位但**不唯一**的条数（同一引文在原文里出现多次）。
    evidence_ambiguous: int = 0
    problems: list[str] = Field(default_factory=list)

    @property
    def evidence_coverage(self) -> float:
        return self.evidence_located / self.evidence_total if self.evidence_total else 1.0
