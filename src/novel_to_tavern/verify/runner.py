"""语义支持校验的执行器。

流程：canon 事实 → 提示词 → 引擎 → 解析 → `verification/semantic.json` + 报告。

**这不是证据定位的替代品。** 证据定位问「引文在不在原文里」，
本层问「引文支不支持这条主张」。两者都过，才谈得上「这条事实站得住」。

失败的调用**不静默跳过**：单条解析失败记为 `insufficient_evidence` 并写明原因，
整体不可用时直接报错，不产出一份看起来通过的假报告。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..extract.runner import parse_json_response
from ..extract.schema import FactRecord
from ..llm.provider import Provider, ProviderError
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .schema import (
    HIGH_IMPACT_MARKERS,
    HIGH_IMPACT_PREDICATES,
    PROBLEM_VERDICTS,
    RawSemanticVerdict,
    SemanticReport,
    SemanticVerdict,
)

VERIFY_DIR = "verification"
SEMANTIC_NAME = "semantic.json"
REPORT_NAME = "semantic_report.md"


class VerificationError(RuntimeError):
    """语义校验阶段的致命错误。"""


def is_high_impact(fact: FactRecord) -> bool:
    """这条事实错了代价大不大。

    谓词是主判据（身份、生死、秘密、关系、能力、立场）；
    谓词没分类时退回取值里的标志词。
    """
    if fact.predicate in HIGH_IMPACT_PREDICATES:
        return True
    return any(marker in fact.value for marker in HIGH_IMPACT_MARKERS)


def high_impact_facts(facts: list[FactRecord]) -> list[FactRecord]:
    return [f for f in facts if is_high_impact(f)]


def _load_facts(run_dir: Path) -> list[FactRecord]:
    path = run_dir / "canonical" / "facts.json"
    if not path.is_file():
        raise VerificationError(f"缺少上游产物：{path}，请先跑 resolve。")
    return [FactRecord.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _quote_of(fact: FactRecord) -> str:
    return " ".join(ref.quote for ref in fact.source_refs if ref.quote).strip()


def _verify_one(
    fact: FactRecord, provider: Provider, *, model_hint: str
) -> SemanticVerdict:
    quote = _quote_of(fact)
    base = {
        "fact_id": fact.fact_id,
        "chunk_id": fact.chunk_id,
        "chapter_index": fact.chapter_index,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "value": fact.value,
        "quote": quote,
        "high_impact": is_high_impact(fact),
    }
    if not quote:
        return SemanticVerdict(
            **base,
            verdict="insufficient_evidence",
            reason="这条事实没有任何引文可供核对 —— 无法判断支持关系",
            confidence=1.0,
            verifier=model_hint,
        )

    prompt = build_user_prompt(
        subject=fact.subject,
        predicate=fact.predicate,
        value=fact.value,
        quote=quote,
        chapter_label=fact.chapter_label,
    )
    try:
        completion = provider.complete(
            chunk_id=f"verify_{fact.fact_id}", system_prompt=SYSTEM_PROMPT, user_prompt=prompt
        )
    except ProviderError as exc:
        return SemanticVerdict(
            **base,
            verdict="insufficient_evidence",
            reason=f"校验调用失败：{exc}",
            confidence=0.0,
            verifier=model_hint,
        )

    try:
        raw = RawSemanticVerdict.model_validate(parse_json_response(completion.text))
    except (ValueError, ValidationError) as exc:
        return SemanticVerdict(
            **base,
            verdict="insufficient_evidence",
            reason=f"校验响应无法解析：{exc}",
            confidence=0.0,
            verifier=model_hint,
        )

    return SemanticVerdict(
        **base,
        verdict=raw.verdict,
        reason=raw.reason,
        confidence=max(0.0, min(1.0, raw.confidence)),
        verifier=f"{provider.name}:{completion.model}" if completion.model else provider.name,
    )


def run_verification(
    run_dir: str | Path,
    provider: Provider,
    *,
    sample: int | None = None,
    only_high_impact: bool = False,
    log=None,
) -> SemanticReport:
    """对 canon 事实做语义支持校验。

    `sample` 只影响**校验多少条**，不影响结果的含义 ——
    报告里会写明抽了多少、总数多少，不把抽样说成全量。
    """
    run_path = Path(run_dir)
    facts = [f for f in _load_facts(run_path) if f.review_status == "accepted"]
    targets = [f for f in facts if f.fact_type == "canon_fact"]
    if only_high_impact:
        targets = high_impact_facts(targets)
    if sample is not None:
        targets = targets[:sample]

    verdicts = [_verify_one(fact, provider, model_hint=provider.name) for fact in targets]

    # **安全闸**：一条都调不通时直接失败，不要写出一份「全部有问题」的报告。
    # 下游会根据这份报告把事实排出条目正文 —— 全面失败的校验结果
    # 会把世界书清空，而且是静默的。宁可在这里报错。
    call_failures = [v for v in verdicts if "校验调用失败" in v.reason]
    if targets and len(call_failures) == len(targets):
        first = call_failures[0].reason
        raise VerificationError(
            f"校验引擎 {provider.name!r} 一条都没调通，已中止而不是写出一份"
            f"「全部有问题」的报告（那会把世界书清空）。首个错误：{first}"
        )

    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.verdict] = counts.get(verdict.verdict, 0) + 1

    excluded = sorted(v.fact_id for v in verdicts if v.verdict in PROBLEM_VERDICTS)
    high_total = len(high_impact_facts(facts))
    high_checked = sum(1 for v in verdicts if v.high_impact)

    notes = [
        "本层只回答「引文支不支持这条主张」，**不替代**证据定位（引文是否逐字存在于原文）。",
        "两者都过才谈得上站得住；引文 100% 定位**不等于**事实 100% 正确。",
        "被判为 contradicted / insufficient_evidence 的事实会被排除在条目正文之外，"
        "但**保留**在 canonical 数据里供追溯。",
        "这是**模型判定**，不是人工审校，本身也会有错。",
    ]
    if sample is not None:
        notes.append(
            f"本次只校验了 {len(targets)} 条（抽样），全量 canon 事实 {len(facts)} 条 ——"
            "不要把抽样结果说成全量结论。"
        )
    if provider.name == "file":
        notes.append(
            "本次用的是 file 引擎：结果来自预生成响应，不是实时 API 调用。"
        )

    report = SemanticReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        verifier=provider.name,
        prompt_version=PROMPT_VERSION,
        facts_total=len(facts),
        facts_checked=len(verdicts),
        counts=counts,
        high_impact_total=high_total,
        high_impact_checked=high_checked,
        excluded_fact_ids=excluded,
        verdicts=verdicts,
        notes=notes,
    )

    out_dir = run_path / VERIFY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / SEMANTIC_NAME).write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_path / "reports").mkdir(parents=True, exist_ok=True)
    (run_path / "reports" / REPORT_NAME).write_text(
        render_report(report, run_dir=run_path), encoding="utf-8"
    )
    if log is not None:
        log.info("verify 完成：%d 条，其中有问题 %d 条", len(verdicts), len(excluded))
    return report


def load_verdicts(run_dir: str | Path) -> SemanticReport | None:
    """读回已有的校验结果。没有就返回 `None` —— 不要伪造一份空的。"""
    path = Path(run_dir) / VERIFY_DIR / SEMANTIC_NAME
    if not path.is_file():
        return None
    return SemanticReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


def render_report(report: SemanticReport, *, run_dir: Path) -> str:
    lines = [
        "# 语义支持校验报告",
        "",
        f"- run_id：`{run_dir.name}`",
        f"- 生成时间：{report.generated_at}",
        f"- 校验引擎：`{report.verifier}`",
        f"- 提示词版本：`{report.prompt_version}`",
        "",
        "## 这一层检查什么",
        "",
        "| 检查 | 回答的问题 | 在哪一层 |",
        "|---|---|---|",
        "| 证据定位 | 引文**逐字存在**于原文吗？行号对不对？ | Phase 2 |",
        "| 语义支持 | 引文**支持**这条主张吗？ | 本层 |",
        "",
        "> 引文可能存在却说明不了那条主张：归属给错了人、漏掉否定、"
        "把角色的信念当成客观事实、只支持了复合事实的一部分。",
        "> 所以「引文 100% 定位」**不是**「事实 100% 正确」。",
        "",
        "## 结果",
        "",
        f"- canon 事实总数：{report.facts_total}",
        f"- 本次校验：**{report.facts_checked}** 条",
        f"- 高风险事实：{report.high_impact_total} 条，其中已校验 {report.high_impact_checked} 条",
        "",
        "| 判定 | 条数 | 含义 |",
        "|---|---|---|",
    ]
    meaning = {
        "entailed": "引文足以支持该主张",
        "partially_supported": "只支持了一部分（限定被丢掉、语气被抬高、复合事实缺一半）",
        "contradicted": "**引文与主张冲突**（含漏掉否定）",
        "insufficient_evidence": "引文与主张无关，或信息不足",
    }
    for verdict in ("entailed", "partially_supported", "contradicted", "insufficient_evidence"):
        count = report.counts.get(verdict, 0)
        if count or verdict in ("entailed", "contradicted"):
            lines.append(f"| `{verdict}` | {count} | {meaning[verdict]} |")

    if report.facts_checked:
        lines += [
            "",
            f"- `entailed` 占比：{report.counts.get('entailed', 0)} / {report.facts_checked}"
            f" = {report.passed_rate:.1%}",
        ]

    if report.excluded_fact_ids:
        lines += [
            "",
            "## 被排除的事实",
            "",
            f"{len(report.excluded_fact_ids)} 条判定为有问题，已排除在条目正文之外"
            "（仍保留在 canonical 数据里）。前 30 条：",
            "",
            "| 事实 | 主语 | 谓词 | 取值 | 判定 | 理由 |",
            "|---|---|---|---|---|---|",
        ]
        problem = [v for v in report.verdicts if v.verdict in PROBLEM_VERDICTS]
        for verdict in problem[:30]:
            value = verdict.value.replace("|", "\\|")[:40]
            reason = verdict.reason.replace("|", "\\|")[:60]
            lines.append(
                f"| `{verdict.fact_id}` | {verdict.subject} | {verdict.predicate} "
                f"| {value} | `{verdict.verdict}` | {reason} |"
            )

    if report.high_impact_checked:
        lines += [
            "",
            "## 高风险事实",
            "",
            "身份、生死、秘密、关系、能力上限、立场这几类错了代价最大，"
            "**即使引文定位成功也建议人工过一遍**。",
            "",
        ]
        flagged = [v for v in report.verdicts if v.high_impact]
        by_verdict: dict[str, int] = {}
        for verdict in flagged:
            by_verdict[verdict.verdict] = by_verdict.get(verdict.verdict, 0) + 1
        for key in sorted(by_verdict, key=lambda k: -by_verdict[k]):
            lines.append(f"- `{key}`：{by_verdict[key]} 条")

    lines += ["", "## 口径", ""]
    for note in report.notes:
        lines.append(f"- {note}")

    lines += ["", "> 本报告不含小说原文。", ""]
    return "\n".join(lines)
