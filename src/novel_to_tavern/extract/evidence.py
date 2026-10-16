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

#: 引文长度**下限**（非空白字符数）。太短的引文（「剑」「他说」）在长篇里
#: 必然多处命中，定位到哪一处都说得通，等于没有来源。
#: 实测本次真实 run 的 5,746 条引文最短 5 字，所以这个下限不改动任何既有产物。
MIN_QUOTE_CHARS = 4


class LocatedQuote(BaseModel):
    start_line: int
    end_line: int
    #: 命中处的**原文行拼接**（不是模型给的原话）。保留原文是因为它保证逐字可查；
    #: 模型原话另存于 `SourceRef.quote_exact`。
    matched_text: str
    #: 这段引文在搜索窗口里出现了几次。>1 表示定位不唯一。
    match_count: int = 1


class QuoteCheck(NamedTuple):
    located: LocatedQuote | None
    reason: str
    #: 引文在原文里出现多次 —— 找到了，但**不唯一**。
    #: 「找到了」与「找对了地方」是两件事，指标上必须分开。
    ambiguous: bool = False
    match_count: int = 0


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
    if len(needle) < MIN_QUOTE_CHARS:
        return QuoteCheck(
            None,
            f"引文过短（{len(needle)} 个非空白字符 < {MIN_QUOTE_CHARS}）："
            "短串在长篇里必然多处命中，定位到哪一处都说得通，不能作为来源",
        )

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

    haystack = "".join(chars)
    position = haystack.find(needle)
    if position == -1:
        return QuoteCheck(None, "引文在原文中找不到（可能是转述或臆造）")

    # 找**全部**命中位置。只取第一处会让「同一句话在书里出现两次」静默地
    # 落到靠前的那一处 —— 而那处往往不是这条事实的出处。
    match_count = 1
    cursor = haystack.find(needle, position + 1)
    while cursor != -1:
        match_count += 1
        cursor = haystack.find(needle, cursor + 1)

    first_line = line_of[position]
    last_line = line_of[position + len(needle) - 1]
    if last_line - first_line + 1 > max_span:
        return QuoteCheck(
            None,
            f"引文横跨 {last_line - first_line + 1} 行，超过 {max_span} 行上限"
            "（这更像是概括而非引用）",
        )

    ambiguous = match_count > 1
    reason = ""
    if ambiguous:
        reason = (
            f"引文在原文中出现 {match_count} 次，已取下最靠前的一处（第 "
            f"{first_line + 1} 行）—— 定位不唯一，需人工确认是哪一处"
        )

    return QuoteCheck(
        LocatedQuote(
            start_line=first_line,
            end_line=last_line + 1,
            matched_text="".join(lines[first_line : last_line + 1]).strip(),
            match_count=match_count,
        ),
        reason,
        ambiguous,
        match_count,
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
    #: 找到了但**不唯一**的条数。它与 `located` 是包含关系：
    #: `located` 回答「能不能找到」，`ambiguous` 回答「是不是只有一处」。
    ambiguous: int = 0

    @property
    def coverage(self) -> float:
        return self.located / self.total if self.total else 1.0

    @property
    def unique_rate(self) -> float:
        """定位**唯一**的比例。分母是已定位的条数 —— 找不到的另有 `coverage` 管。"""
        if not self.located:
            return 0.0
        return (self.located - self.ambiguous) / self.located

    def add(self, ok: bool, *, ambiguous: bool = False) -> None:
        self.total += 1
        if ok:
            self.located += 1
            if ambiguous:
                self.ambiguous += 1
        else:
            self.unlocated += 1
