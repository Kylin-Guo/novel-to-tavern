"""导出阶段按需装配风格产物。

`style.enabled=true` 时 export 调用 `ensure_style_artifacts`：

- 产物**新鲜** → 直接加载，不需要引擎，也不需要凭据；
- 产物**缺失或过期** → 有 provider 就自动观察 + 编译；没有就报错，
  不静默产出「没有风格规范」的卡。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..timeline.worldbible import PlannedEntry
from . import StyleError
from .compiler import (
    ENTRIES_JSON,
    PROFILE_JSON,
    RUNTIME_MD,
    compute_inputs_fingerprint,
    run_style_compile,
)
from .observe import run_style_observation
from .schema import StyleProfile
from .worldbook import load_style_entries


@dataclass
class StyleArtifacts:
    profile: StyleProfile
    #: `runtime_style_prompt.md` 内容 —— 注入 Description 的唯一风格主体。
    runtime_text: str
    #: 世界书条目（`style.worldbook_entries=false` 时为空列表）。
    entries: list[PlannedEntry]


def _base(run_dir) -> Path:
    return Path(run_dir) / "author_style"


def style_artifacts_fresh(
    run_dir, config, *, endpoint_fingerprint: str = ""
) -> bool:
    """产物存在，且 `inputs_fingerprint` 与当前输入一致。"""
    base = _base(run_dir)
    profile_path = base / PROFILE_JSON
    runtime_path = base / RUNTIME_MD
    if not (profile_path.is_file() and runtime_path.is_file()):
        return False
    try:
        profile = StyleProfile.model_validate(
            json.loads(profile_path.read_text(encoding="utf-8"))
        )
        expected = compute_inputs_fingerprint(
            run_dir, config, endpoint_fingerprint=endpoint_fingerprint
        )
    except (OSError, ValueError, StyleError):
        return False
    return bool(profile.inputs_fingerprint) and profile.inputs_fingerprint == expected


def _load(run_dir, config) -> StyleArtifacts:
    base = _base(run_dir)
    profile_path = base / PROFILE_JSON
    runtime_path = base / RUNTIME_MD
    if not profile_path.is_file() or not runtime_path.is_file():
        raise StyleError(
            f"风格产物不完整：需要 {profile_path} 与 {runtime_path}。"
            "请先跑 `n2t style-compile` 或开启自动蒸馏。"
        )
    profile = StyleProfile.model_validate(
        json.loads(profile_path.read_text(encoding="utf-8"))
    )
    runtime_text = runtime_path.read_text(encoding="utf-8")

    entries: list[PlannedEntry] = []
    entries_path = base / ENTRIES_JSON
    if config.style.worldbook_entries and entries_path.is_file():
        entries = load_style_entries(entries_path)
    return StyleArtifacts(profile=profile, runtime_text=runtime_text, entries=entries)


def ensure_style_artifacts(
    run_dir, config, provider=None, *, log=None
) -> StyleArtifacts:
    if style_artifacts_fresh(run_dir, config):
        return _load(run_dir, config)

    if provider is None:
        raise StyleError(
            "风格产物不存在或已过期，需要 LLM 引擎自动蒸馏："
            "请配置凭据，或先用 file provider 预生成，或关闭 style.enabled。"
        )

    result = run_style_observation(config, run_dir, provider, log=log)
    if not result["ok"]:
        raise StyleError(
            "风格观察有失败分块，已中止编译："
            + "；".join(f"{k}：{v}" for k, v in sorted(result["failed"].items()))
        )
    run_style_compile(run_dir, config, provider, log=log)
    return _load(run_dir, config)
