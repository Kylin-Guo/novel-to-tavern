"""作者风格自动蒸馏（旁路资料流，默认关闭）。

风格资料**不是 canon**：不写 facts / entities / timeline / knowledge，
不改变任何原著事实。完整流程见 `docs/AUTHOR_STYLE_PIPELINE.md`。
"""

from __future__ import annotations


class StyleError(RuntimeError):
    """风格管线的统一错误基类。"""


from .compiler import (
    AUDIT_NAME,
    ENTRIES_JSON,
    EVAL_CASES_JSON,
    PROFILE_JSON,
    PROFILE_MD,
    RUNTIME_MD,
    StyleCompileError,
    compute_inputs_fingerprint,
    render_profile_md,
    render_runtime_prompt,
    run_style_compile,
)
from .observe import (
    INDEX_NAME,
    OBSERVATIONS_DIR,
    STYLE_DIR,
    StyleObservationRunner,
    StyleObserveError,
    run_style_observation,
    select_chunks,
)
from .pipeline import (
    StyleArtifacts,
    ensure_style_artifacts,
    style_artifacts_fresh,
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
from .worldbook import (
    STYLE_ENTRY_GROUPS,
    STYLE_ENTRY_KEYS,
    STYLE_ENTRY_MUST_NOT_TRIGGER,
    StyleLeakError,
    build_style_entries,
    check_style_no_plot_leak,
    load_style_entries,
    write_style_entries,
)

__all__ = [
    "AUDIT_NAME",
    "ENTRIES_JSON",
    "EVAL_CASES_JSON",
    "INDEX_NAME",
    "OBSERVATION_SCHEMA_VERSION",
    "OBSERVATIONS_DIR",
    "PROFILE_JSON",
    "PROFILE_MD",
    "PROFILE_SCHEMA_VERSION",
    "RUNTIME_MD",
    "STYLE_DIMENSIONS",
    "STYLE_DIR",
    "STYLE_ENTRY_GROUPS",
    "STYLE_ENTRY_KEYS",
    "STYLE_ENTRY_MUST_NOT_TRIGGER",
    "RawStyleEvidence",
    "RawStyleObservation",
    "SourceManifestEntry",
    "StyleArtifacts",
    "StyleCompileError",
    "StyleDimension",
    "StyleError",
    "StyleEvalCase",
    "StyleEvidence",
    "StyleLeakError",
    "StyleObservation",
    "StyleObservationRunner",
    "StyleObserveError",
    "StyleProfile",
    "build_style_entries",
    "check_style_no_plot_leak",
    "compute_inputs_fingerprint",
    "ensure_style_artifacts",
    "load_style_entries",
    "render_profile_md",
    "render_runtime_prompt",
    "run_style_compile",
    "run_style_observation",
    "select_chunks",
    "style_artifacts_fresh",
    "write_style_entries",
]
