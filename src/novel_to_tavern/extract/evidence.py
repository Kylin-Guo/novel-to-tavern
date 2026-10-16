"""证据定位：把模型给出的引文锚定到真实行号。

**不允许模型自己给行号** —— 行号由本模块在原文里搜索引文后算出。
引文在原文中找不到，就说明这条内容没有来源，绝不能标成 canon。

这是「不把模型推断伪装成原著事实」在代码层的落点。
"""

from __future__ import annotations


from typing import NamedTuple

from pydantic import BaseModel

#: 引文最多允许跨多少行。超过说明模型在"编一段大意"而不是引用原文。
MAX_QUOTE_SPAN_LINES = 8

#: 引文长度上限，防止把整章塞进 evidence。
MAX_QUOTE_CHARS = 400



class LocatedQuote(BaseModel):
    start_line: int
    end_line: int
    matched_text: str


class QuoteCheck(NamedTuple):
    located: LocatedQuote | None
    reason: str


def normalize_for_match(text: str) -> str:
    """去掉全部空白后再比对，避免换行/缩进差异导致误判为"找不到"。"""
    return "".join(ch for ch in text if not ch.isspace())


def locate_quote(
    lines: list[str],
    quote: str,
    *,
    window: tuple[int, int] | None = None,
    max_span: int = MAX_QUOTE_SPAN_LINES,
) -> QuoteCheck:
    """在 `lines`（可限定 window）里找 `quote`，返回其覆盖的行范围。

    匹配前去掉所有空白，因此逐行排版差异不影响结果；
    返回的行号一定是**真实覆盖该引文**的行区间。
    """
    if not quote or not quote.strip():
        return QuoteCheck(None, "引文为空")
    if len(quote) > MAX_QUOTE_CHARS:
        return QuoteCheck(None, f"引文过长（{len(quote)} 字符 > {MAX_QUOTE_CHARS}）")

    needle = normalize_for_match(quote)
    if not needle:
        return QuoteCheck(None, "引文去空白后为空")

    start = window[0] if window else 0
    end = window[1] if window else len(lines)

    # 先把窗口内的非空白字符连成一条，并记住每个字符来自哪一行；
    # 命中后映射回行号，得到的是**最紧**的覆盖区间，而不是最早能容纳它的区间。
    chars: list[str] = []
    line_of: list[int] = []
    for line_no in range(start, end):
        for ch in lines[line_no]:
            if not ch.isspace():
                chars.append(ch)
                line_of.append(line_no)

    position = "".join(chars).find(needle)
    if position == -1:
        return QuoteCheck(None, "引文在原文中找不到（可能是转述或臆造）")

    first_line = line_of[position]
    last_line = line_of[position + len(needle) - 1]
    if last_line - first_line + 1 > max_span:
        return QuoteCheck(
            None,
            f"引文横跨 {last_line - first_line + 1} 行，超过 {max_span} 行上限"
            "（这更像是概括而非引用）",
        )

    return QuoteCheck(
        LocatedQuote(
            start_line=first_line,
            end_line=last_line + 1,
            matched_text="".join(lines[first_line : last_line + 1]).strip(),
        ),
        "",
    )


def truncate_quote(quote: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """超长引文截断到 limit，并标记截断。"""
    if len(quote) <= limit:
        return quote
    return quote[:limit] + "…"


class EvidenceStats(BaseModel):
    total: int = 0
    located: int = 0
    unlocated: int = 0

    @property
    def coverage(self) -> float:
        return self.located / self.total if self.total else 1.0

    def add(self, ok: bool) -> None:
        self.total += 1
        if ok:
            self.located += 1
        else:
            self.unlocated += 1
