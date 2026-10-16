"""抽取引擎的装配。

凭据只从环境变量/.env 读，且只按配置里的**变量名**间接寻址；
不硬编码供应商，不自动切换到别的 endpoint。
"""

from __future__ import annotations

from pathlib import Path

from .. import config as config_module, env as env_module
from .client import CompletionResult, LLMError, LLMRetryableError, OpenAIChatClient
from .provider import (
    Completion,
    FileProvider,
    MissingResponseError,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
)


def build_provider(
    config: config_module.Config,
    *,
    dotenv_path: str | Path = env_module.DEFAULT_DOTENV,
    log=None,
) -> Provider:
    """按配置返回抽取引擎。缺凭据时给出可操作的错误，而不是含糊失败。"""
    llm = config.llm

    if llm.provider == "file":
        if not llm.precomputed_responses_dir:
            raise ProviderError(
                "llm.provider=file 时必须设置 llm.precomputed_responses_dir。"
            )
        return FileProvider(llm.precomputed_responses_dir)

    api_key = env_module.resolve_variable(llm.api_key_env, dotenv_path=dotenv_path)
    base_url = env_module.resolve_variable(llm.base_url_env, dotenv_path=dotenv_path)

    missing = [
        name
        for name, value in ((llm.api_key_env, api_key), (llm.base_url_env, base_url))
        if not value
    ]
    if missing:
        raise ProviderError(
            "缺少凭据，无法调用抽取引擎："
            + "、".join(missing)
            + "。请写入 .env（已在 .gitignore 中），"
            "或把 llm.provider 设为 file 走离线预生成响应。"
        )

    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=llm.extraction_model or "",
        temperature=llm.temperature_extract,
        timeout_seconds=llm.request_timeout_seconds,
        max_retries=llm.max_retries,
        backoff_seconds=llm.retry_backoff_seconds,
        max_output_tokens=llm.max_output_tokens,
        log=log,
    )


__all__ = [
    "Completion",
    "CompletionResult",
    "FileProvider",
    "LLMError",
    "LLMRetryableError",
    "MissingResponseError",
    "OpenAIChatClient",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
    "build_provider",
]
