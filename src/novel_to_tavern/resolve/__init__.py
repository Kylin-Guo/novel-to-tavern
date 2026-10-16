"""实体消歧与角色档案（Phase 3）。

名字相似不足以证明是同一个实体；低置信度候选进复核队列而非被自动合并或裁剪。
"""

from __future__ import annotations

from .entities import (
    CanonicalEntity,
    MergeDecision,
    NameCluster,
    ResolutionResult,
    ROLE_NOUNS,
    alias_links,
    declared_aliases,
    cluster_mentions,
    is_role_noun,
    normalize_name,
    propose_merges,
)
from .runner import (
    CANONICAL_DIR,
    DECISIONS_NAME,
    ENTITIES_NAME,
    REVIEW_NAME,
    SUMMARY_NAME,
    ResolutionError,
    load_extractions,
    resolve,
)

__all__ = [
    "declared_aliases",
    "CANONICAL_DIR",
    "DECISIONS_NAME",
    "ENTITIES_NAME",
    "REVIEW_NAME",
    "ROLE_NOUNS",
    "SUMMARY_NAME",
    "CanonicalEntity",
    "MergeDecision",
    "NameCluster",
    "ResolutionError",
    "ResolutionResult",
    "alias_links",
    "cluster_mentions",
    "is_role_noun",
    "load_extractions",
    "normalize_name",
    "propose_merges",
    "resolve",
]
