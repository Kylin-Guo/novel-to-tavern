"""触发模拟与上下文预算估算。

**为什么需要这个。** 世界书条目的触发词是「子串命中」—— 一行对白里出现
「西泽尔」就会把该条目整段灌进上下文。触发词写得松，一句话可能同时命中
上百条：本项目实测过一次，一句话提到主角命中 **117 条 ≈ 6 万 token**，
上下文直接被冲爆。这种事在静态校验里看不出来（JSON 完全合法），
只有模拟一遍才发现。

本模块按 SillyTavern 的匹配语义（`caseSensitive` / `matchWholeWords`，
默认都是关）做一次**近似**模拟，用来：

1. 量出最坏情况的上下文占用；
2. 找出过松的触发词（单个键、被大量条目共用的键、过短的键）。

**这是估算，不是客户端的真实行为。** 各客户端的扫描深度、递归、
预算裁剪都不一样，本模块不假装知道那些。所有数字都标注为粗估。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..timeline.worldbible import PlannedEntry, estimate_tokens

#: 短于这个长度的键就很可疑了：「王」「上校」「红」这种词在对白里到处都是。
SUSPICIOUS_KEY_LENGTH = 2

#: 被这么多条目共用的键，命中一次会连带拉起一大片。
SHARED_KEY_THRESHOLD = 5


class MatchedEntry(BaseModel):
    entry_id: str
    title: str
    category: str
    matched_keys: list[str] = Field(default_factory=list)
    always_on: bool = False
    tokens: int = 0


class TriggerProbe(BaseModel):
    """一句探测文本命中了什么。"""

    message: str
    matched: list[MatchedEntry] = Field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(m.tokens for m in self.matched)

    @property
    def triggered_count(self) -> int:
        return sum(1 for m in self.matched if not m.always_on)

    @property
    def total_chars(self) -> int:
        return 0  # 由调用方填；保留属性以便统一接口


class KeyRisk(BaseModel):
    key: str
    entry_count: int
    reason: str


class TriggerBudgetReport(BaseModel):
    """触发词与预算的体检结果。**全是粗估。**"""

    entry_total: int = 0
    always_on_entries: int = 0
    always_on_tokens: int = 0
    total_tokens: int = 0
    triggered_entries: int = 0
    #: 最坏情况：单个条目键集合的「闭包」里 token 最多的一条。
    worst_entry_id: str = ""
    worst_entry_title: str = ""
    worst_case_tokens: int = 0
    worst_case_entries: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    chars_by_category: dict[str, int] = Field(default_factory=dict)
    tokens_by_category: dict[str, int] = Field(default_factory=dict)
    key_risks: list[KeyRisk] = Field(default_factory=list)
    single_key_entries: list[str] = Field(default_factory=list)
    probes: list[TriggerProbe] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def key_matches(key: str, text: str, *, case_sensitive: bool = False) -> bool:
    """近似 ST 的子串匹配。默认大小写不敏感。"""
    if not key or not text:
        return False
    if case_sensitive:
        return key in text
    return key.casefold() in text.casefold()


def matched_keys(keys: list[str], text: str) -> list[str]:
    return [k for k in keys if key_matches(k, text)]


def simulate(entries: list[PlannedEntry], message: str) -> TriggerProbe:
    """模拟一句消息会拉起哪些条目。

    常驻条目（`always_on`）**总是**在上下文里，与消息内容无关 ——
    这正是要量出常驻预算的原因。
    """
    matched: list[MatchedEntry] = []
    for entry in entries:
        if entry.always_on:
            matched.append(
                MatchedEntry(
                    entry_id=entry.entry_id,
                    title=entry.title,
                    category=entry.category,
                    matched_keys=[],
                    always_on=True,
                    tokens=entry.estimated_tokens,
                )
            )
            continue
        hits = matched_keys(list(entry.keys), message)
        if not hits:
            continue
        matched.append(
            MatchedEntry(
                entry_id=entry.entry_id,
                title=entry.title,
                category=entry.category,
                matched_keys=hits,
                always_on=False,
                tokens=entry.estimated_tokens,
            )
        )
    return TriggerProbe(message=message, matched=matched)


def _worst_case(entries: list[PlannedEntry]) -> tuple[PlannedEntry | None, int, int]:
    """最坏情况：挑一个条目，把它命中的键**同时**抄进一句话，看拉起来多少。

    近似做法：一条条目的键集合的「连带闭包」= 所有与它**共享任一键**的条目
    加上常驻条目。共享键越多，一句话带出的上下文越多。
    """
    triggerable = [e for e in entries if not e.always_on]
    always_on = [e for e in entries if e.always_on]
    if not triggerable:
        return None, sum(e.estimated_tokens for e in always_on), len(always_on)

    owners: dict[str, int] = {}
    for entry in triggerable:
        for key in entry.keys:
            owners[key] = owners.get(key, 0) + 1

    best: PlannedEntry | None = None
    best_tokens = -1
    best_count = 0
    always_tokens = sum(e.estimated_tokens for e in always_on)

    for entry in triggerable:
        closure = {entry.entry_id: entry}
        for key in entry.keys:
            if owners.get(key, 0) < 2:
                continue
            for other in triggerable:
                if key in other.keys:
                    closure[other.entry_id] = other
        tokens = always_tokens + sum(e.estimated_tokens for e in closure.values())
        if tokens > best_tokens:
            best, best_tokens, best_count = entry, tokens, len(closure) + len(always_on)
    return best, best_tokens, best_count


def audit_triggers(
    entries: list[PlannedEntry], *, probes: list[str] | None = None
) -> TriggerBudgetReport:
    """体检一遍条目计划：预算、最坏情况、过松的触发词。"""
    always_on = [e for e in entries if e.always_on]
    triggered = [e for e in entries if not e.always_on]

    by_category: dict[str, int] = {}
    chars_by_category: dict[str, int] = {}
    tokens_by_category: dict[str, int] = {}
    for entry in entries:
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
        chars_by_category[entry.category] = (
            chars_by_category.get(entry.category, 0) + len(entry.content_runtime)
        )
        tokens_by_category[entry.category] = (
            tokens_by_category.get(entry.category, 0) + entry.estimated_tokens
        )

    owners: dict[str, list[str]] = {}
    for entry in triggered:
        for key in entry.keys:
            owners.setdefault(key, []).append(entry.title)

    risks: list[KeyRisk] = []
    for key, titles in owners.items():
        if len(key) < SUSPICIOUS_KEY_LENGTH:
            risks.append(
                KeyRisk(key=key, entry_count=len(titles), reason="键太短，日常对白里几乎必然出现")
            )
        elif len(titles) >= SHARED_KEY_THRESHOLD:
            risks.append(
                KeyRisk(
                    key=key,
                    entry_count=len(titles),
                    reason=f"被 {len(titles)} 个条目共用，命中一次会一起拉起",
                )
            )
    risks.sort(key=lambda r: (-r.entry_count, r.key))

    worst_entry, worst_tokens, worst_count = _worst_case(entries)

    return TriggerBudgetReport(
        entry_total=len(entries),
        always_on_entries=len(always_on),
        always_on_tokens=sum(e.estimated_tokens for e in always_on),
        total_tokens=sum(e.estimated_tokens for e in entries),
        triggered_entries=len(triggered),
        worst_entry_id=worst_entry.entry_id if worst_entry else "",
        worst_entry_title=worst_entry.title if worst_entry else "",
        worst_case_tokens=worst_tokens,
        worst_case_entries=worst_count,
        by_category=by_category,
        chars_by_category=chars_by_category,
        tokens_by_category=tokens_by_category,
        key_risks=risks[:40],
        single_key_entries=[
            e.title for e in triggered if len(e.keys) == 1
        ][:60],
        probes=[simulate(entries, message) for message in (probes or [])],
        notes=[
            "全部 token 都是**粗估**（CJK 约 1 字 1 token，其余约 4 字符 1 token），"
            "不是任何具体分词器的真实计数。",
            "触发模拟按子串匹配做**近似**，未考虑客户端自己的扫描深度、递归与预算裁剪。",
            "「最坏情况」是构造出来的：把同一条目的多个键同时写进一句话。"
            "真实对白很少这么巧，但这是设计触发词时该看的数字。",
            "常驻条目与消息内容无关，每一轮都在上下文里 —— 优化常驻预算是唯一"
            "确定有效的省额度手段。",
        ],
    )


def count_chars(entries: list[PlannedEntry]) -> int:
    return sum(len(e.content_runtime) for e in entries)
