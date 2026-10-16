"""API 密钥登记与脱敏。

密钥只允许来自环境变量或 .env。本模块不持有密钥来源，只记住"哪些字符串是密钥"，
以便日志与导出前统一擦除。任何密钥值都不得写入日志、测试 fixture 或导出的角色卡。
"""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"

# 短于该长度的值不登记：避免把常见短字符串（如 "test"）误当密钥全局擦除。
MIN_SECRET_LENGTH = 8

# 兜底模式：即使未登记，也擦掉形如供应商密钥的串。
_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}\b"),
)

_registered: set[str] = set()


def register_secret(value: str | None) -> None:
    """登记一个密钥值。过短或空值忽略。"""
    if not value or len(value) < MIN_SECRET_LENGTH:
        return
    _registered.add(value)


def clear_registered() -> None:
    """清空登记表（测试用）。"""
    _registered.clear()


def redact(text: str) -> str:
    """返回擦除密钥后的文本。"""
    if not text:
        return text
    result = text
    for secret in sorted(_registered, key=len, reverse=True):
        result = result.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_object(value):
    """递归擦除 dict / list / str 中的密钥，返回新对象。"""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_object(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_object(v) for v in value]
    return value
