"""抽取引擎：HTTP 重试策略、file provider、凭据装配。全程不打真实网络。"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.llm import (
    FileProvider,
    LLMError,
    MissingResponseError,
    OpenAIChatClient,
    OpenAICompatibleProvider,
    ProviderError,
    build_provider,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _chat_payload(text: str = '{"ok": 1}') -> bytes:
    return json.dumps(
        {
            "model": "test-model",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    ).encode("utf-8")


def _client(**kwargs) -> OpenAIChatClient:
    defaults = dict(
        base_url="https://api.invalid/v1",
        api_key="sk-test-abcdefghijklmnop",
        timeout_seconds=5,
        max_retries=2,
        backoff_seconds=0.0,
    )
    defaults.update(kwargs)
    return OpenAIChatClient(**defaults)


def test_successful_call_parses_content_and_usage(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(_chat_payload()))
    result = _client().complete(system_prompt="s", user_prompt="u", model="test-model")
    assert result.text == '{"ok": 1}'
    assert result.usage["prompt_tokens"] == 10
    assert result.finish_reason == "stop"


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                "https://api.invalid/v1/chat/completions", 429, "Too Many Requests", {}, io.BytesIO(b"slow down")
            )
        return FakeResponse(_chat_payload())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = _client().complete(system_prompt="s", user_prompt="u", model="m")
    assert calls["n"] == 2
    assert result.attempts == 2


def test_does_not_retry_on_400(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(*args, **kwargs):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "https://api.invalid/v1/chat/completions", 400, "Bad Request", {}, io.BytesIO(b"bad payload")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMError, match="400"):
        _client().complete(system_prompt="s", user_prompt="u", model="m")
    assert calls["n"] == 1


def test_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(*args, **kwargs):
        calls["n"] += 1
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMError, match="重试"):
        _client(max_retries=2).complete(system_prompt="s", user_prompt="u", model="m")
    assert calls["n"] == 3  # 首次 + 2 次重试


def test_truncated_or_empty_choice_is_retryable(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: FakeResponse(json.dumps({"choices": []}).encode())
    )
    with pytest.raises(LLMError):
        _client(max_retries=0).complete(system_prompt="s", user_prompt="u", model="m")


def test_error_messages_never_contain_the_api_key(monkeypatch):
    secret = "sk-super-secret-key-abcdefgh"

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://api.invalid/v1/chat/completions", 401, "Unauthorized", {}, io.BytesIO(b"nope")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(LLMError) as excinfo:
        _client(api_key=secret, max_retries=0).complete(system_prompt="s", user_prompt="u", model="m")
    assert secret not in str(excinfo.value)
    assert "api.invalid" in str(excinfo.value)


def test_empty_credentials_are_rejected_early():
    with pytest.raises(LLMError, match="api_key 为空"):
        OpenAIChatClient(base_url="https://api.invalid/v1", api_key="")
    with pytest.raises(LLMError, match="base_url 为空"):
        OpenAIChatClient(base_url="", api_key="x")


# --- file provider --------------------------------------------------------


def test_file_provider_reads_text_envelope(tmp_path):
    (tmp_path / "chunk_a.json").write_text(
        json.dumps({"text": '{"summary": "x"}', "model": "pre"}), encoding="utf-8"
    )
    completion = FileProvider(tmp_path).complete(
        chunk_id="chunk_a", system_prompt="", user_prompt=""
    )
    assert completion.text == '{"summary": "x"}'
    assert completion.model == "pre"


def test_file_provider_accepts_bare_extraction_object(tmp_path):
    (tmp_path / "chunk_a.json").write_text(
        json.dumps({"summary": "x", "mentions": []}), encoding="utf-8"
    )
    completion = FileProvider(tmp_path).complete(
        chunk_id="chunk_a", system_prompt="", user_prompt=""
    )
    assert json.loads(completion.text)["summary"] == "x"


def test_file_provider_reports_missing_response_clearly(tmp_path):
    with pytest.raises(MissingResponseError, match="缺少预生成响应"):
        FileProvider(tmp_path).complete(chunk_id="nope", system_prompt="", user_prompt="")


def test_file_provider_rejects_missing_directory(tmp_path):
    with pytest.raises(ProviderError, match="不存在"):
        FileProvider(tmp_path / "absent")


# --- 装配 -----------------------------------------------------------------


def test_build_provider_requires_credentials():
    with pytest.raises(ProviderError, match="缺少凭据"):
        build_provider(config_module.Config(), dotenv_path="/nonexistent/.env")


def test_build_provider_error_points_at_the_dotenv(tmp_path):
    cfg = config_module.Config()
    with pytest.raises(ProviderError) as excinfo:
        build_provider(cfg, dotenv_path=tmp_path / ".env")
    assert cfg.llm.api_key_env in str(excinfo.value)
    assert cfg.llm.base_url_env in str(excinfo.value)
    assert ".env" in str(excinfo.value)


def test_build_provider_reads_credentials_from_dotenv(tmp_path, monkeypatch):
    cfg = config_module.Config()
    monkeypatch.delenv(cfg.llm.api_key_env, raising=False)
    monkeypatch.delenv(cfg.llm.base_url_env, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{cfg.llm.api_key_env}=sk-abcdefghijklmnop1234\n"
        f"{cfg.llm.base_url_env}=https://free.example.invalid/v1\n",
        encoding="utf-8",
    )
    cfg = cfg.model_copy(
        update={"llm": cfg.llm.model_copy(update={"extraction_model": "some-free-model"})}
    )
    provider = build_provider(cfg, dotenv_path=dotenv)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "openai_compatible"


def test_build_provider_requires_a_model_name(tmp_path):
    cfg = config_module.Config()
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{cfg.llm.api_key_env}=sk-abcdefghijklmnop1234\n"
        f"{cfg.llm.base_url_env}=https://free.example.invalid/v1\n",
        encoding="utf-8",
    )
    with pytest.raises(ProviderError, match="extraction_model"):
        build_provider(cfg, dotenv_path=dotenv)


def test_build_provider_file_mode_needs_a_directory(tmp_path):
    cfg = config_module.Config()
    cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"provider": "file"})})
    with pytest.raises(ProviderError, match="precomputed_responses_dir"):
        build_provider(cfg, dotenv_path=tmp_path / ".env")


def test_build_provider_file_mode_works_offline(tmp_path):
    cfg = config_module.Config()
    cfg = cfg.model_copy(
        update={
            "llm": cfg.llm.model_copy(
                update={"provider": "file", "precomputed_responses_dir": str(tmp_path)}
            )
        }
    )
    assert isinstance(build_provider(cfg, dotenv_path=tmp_path / ".env"), FileProvider)
