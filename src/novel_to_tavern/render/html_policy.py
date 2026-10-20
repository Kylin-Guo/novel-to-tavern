"""受控 HTML 输出规范。

边界先说清楚：

- 这里只生成**提示词约束**（一条世界书触发条目），不是 Tavo 运行时过滤器。
  JSON 合法不等于聊天内容里的 HTML 一定被渲染，也不等于模型一定遵守。
- `validate_html_sample` 只用于校验本项目生成的文本与测试 fixture，
  **不能**当成客户端侧的安全保障。
- 白名单极窄：只用 `span`，只用配置里的字号、色板与斜体。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from ..timeline.worldbible import PlannedEntry, estimate_tokens

#: 唯一允许的 CSS 属性集合。
_ALLOWED_PROPERTIES = ("font-size", "color", "font-style")
_ALLOWED_PROPERTY_SET = set(_ALLOWED_PROPERTIES)

#: 色板语义名的用途建议。名字不在表里时用通用说明。
_PALETTE_HINTS = {
    "muted": "时间、地点、旁注",
    "emphasis": "关键线索、强调",
    "warning": "警示、危险",
    "mystery": "悬念、未知",
}

_SIZE_RE = re.compile(r"\d+(\.\d+)?em")
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


class HtmlPolicyError(RuntimeError):
    """HTML 规范配置非法。"""


@dataclass(frozen=True)
class HtmlPolicy:
    allowed_properties: tuple[str, ...]
    allowed_font_sizes: tuple[str, ...]
    color_palette: dict[str, str]
    max_suggested_spans_per_reply: int

    @classmethod
    def from_config(cls, cfg) -> "HtmlPolicy":
        if getattr(cfg, "mode", "controlled_span") != "controlled_span":
            raise HtmlPolicyError(f"不支持的 HTML 模式：{getattr(cfg, 'mode', '')!r}")

        properties = tuple(dict.fromkeys(cfg.allowed_properties))
        if not properties:
            raise HtmlPolicyError("allowed_properties 不能为空")
        for prop in properties:
            if prop not in _ALLOWED_PROPERTY_SET:
                raise HtmlPolicyError(f"CSS 属性不在白名单：{prop!r}")

        sizes = tuple(cfg.allowed_font_sizes)
        if not sizes:
            raise HtmlPolicyError("allowed_font_sizes 不能为空")
        for size in sizes:
            if not _SIZE_RE.fullmatch(size):
                raise HtmlPolicyError(f"字号必须是 em 相对单位：{size!r}")

        palette = dict(cfg.color_palette)
        if not palette:
            raise HtmlPolicyError("color_palette 不能为空")
        for name, color in palette.items():
            if not _NAME_RE.fullmatch(name):
                raise HtmlPolicyError(f"色板语义名不合法：{name!r}")
            if not _HEX_RE.fullmatch(color):
                raise HtmlPolicyError(f"颜色必须是 #RRGGBB：{color!r}")

        if cfg.max_suggested_spans_per_reply < 0:
            raise HtmlPolicyError("max_suggested_spans_per_reply 不能为负")

        return cls(
            allowed_properties=properties,
            allowed_font_sizes=sizes,
            color_palette=palette,
            max_suggested_spans_per_reply=cfg.max_suggested_spans_per_reply,
        )


def _examples(policy: HtmlPolicy) -> list[str]:
    """只从 policy 里取值的合法示例 —— 文中的示例本身必须能通过校验。"""
    examples: list[str] = []
    if "color" in policy.allowed_properties:
        name, color = next(iter(policy.color_palette.items()))
        examples.append(f'<span style="color: {color}">（{name}：时间与地点）</span>')
    if "font-size" in policy.allowed_properties:
        size = policy.allowed_font_sizes[-1]
        examples.append(f'<span style="font-size: {size}">关键揭示的一句</span>')
    if "font-style" in policy.allowed_properties:
        examples.append('<span style="font-style: italic">内心独白</span>')
    if len(policy.allowed_properties) >= 2 and "color" in policy.allowed_properties:
        name, color = next(iter(policy.color_palette.items()))
        examples.append(
            f'<span style="color: {color}; font-style: italic">'
            "（强调并斜体的短句）</span>"
        )
    return examples


def build_html_rules_text(policy: HtmlPolicy) -> str:
    """规范正文。所有取值都来自 policy，不写死。"""
    palette_lines = [
        f"- {name} = {color}：{_PALETTE_HINTS.get(name, '按语义使用')}"
        for name, color in policy.color_palette.items()
    ]
    example_lines = _examples(policy)

    lines = [
        "# 受控 HTML 输出规范",
        "",
        "默认使用纯文本与 Markdown。只有在确有视觉收益时才使用受控 HTML：",
        "- 章节切换、关键揭示、内心独白、书信/密令/档案。",
        "- 只用于行内片段，不用块级排版。",
        "",
        f"只允许的 CSS 属性：{'、'.join(policy.allowed_properties)}。",
        f"字号只能取：{'、'.join(policy.allowed_font_sizes)}。",
        "颜色只能取下列语义色：",
        *palette_lines,
        "",
        f"单条回复通常 0–{policy.max_suggested_spans_per_reply} 个片段；没有必要时不要用。",
        "",
        "禁止：其他标签、嵌套 span、外部资源、事件属性（以 on 开头）、"
        "任意 class 或 id、内联脚本与内嵌框架。",
        "不改变叙事内容与事实。不确定就不用；客户端可能直接显示标签原文。",
    ]
    if example_lines:
        lines += ["", "示例（纯文本回退时去掉标签）：", *example_lines]
    return "\n".join(lines)


HTML_ENTRY_KEYS = ["输出格式规范", "排版规则", "HTML格式", "视觉样式", "字号颜色"]


def build_html_entry(policy: HtmlPolicy) -> PlannedEntry:
    body = (
        build_html_rules_text(policy)
        + "\n\n本条目是格式约定，不是世界设定。"
        + "提示词不是运行时沙箱：客户端是否渲染以实测为准。"
    )
    return PlannedEntry(
        entry_id="wb_rendering_html",
        category="rendering",
        title="输出格式：受控 HTML 规范",
        content_runtime=body,
        content_canonical=body,
        keys=list(HTML_ENTRY_KEYS),
        secondary_keys=[],
        always_on=False,
        valid_from_chapter=None,
        chapter_gated=False,
        estimated_tokens=estimate_tokens(body),
        priority=30,
        quality_flags=["非 canon：输出呈现规则", "无 Tavo 运行时过滤"],
    )


class _PolicyParser(HTMLParser):
    def __init__(self, policy: HtmlPolicy) -> None:
        super().__init__(convert_charrefs=True)
        self.policy = policy
        self.violations: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag != "span":
            self.violations.append(f"只允许 span 标签，出现 <{tag}>")
            return
        if self.stack:
            self.violations.append("不允许嵌套 span")
        self.stack.append(tag)
        self._check_attrs(attrs)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag != "span":
            self.violations.append(f"只允许 span 标签，出现 <{tag}/>")
            return
        self._check_attrs(attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag != "span":
            self.violations.append(f"只允许 span 标签，出现 </{tag}>")
            return
        if not self.stack:
            self.violations.append("多余的 </span>：没有对应的开始标签")
        else:
            self.stack.pop()

    def _check_attrs(self, attrs):
        for name, value in attrs:
            if name.lower() != "style":
                self.violations.append(f"只允许 style 属性，出现 {name!r}")
                continue
            self._check_style(value or "")

    def _check_style(self, style: str) -> None:
        palette = {color.lower() for color in self.policy.color_palette.values()}
        sizes = {size.lower() for size in self.policy.allowed_font_sizes}
        for declaration in style.split(";"):
            if not declaration.strip():
                continue
            if ":" not in declaration:
                self.violations.append(f"无法解析的样式声明：{declaration.strip()!r}")
                continue
            prop, value = declaration.split(":", 1)
            prop = prop.strip().lower()
            value = value.strip().lower()
            if prop not in self.policy.allowed_properties:
                self.violations.append(f"CSS 属性不在白名单：{prop!r}")
            elif prop == "font-size" and value not in sizes:
                self.violations.append(f"字号不在白名单：{value!r}")
            elif prop == "color" and value not in palette:
                self.violations.append(f"颜色不在色板内：{value!r}")
            elif prop == "font-style" and value != "italic":
                self.violations.append(f"font-style 只能取 italic：{value!r}")

    def finish(self) -> None:
        if self.stack:
            self.violations.append("span 未闭合")


def validate_html_sample(text: str, policy: HtmlPolicy) -> list[str]:
    """返回违规原因列表；空列表表示通过。

    **仅用于校验本项目生成的文本与静态 fixture，不是 Tavo 运行时过滤器。**
    """
    parser = _PolicyParser(policy)
    parser.feed(text)
    parser.close()
    parser.finish()
    return parser.violations
