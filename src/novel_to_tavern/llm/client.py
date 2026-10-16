"""OpenAI 兼容 endpoint 的最小客户端。

只用标准库 `urllib`，不引入 requests/httpx。
有限重试 + 指数退避；429/5xx/超时可重试，4xx（除 429）不重试。
**绝不记录 API key**：日志里只出现 endpoint 主机名与状态码。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

#: 可重试的 HTTP 状态码。
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """调用失败（已耗尽重试）。"""


class LLMRetryableError(LLMError):
    """可重试的失败。"""


@dataclass
class CompletionResult:
    text: str
    model: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


def _safe_host(url: str) -> str:
    try:
        return urlparse(url).netloc or "<invalid-url>"
    except Exception:  # pragma: no cover - urlparse 极少抛错
        return "<invalid-url>"


class OpenAIChatClient:
    """`POST {base_url}/chat/completions`。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 180,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        log=None,
    ) -> None:
        if not base_url:
            raise LLMError("base_url 为空：请设置配置里 base_url_env 指向的环境变量。")
        if not api_key:
            raise LLMError("api_key 为空：请设置配置里 api_key_env 指向的环境变量。")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._log = log

    @property
    def host(self) -> str:
        return _safe_host(self.base_url)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.1,
        max_output_tokens: int | None = None,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if max_output_tokens:
            payload["max_tokens"] = max_output_tokens

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                return self._parse(raw, model=model, attempts=attempt)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                last_error = LLMRetryableError(f"HTTP {exc.code} from {self.host}: {detail}")
                if exc.code not in RETRYABLE_STATUS:
                    raise LLMError(
                        f"HTTP {exc.code} from {self.host}（该状态码不重试）：{detail}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = LLMRetryableError(f"网络错误（{self.host}）：{exc}")

            if attempt <= self.max_retries:
                wait = self.backoff_seconds * (2 ** (attempt - 1))
                if self._log:
                    self._log.warning(
                        "调用失败，第 %d 次重试前等待 %.1fs：%s", attempt, wait, last_error
                    )
                time.sleep(wait)

        raise LLMError(f"重试 {self.max_retries} 次后仍失败：{last_error}")

    @staticmethod
    def _parse(raw: str, *, model: str, attempts: int) -> CompletionResult:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMRetryableError(f"endpoint 返回的不是 JSON：{exc}") from exc

        if "choices" not in data:
            raise LLMRetryableError(f"响应缺少 choices 字段：{str(data)[:200]}")

        choices = data["choices"]
        if not choices:
            raise LLMRetryableError("choices 为空")
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if not text:
            raise LLMRetryableError("响应内容为空")

        return CompletionResult(
            text=text,
            model=data.get("model", model),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage") or {},
            attempts=attempts,
        )
