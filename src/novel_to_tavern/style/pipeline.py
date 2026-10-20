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


#: 开启风格模块时，写在 Description **最开头**的写作要求。
#:
#: 为什么放在开头：Description 是每轮都在上下文里的最稳定位置；
#: 用户要的是「先看到模仿作者风格的要求」，而不是先看到世界模拟器说明。
#: 这里明确指向世界书的「作者风格：…」条目 —— 具体规则在那些条目里，
#: 不是在 Description 里重复一遍。
STYLE_DESCRIPTION_PREAMBLE = (
    "【写作要求：作者风格】本卡附带从原著蒸馏出的作者风格档案。"
    "写作时请尽量模仿该作品的文风：句式与段落节奏、环境与感官描写、"
    "对白与潜台词、心理呈现、场景推进，都按风格档案执行。"
    "具体规则见世界书中标题以「作者风格：」开头的 8 组条目 ——"
    "用户提到「作者风格」「叙事风格」「语言风格」「文风特点」「写作风格」时会触发，"
    "请优先按那些条目写，而不是套用通用网文腔。"
    "风格只约束写法，不改变原著事实、角色设定与时间线。"
)


def style_description(description: str, runtime_text: str) -> str:
    """把风格要求放到 Description 开头，并在末尾保留精简运行时规范分节。"""
    return (
        STYLE_DESCRIPTION_PREAMBLE
        + "\n\n"
        + description.strip()
        + "\n\n【叙事风格规范】\n"
        + runtime_text.strip()
    )


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
