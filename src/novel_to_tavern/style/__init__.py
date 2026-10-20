"""作者风格自动蒸馏（旁路资料流，默认关闭）。

风格资料**不是 canon**：不写 facts / entities / timeline / knowledge，
不改变任何原著事实。完整流程见 `docs/AUTHOR_STYLE_PIPELINE.md`。
"""

from __future__ import annotations


class StyleError(RuntimeError):
    """风格管线的统一错误基类。"""


from .observe import (
    INDEX_NAME,
    OBSERVATIONS_DIR,
    STYLE_DIR,
    StyleObservationRunner,
    StyleObserveError,
    run_style_observation,
    select_chunks,
)
from .schema import (
    OBSERVATION_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    STYLE_DIMENSIONS,
    RawStyleEvidence,
    RawStyleObservation,
    SourceManifestEntry,
    StyleDimension,
    StyleEvalCase,
    StyleEvidence,
    StyleObservation,
    StyleProfile,
)

__all__ = [
    "INDEX_NAME",
    "OBSERVATION_SCHEMA_VERSION",
    "OBSERVATIONS_DIR",
    "PROFILE_SCHEMA_VERSION",
    "STYLE_DIMENSIONS",
    "STYLE_DIR",
    "RawStyleEvidence",
    "RawStyleObservation",
    "SourceManifestEntry",
    "StyleDimension",
    "StyleError",
    "StyleEvalCase",
    "StyleEvidence",
    "StyleObservation",
    "StyleObservationRunner",
    "StyleObserveError",
    "StyleProfile",
    "run_style_observation",
    "select_chunks",
]
