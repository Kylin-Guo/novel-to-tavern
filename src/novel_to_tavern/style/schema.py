"""作者风格资料的 schema。

分两层，与 `extract/schema.py` 的 Raw/Record 分层同理：

- `Raw*`：模型直接产出的形状。**模型只给引文，不给行号。**
- `StyleObservation` / `StyleProfile`：经代码校验后的结果。
  引文的行号由 `evidence.locate_quote` 在原文里搜出来，不接受模型自报。

风格资料**不是 canon**：它不写 facts/entities/timeline/knowledge，
也不改变任何原著事实。详见 `docs/AUTHOR_STYLE_PIPELINE.md`。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OBSERVATION_SCHEMA_VERSION = 1
PROFILE_SCHEMA_VERSION = "style_profile_v1"

#: 七个风格维度。顺序固定，提示词与世界书分组都按它来。
STYLE_DIMENSIONS: tuple[str, ...] = (
    "narrative_voice",
    "sentence_rhythm",
    "description_patterns",
    "figurative_language",
    "dialogue_patterns",
    "psychological_narration",
    "scene_pacing",
)

Confidence = Literal["high", "medium", "low", "unknown"]


class _Base(BaseModel):
    """严格模式：多一个字段就报错。

    模型输出被当成数据，不是指令；未知字段被静默收下会让「提示词改了、
    schema 没改」这类漂移看不出来。
    """

    model_config = ConfigDict(extra="forbid")


# --- 观察层（逐分块） ------------------------------------------------------


class RawStyleEvidence(_Base):
    """模型给出的一条引文。只给引文，不信行号。"""

    aspect: str
    quote: str


class RawStyleObservation(_Base):
    """模型对单个分块的风格观察。"""

    narrative_voice: str = "unknown"
    sentence_rhythm: str = "unknown"
    description_patterns: str = "unknown"
    figurative_language: str = "unknown"
    dialogue_patterns: str = "unknown"
    psychological_narration: str = "unknown"
    scene_pacing: str = "unknown"
    notable_motifs: list[str] = Field(default_factory=list)
    anti_patterns_observed: list[str] = Field(default_factory=list)
    evidence: list[RawStyleEvidence] = Field(default_factory=list)


class StyleEvidence(RawStyleEvidence):
    """引文在原文里定位成功后的形状。行号由代码填。"""

    start_line: int
    end_line: int


class StyleObservation(RawStyleObservation):
    schema_version: int = OBSERVATION_SCHEMA_VERSION
    chunk_id: str
    #: 全局章节序号（`Manifest.global_chapter_order`），多卷本不会撞号。
    chapter_index: int
    source_id: str
    evidence: list[StyleEvidence] = Field(default_factory=list)
    #: 定位失败被丢弃的引文数。观察本身保留，丢弃数留作审计。
    quotes_dropped: int = 0
    model: str = ""
    prompt_version: str = ""
    input_sha256: str = ""
    output_sha256: str = ""


# --- 档案层（编译产物） ----------------------------------------------------


class StyleDimension(_Base):
    summary: str = "unknown"
    #: 行为式规则（「怎么写」），不是形容词堆砌。
    rules: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"


class SourceManifestEntry(_Base):
    kind: Literal["novel", "interview", "essay", "note", "other"]
    locator: str
    detail: str = ""


class StyleEvalCase(_Base):
    case_id: str
    #: 场景铺陈 / 人物对话 / 内心活动 / 冲突 / 情绪克制爆发 / 场景收束
    scenario_type: str
    instruction: str
    #: 应符合的风格规律（抽象描述，不是原文）
    expected_traits: list[str]
    anti_patterns: list[str] = Field(default_factory=list)


class StyleProfile(_Base):
    schema_version: str = PROFILE_SCHEMA_VERSION
    profile_id: str
    author_label: str
    works_in_scope: list[str]
    created_at: str
    source_manifest: list[SourceManifestEntry]
    narrative_voice: StyleDimension
    sentence_rhythm: StyleDimension
    description_patterns: StyleDimension
    figurative_language: StyleDimension
    dialogue_patterns: StyleDimension
    psychological_narration: StyleDimension
    scene_pacing: StyleDimension
    genre_tone: StyleDimension
    anti_patterns: list[str] = Field(default_factory=list)
    #: 不同场景/卷次的风格差异。合并阶段保留分歧，不强行统一。
    contextual_variants: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_review_items: list[str] = Field(default_factory=list)
    #: 注入 Description 的精简运行时规范正文。
    runtime_rules: str = ""
    eval_cases: list[StyleEvalCase] = Field(default_factory=list)
    #: export 的产物新鲜度判定依据，见 `compiler.compute_inputs_fingerprint`。
    inputs_fingerprint: str = ""
