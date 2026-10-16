"""语义支持校验（Phase 6）。

**这一层不替代证据定位。** 两者回答的是不同问题：

| 检查 | 回答的问题 | 阶段 |
|---|---|---|
| 证据定位 | 引文**逐字存在于原文**吗？行号对不对？ | Phase 2（必需） |
| 语义支持 | 这条引文**支持**这条主张吗？ | Phase 6（本层） |

引文可能存在却说明不了那条主张：归属给错了人、漏掉了否定、
把角色的信念当成客观事实、或者只支持了复合事实的一部分。
所以「引文 100% 定位」**不是**「事实 100% 正确」。
"""

from .runner import (
    SEMANTIC_NAME,
    VERIFY_DIR,
    VerificationError,
    high_impact_facts,
    load_verdicts,
    run_verification,
)
from .schema import (
    HIGH_IMPACT_PREDICATES,
    RawSemanticVerdict,
    SemanticReport,
    SemanticVerdict,
    Verdict,
)

__all__ = [
    "HIGH_IMPACT_PREDICATES",
    "SEMANTIC_NAME",
    "VERIFY_DIR",
    "RawSemanticVerdict",
    "SemanticReport",
    "SemanticVerdict",
    "Verdict",
    "VerificationError",
    "high_impact_facts",
    "load_verdicts",
    "run_verification",
]
