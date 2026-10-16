"""语义支持校验的 schema。

判定沿用文本蕴含任务的四分类，不要更多档 —— 档位越多，标注越不可靠：

- `entailed` —— 引文足以支持该主张；
- `partially_supported` —— 支持了一部分（复合事实、条件被省略、程度被夸大）；
- `contradicted` —— 引文与该主张冲突（含漏掉否定）；
- `insufficient_evidence` —— 引文与主张无关，或信息不足以判断。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["entailed", "partially_supported", "contradicted", "insufficient_evidence"]

#: 判定为「有问题」的档位 —— 这两类不得继续当作已确立的 canon 使用。
PROBLEM_VERDICTS: frozenset[str] = frozenset({"contradicted", "insufficient_evidence"})

#: 高风险谓词：错了代价最大，即使引文定位成功也应当人工过一遍。
#: 身份、生死、秘密、关系、能力上限、立场 —— 这几类被写错会直接扭曲剧情。
HIGH_IMPACT_PREDICATES: frozenset[str] = frozenset(
    {
        "identity",
        "death",
        "alive",
        "secret",
        "relationship",
        "ability",
        "status",
        "affiliation",
        "motive",
    }
)

#: 高风险取值的标志词（原文没给出谓词分类时的兜底）。
HIGH_IMPACT_MARKERS: tuple[str, ...] = (
    "其实",
    "真正",
    "秘密",
    "身份",
    "叛徒",
    "间谍",
    "死",
    "身份是",
)


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RawSemanticVerdict(_Raw):
    """期望模型直接产出的形状。"""

    verdict: Verdict
    reason: str = ""
    confidence: float = 0.0


class SemanticVerdict(BaseModel):
    """一条事实的语义校验结果。"""

    fact_id: str
    chunk_id: str = ""
    chapter_index: int = 0
    subject: str = ""
    predicate: str = ""
    value: str = ""
    quote: str = ""
    verdict: Verdict
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    high_impact: bool = False
    verifier: str = Field(default="", description="谁做的判定，例如 `llm:<model>` 或 `file`")

    @property
    def ok(self) -> bool:
        return self.verdict not in PROBLEM_VERDICTS


class SemanticReport(BaseModel):
    """整个 run 的语义校验结果。**与证据定位指标分开统计。**"""

    schema_version: int = 1
    generated_at: str = ""
    verifier: str = ""
    prompt_version: str = ""
    facts_total: int = 0
    facts_checked: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    high_impact_total: int = 0
    high_impact_checked: int = 0
    #: 判定为 contradicted / insufficient_evidence 的事实 id。
    #: 导出时会把这些事实排除在条目正文之外。
    excluded_fact_ids: list[str] = Field(default_factory=list)
    verdicts: list[SemanticVerdict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def passed_rate(self) -> float:
        if not self.facts_checked:
            return 0.0
        return self.counts.get("entailed", 0) / self.facts_checked
