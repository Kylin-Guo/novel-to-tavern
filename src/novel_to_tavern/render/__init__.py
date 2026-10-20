"""受控 HTML 输出规范（世界书触发条目，默认关闭）。

提示词约束，不是运行时沙箱。详见 docs/HTML_RENDERING.md。
"""

from __future__ import annotations

from .html_policy import (
    HTML_ENTRY_KEYS,
    HtmlPolicy,
    HtmlPolicyError,
    build_html_entry,
    build_html_rules_text,
    validate_html_sample,
)

__all__ = [
    "HTML_ENTRY_KEYS",
    "HtmlPolicy",
    "HtmlPolicyError",
    "build_html_entry",
    "build_html_rules_text",
    "validate_html_sample",
]
