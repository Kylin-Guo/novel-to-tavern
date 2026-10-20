"""风格管线的缓存键与读写。

缓存键必须包含**全部语义相关输入**：阶段、模型、endpoint、提示词版本、
提示词模板 hash、两个 schema 版本、输入内容 hash、temperature。

漏掉任何一项都会造成「改了东西但结果没变」这种最难查的故障。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .prompts import (
    PROMPT_VERSION_COMPILE,
    PROMPT_VERSION_COMPRESS,
    PROMPT_VERSION_MERGE,
    PROMPT_VERSION_OBSERVE,
    prompt_template_hash,
)
from .schema import OBSERVATION_SCHEMA_VERSION, PROFILE_SCHEMA_VERSION

#: 四个阶段的版本号一起进模板 hash 的语义，供审计展示。
PROMPT_VERSIONS = {
    "style_observe": PROMPT_VERSION_OBSERVE,
    "style_merge": PROMPT_VERSION_MERGE,
    "style_compile": PROMPT_VERSION_COMPILE,
    "style_compress": PROMPT_VERSION_COMPRESS,
}


def style_cache_key(
    *,
    kind: str,
    config,
    provider,
    prompt_version: str,
    input_sha256: str,
    extra: dict | None = None,
) -> str:
    payload = {
        "kind": kind,
        "model": config.llm.extraction_model or getattr(provider, "model", "") or "",
        "endpoint_fingerprint": getattr(provider, "endpoint_fingerprint", ""),
        "prompt_version": prompt_version,
        "prompt_template_sha256": prompt_template_hash(),
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "input_sha256": input_sha256,
        "temperature": config.llm.temperature_extract,
        # 输出长度上限会改变模型回答；不进键就是「改了参数结果不变」。
        "max_output_tokens": config.llm.max_output_tokens,
    }
    payload.update(extra or {})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def cache_path(config, key: str) -> Path:
    return Path(config.pipeline.cache_dir) / f"{key}.json"


def load_cached_response(config, key: str) -> str | None:
    if not config.pipeline.cache_enabled:
        return None
    path = cache_path(config, key)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("text")


def store_cached_response(config, key: str, text: str, *, model: str) -> None:
    if not config.pipeline.cache_enabled:
        return
    path = cache_path(config, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"text": text, "model": model}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
