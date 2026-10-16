"""最小 .env 读取（标准库实现，不引入 python-dotenv）。

只支持 `KEY=VALUE` 这类常见写法：允许 `#` 注释、空行、`export ` 前缀、
单/双引号包裹的值。解析结果只返回字典，由调用方决定是否写入 os.environ。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DOTENV = ".env"


def parse_dotenv(text: str) -> dict[str, str]:
    """解析 .env 文本为字典。不修改 os.environ。"""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(path: str | Path = DEFAULT_DOTENV) -> dict[str, str]:
    """.env 不存在时返回空字典，不报错。"""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    return parse_dotenv(file_path.read_text(encoding="utf-8"))


def resolve_variable(name: str, *, dotenv_path: str | Path = DEFAULT_DOTENV) -> str | None:
    """按「真实环境变量优先，其次 .env」取值。只返回名字对应的值，不打印。"""
    from_env = os.environ.get(name)
    if from_env:
        return from_env
    return load_dotenv(dotenv_path).get(name) or None


def is_set(name: str, *, dotenv_path: str | Path = DEFAULT_DOTENV) -> bool:
    """只回答"是否已配置"，不返回也不打印值。"""
    return resolve_variable(name, dotenv_path=dotenv_path) is not None
