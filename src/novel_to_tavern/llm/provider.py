"""抽取引擎的两种实现。

- `openai_compatible`：真实调用用户配置的 endpoint（免费额度场景）。
- `file`：从目录读**预先产出**的响应，文件名 = `<chunk_id>.json`。

`file` 不是测试替身，而是一条正式路径：没有可用凭据时仍能离线跑完整条管线，
也便于同一份输入在不同引擎之间对拍。产出的 run 会在 manifest 与审计报告里
明确标注 `provider`，不冒充 API 调用结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .client import LLMError, OpenAIChatClient


class ProviderError(RuntimeError):
    """抽取失败。"""


class MissingResponseError(ProviderError):
    """file provider 找不到对应 chunk 的响应。"""


@dataclass
class Completion:
    text: str
    model: str = ""
    usage: dict | None = None
    finish_reason: str | None = None


def normalize_endpoint(base_url: str) -> str:
    """把 base_url 归一成一个**不含凭据**的指纹串。

    为什么需要它：`provider.name` 对 OpenAI 兼容引擎永远是常量
    `"openai_compatible"`。换一家兼容服务、模型名又恰好相同时，缓存会命中
    上一家的响应 —— 而且命中是静默的，看起来就像「改了配置但结果没变」。

    归一化规则：小写 scheme/host，去掉末尾 `/`，**丢掉 query 与 fragment**。
    丢掉 query 是因为有些服务把 key 放在查询串里 —— 那绝不能进缓存键，
    缓存文件名是会被列目录看到的。
    """
    parsed = urlsplit(base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        # 不是完整 URL（例如用户只写了主机名）：只做大小写与斜杠归一。
        return base_url.strip().rstrip("/").lower()
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


class Provider(Protocol):
    name: str
    #: 这个引擎**具体连到哪里**。缓存键必须包含它，否则换 endpoint 会静默复用旧结果。
    endpoint_fingerprint: str

    def complete(self, *, chunk_id: str, system_prompt: str, user_prompt: str) -> Completion: ...


class FileProvider:
    """按 `chunk_id` 从目录读预生成响应。

    目录里每个文件是 `{"text": "...", "model": "..."}`，或直接是抽取结果的
    JSON 对象（此时会被重新序列化成文本，走与 API 完全相同的解析路径）。
    """

    name = "file"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise ProviderError(f"file provider 的响应目录不存在：{self.root}")
        # 换一个预生成目录就是换了一份数据源，缓存必须跟着失效。
        self.endpoint_fingerprint = f"file:{self.root.resolve()}"

    def _path_for(self, chunk_id: str) -> Path:
        return self.root / f"{chunk_id}.json"

    def complete(self, *, chunk_id: str, system_prompt: str, user_prompt: str) -> Completion:
        path = self._path_for(chunk_id)
        if not path.is_file():
            raise MissingResponseError(
                f"缺少预生成响应：{path}（chunk_id={chunk_id}）"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "text" in payload:
            return Completion(
                text=payload["text"],
                model=payload.get("model", "precomputed"),
                usage=payload.get("usage"),
                finish_reason=payload.get("finish_reason", "stop"),
            )
        return Completion(
            text=json.dumps(payload, ensure_ascii=False),
            model="precomputed",
            finish_reason="stop",
        )


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        timeout_seconds: int = 180,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        max_output_tokens: int | None = None,
        log=None,
    ) -> None:
        if not model:
            raise ProviderError("未配置模型名：请设置 llm.extraction_model。")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.endpoint_fingerprint = normalize_endpoint(base_url)
        self._client = OpenAIChatClient(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            log=log,
        )

    def complete(self, *, chunk_id: str, system_prompt: str, user_prompt: str) -> Completion:
        try:
            result = self._client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        except LLMError as exc:
            raise ProviderError(str(exc)) from exc
        return Completion(
            text=result.text,
            model=result.model,
            usage=result.usage,
            finish_reason=result.finish_reason,
        )
