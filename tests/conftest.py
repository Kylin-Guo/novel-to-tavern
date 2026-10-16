"""测试公共装置。

默认不访问网络、不调用任何 API、不读取真实凭据。未安装包时回退到 src 布局。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_secret_registry():
    """每条测试前后清空密钥登记表，避免相互污染。"""
    from novel_to_tavern import secrets

    secrets.clear_registered()
    yield
    secrets.clear_registered()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _no_ambient_api_env(monkeypatch):
    """确保测试环境里没有真实凭据，防止意外外泄到断言输出。"""
    from novel_to_tavern import config as config_module

    monkeypatch.delenv(config_module.LLMConfig().api_key_env, raising=False)
    monkeypatch.delenv(config_module.LLMConfig().base_url_env, raising=False)
