"""导出流水线（Phase 5）。

产出：主角色卡（内嵌 character_book）、独立世界书、两个分别对应起始点、
按起始章节过滤的世界书、时间线、导出清单与审计报告。

导出前一律经过严格校验与"内嵌/独立条目语义一致"比对；
任何一项不通过就不写文件，避免产出"看起来成功"的卡。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__, config as config_module
from ..extract.schema import EventRecord, FactRecord, RelationRecord, SourceRef
from ..resolve.entities import CanonicalEntity
from ..tavern import (
    CardV2,
    WorldbookFile,
    dumps,
    validate_card,
    validate_no_secrets,
    validate_parity,
    validate_worldbook,
)
from ..timeline.build import TimelineEvent
from ..timeline.worldbible import PlannedEntry, summarize_plan
from .builder import (
    ChapterDigest,
    Greetings,
    build_core_rules_entry,
    build_exports,
    build_greetings,
    build_plot_entry,
    chapter_label,
)

CARD_NAME = "world_simulator_v2.json"
WORLDBOOK_NAME = "worldbook_standalone.json"
WORLDBOOK_BEGINNING = "worldbook_start_beginning.json"
WORLDBOOK_AFTER_END = "worldbook_start_after_ending.json"
TIMELINE_NAME = "timeline.json"
MANIFEST_NAME = "export_manifest.json"
AUDIT_NAME = "audit.md"

#: 严格起始点卡与它的世界书、状态快照。`{n}` 是 1 基章节号。
STRICT_CARD_TMPL = "card_start_chapter_{n}.json"
STRICT_BOOK_TMPL = "worldbook_start_chapter_{n}.json"
START_STATE_TMPL = "start_state_chapter_{n}.json"


class ExportError(RuntimeError):
    """导出阶段的致命错误。运行到这一步说明上游数据有问题，不能产出半成品。"""


#: 卷次记号与分隔符，从公共前缀里剥掉。
_VOLUME_MARKS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVXivx0123456789 "

def derive_book_title(filenames: list[str], *, fallback: str = "novel-to-tavern") -> str:
    """从来源文件名推断书名。

    多卷本的公共前缀才是书名：`天之炽Ⅰ：红龙的归来` + `天之炽Ⅱ：女武神1`
    → `天之炽`。取不到就退回配置里的项目名，不硬猜。
    """
    stems = [Path(name).stem for name in filenames if name]
    if not stems:
        return fallback
    prefix = stems[0]
    for stem in stems[1:]:
        limit = min(len(prefix), len(stem))
        cut = 0
        while cut < limit and prefix[cut] == stem[cut]:
            cut += 1
        prefix = prefix[:cut]
    cleaned = prefix.rstrip(_VOLUME_MARKS).rstrip("：:·-—_ ")
    return cleaned or fallback


def _read_json(path: Path):
    if not path.is_file():
        raise ExportError(f"缺少上游产物：{path}，请先跑 timeline。")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _collect_digests(run_dir: Path) -> list[ChapterDigest]:
    """从抽取结果里取每章摘要，用来生成剧情主线与开场白。"""
    directory = run_dir / "extraction"
    by_chapter: dict[int, ChapterDigest] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        index = data.get("chapter_index")
        if index is None or index in by_chapter:
            continue
        by_chapter[index] = ChapterDigest(
            chapter_index=index,
            label=f"第{index + 1}章",
            summary=data.get("summary", ""),
            title=data.get("chapter_title", ""),
        )
    return [by_chapter[k] for k in sorted(by_chapter)]


def _assemble_entries(
    plan: list[PlannedEntry],
    digests: list[ChapterDigest],
    *,
    upto_chapter: int | None = None,
    strict_label: str = "",
    include_plot: bool = True,
) -> list[PlannedEntry]:
    """核心规则 + 规划条目 + 剧情主线。顺序决定插入次序。

    `include_plot=False` 用于严格起始点路径 —— 那里剧情主线已经由
    `startpoint.plan_strict` 放进 `plan` 里了，不能重复添加。
    """
    always_on = [e for e in plan if e.always_on]
    triggered = [e for e in plan if not e.always_on]

    entries: list[PlannedEntry] = [build_core_rules_entry(strict_start=strict_label)]
    for entry in always_on:
        if entry.entry_id != "wb_core_rules":
            entries.append(entry)

    if include_plot:
        plot = build_plot_entry(digests, upto_chapter=upto_chapter)
        if plot is not None:
            entries.append(plot)
    entries.extend(triggered)
    return entries


def export(
    run_dir: str | Path,
    config: config_module.Config,
    *,
    start_chapter: int | None = None,
) -> dict:
    """导出。

    `start_chapter`（**0 基**）非空时，除了默认产物，还会另外产出**严格起始点**的一整套：
    起点之后的事实不进任何条目正文。默认产物不受影响。
    """
    run_path = Path(run_dir)
    exports_dir = run_path / "exports"
    reports_dir = run_path / "reports"

    manifest = _read_json(run_path / "manifest.json")
    book_title = derive_book_title(
        [s["filename"] for s in manifest.get("sources", [])], fallback=config.project.name
    )

    plan = [
        PlannedEntry.model_validate(item)
        for item in _read_json(run_path / "worldbook" / "plan.json")
    ]
    entities = [
        CanonicalEntity.model_validate(item)
        for item in _read_json(run_path / "canonical" / "entities.json")
    ]
    timeline = [
        TimelineEvent.model_validate(item)
        for item in _read_json(run_path / "canonical" / "timeline.json")
    ]
    digests = _collect_digests(run_path)
    if not digests:
        raise ExportError("抽取结果里没有章节摘要，无法生成剧情主线与开场白。")

    entries = _assemble_entries(plan, digests)

    try:
        greetings: Greetings = build_greetings(
            book_title=book_title, digests=digests, entities=entities, timeline=timeline
        )
    except ValueError as exc:
        raise ExportError(str(exc)) from exc

    card, worldbook = build_exports(
        book_title=book_title,
        entries=entries,
        greetings=greetings,
        tags=["世界模拟器", "小说改编", "novel-to-tavern"],
        version=__version__,
    )

    # --- 校验：不通过就不写文件 ---
    card_report = validate_card(
        card, strict=True, max_always_on=config.worldbook.max_always_on_entries
    )
    book_report = validate_worldbook(worldbook, strict=True)
    parity_report = validate_parity(card, worldbook)
    problems = [*card_report.errors, *book_report.errors, *parity_report.errors]
    if problems:
        raise ExportError("导出前校验未通过：\n  - " + "\n  - ".join(problems))

    card_text = dumps(card)
    book_text = dumps(worldbook, exclude_none=False)
    secret_report = validate_no_secrets(card_text + book_text)
    if not secret_report.ok:
        raise ExportError("导出内容中检出疑似密钥，已中止。")

    # --- 按起始点过滤的独立世界书 ---
    from ..timeline.worldbible import filter_for_start_chapter

    available_begin, blocked_begin = filter_for_start_chapter(entries, 0)
    begin_card, begin_book = build_exports(
        book_title=f"{book_title}（从开头开始）",
        entries=available_begin,
        greetings=greetings,
        tags=["世界模拟器", "从故事开头开始"],
        version=__version__,
    )
    after_card, after_book = build_exports(
        book_title=f"{book_title}（从结局之后开始）",
        entries=entries,
        greetings=greetings,
        tags=["世界模拟器", "从结局之后开始"],
        version=__version__,
    )

    # --- 严格起始点（可选）：起点之后的内容不进文件 ---
    strict_result: dict | None = None
    if start_chapter is not None:
        # 只有严格档需要逐条事实/事件/关系 —— 默认档不必因为这些文件缺失而失败。
        strict_result = _export_strict(
            run_path=run_path,
            exports_dir=exports_dir,
            config=config,
            book_title=book_title,
            start_chapter=start_chapter,
            digests=digests,
            entities=entities,
            facts=[
                FactRecord.model_validate(item)
                for item in _read_json(run_path / "canonical" / "facts.json")
            ],
            events=[
                EventRecord.model_validate(item)
                for item in _read_json(run_path / "canonical" / "events.json")
            ],
            relations=[
                RelationRecord.model_validate(item)
                for item in _read_json(run_path / "canonical" / "relations.json")
            ],
            timeline=timeline,
        )

    # --- 落盘 ---
    _write_text(exports_dir / CARD_NAME, card_text + "\n")
    _write_text(exports_dir / WORLDBOOK_NAME, book_text + "\n")
    _write_text(
        exports_dir / WORLDBOOK_BEGINNING,
        dumps(begin_book, exclude_none=False) + "\n",
    )
    _write_text(
        exports_dir / WORLDBOOK_AFTER_END,
        dumps(after_book, exclude_none=False) + "\n",
    )
    _write_text(
        exports_dir / TIMELINE_NAME,
        json.dumps([e.model_dump(mode="json") for e in timeline], ensure_ascii=False, indent=2) + "\n",
    )

    stats = summarize_plan(entries)
    export_manifest = {
        "schema_version": 1,
        "project_id": config.project.name,
        "run_id": run_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator_version": __version__,
        "sources": [
            {"source_id": s["source_id"], "sha256": s["sha256"], "filename": s["filename"]}
            for s in manifest.get("sources", [])
        ],
        "config_fingerprint": manifest.get("config_fingerprint", ""),
        "character_card_spec": "chara_card_v2",
        "prompt_versions": _prompt_versions(run_path),
        "entry_counts": {
            "main_card_entries": len(card.data.character_book.entries),
            "standalone_entries": len(worldbook.entries),
            "blocked_for_beginning": len(blocked_begin),
        },
        "token_estimate": stats,
        "outputs": [
            CARD_NAME,
            WORLDBOOK_NAME,
            WORLDBOOK_BEGINNING,
            WORLDBOOK_AFTER_END,
            TIMELINE_NAME,
        ],
        "validation": {
            "card_errors": card_report.errors,
            "worldbook_errors": book_report.errors,
            "parity_errors": parity_report.errors,
            "card_warnings": card_report.warnings,
        },
        "metrics": {
            **_evidence_stats(run_path),
            "quote_location_success_rate_meaning": (
                "引文在原文里逐字定位成功的比例。**这是来源定位指标，"
                "不是事实正确率** —— 引文存在不等于主张被正确解读或归属。"
            ),
            "semantic_support": _semantic_metrics(run_path),
        },
        "note": "不包含任何 API 凭据。token 为粗估，非具体分词器计数。",
    }

    if strict_result is not None:
        strict_plan = strict_result["plan"]
        strict_state = strict_result["state"]
        export_manifest["strict_start_point"] = {
            "enabled": True,
            "chapter_index": strict_state.start_chapter_index,
            "chapter_label": strict_state.start_chapter_label,
            "guarantee": "起始点之后的事实不写入任何条目正文（结构性，非提示词约束）",
            "facts_included": strict_plan.facts_included,
            "facts_excluded": strict_plan.facts_excluded,
            "events_included": strict_plan.events_included,
            "events_excluded": strict_plan.events_total - strict_plan.events_included,
            "entries_dropped": strict_state.entries_dropped,
            "entries_truncated": strict_state.entries_truncated,
            "files": strict_result["files"],
        }
        export_manifest["outputs"].extend(strict_result["files"])
    else:
        export_manifest["strict_start_point"] = {
            "enabled": False,
            "note": "未指定 --start-chapter。主卡为「尽力而为」档，见 README 的剧透防护说明。",
        }
    _write_text(
        exports_dir / MANIFEST_NAME,
        json.dumps(export_manifest, ensure_ascii=False, indent=2) + "\n",
    )

    audit = _render_audit(
        run_path,
        book_title=book_title,
        card=card,
        worldbook=worldbook,
        begin_card=begin_card,
        after_card=after_card,
        entries=entries,
        blocked_begin=blocked_begin,
        card_report=card_report,
        book_report=book_report,
        parity_report=parity_report,
        stats=stats,
        digests=digests,
        timeline=timeline,
        entities=entities,
        strict_result=strict_result,
    )
    _write_text(reports_dir / AUDIT_NAME, audit)

    return {
        "card": card,
        "worldbook": worldbook,
        "entries": entries,
        "blocked_begin": blocked_begin,
        "stats": stats,
        "manifest": export_manifest,
        "greetings": greetings,
        "strict": strict_result,
    }


def _export_strict(
    *,
    run_path: Path,
    exports_dir: Path,
    config: config_module.Config,
    book_title: str,
    start_chapter: int,
    digests: list[ChapterDigest],
    entities: list[CanonicalEntity],
    facts: list[FactRecord],
    events: list[EventRecord],
    relations: list[RelationRecord],
    timeline: list[TimelineEvent],
) -> dict:
    """产出一整套**严格起始点**产物。

    与默认卡的区别只有一条，但是关键的一条：**起始点之后的事实不写进条目正文**。
    模型读不到不存在的东西 —— 这是结构性保证，不是提示词要求。
    """
    from .startpoint import (
        build_start_state,
        load_knowledge,
        plan_strict,
        resolve_start_point,
        write_start_state,
    )

    label = f"第 {start_chapter + 1} 章"
    for digest in digests:
        if digest.chapter_index == start_chapter:
            label = chapter_label(digest.chapter_index, digest.title)
            break

    try:
        start = resolve_start_point(
            mode="chapter",
            chapter_index=start_chapter,
            digests_chapters=[d.chapter_index for d in digests],
            chapter_label=label,
        )
    except ValueError as exc:
        raise ExportError(f"起始点无效：{exc}") from exc

    plan = plan_strict(
        entities=entities, facts=facts, events=events, digests=digests, start=start
    )
    assembled = _assemble_entries(
        plan.entries, digests, strict_label=start.chapter_label, include_plot=False
    )
    greetings = build_greetings(
        book_title=book_title,
        digests=digests,
        entities=entities,
        timeline=timeline,
        strict_label=start.chapter_label,
        strict_chapter_index=start_chapter,
    )
    card, worldbook = build_exports(
        book_title=f"{book_title}（{start.chapter_label} 起）",
        entries=assembled,
        greetings=greetings,
        tags=["世界模拟器", "严格起始点", start.chapter_label],
        version=__version__,
    )

    card_report = validate_card(
        card, strict=True, max_always_on=config.worldbook.max_always_on_entries
    )
    book_report = validate_worldbook(worldbook, strict=True)
    parity_report = validate_parity(card, worldbook)
    problems = [*card_report.errors, *book_report.errors, *parity_report.errors]
    if problems:
        raise ExportError("严格起始点导出校验未通过：\n  - " + "\n  - ".join(problems))

    card_text = dumps(card)
    book_text = dumps(worldbook, exclude_none=False)
    if not validate_no_secrets(card_text + book_text).ok:
        raise ExportError("严格起始点产物中检出疑似密钥，已中止。")

    state = build_start_state(
        start=start,
        plan=plan,
        facts=facts,
        events=events,
        relations=relations,
        knowledge=load_knowledge(run_path),
    )

    n = start_chapter + 1
    card_name = STRICT_CARD_TMPL.format(n=n)
    book_name = STRICT_BOOK_TMPL.format(n=n)
    state_name = START_STATE_TMPL.format(n=n)
    _write_text(exports_dir / card_name, card_text + "\n")
    _write_text(exports_dir / book_name, book_text + "\n")
    write_start_state(exports_dir / state_name, state)

    stats = summarize_plan(assembled)
    return {
        "start": start,
        "plan": plan,
        "state": state,
        "card": card,
        "worldbook": worldbook,
        "stats": stats,
        "files": [card_name, book_name, state_name],
        "card_report": card_report,
    }


def _evidence_stats(run_dir: Path) -> dict[str, int | float]:
    """从抽取结果汇总**证据定位**指标。

    名字要说清楚它是什么：这是 `quote_location_success_rate`
    —— 引文能不能在原文里逐字找到，**不是**事实正确率。
    """
    total = located = 0
    for path in sorted((run_dir / "extraction").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        total += int(data.get("evidence_total", 0) or 0)
        located += int(data.get("evidence_located", 0) or 0)
    return {
        "quotes_total": total,
        "quotes_located": located,
        "quote_location_success_rate": round(located / total, 6) if total else 0.0,
    }


def _semantic_metrics(run_dir: Path) -> dict[str, object]:
    """语义支持校验的指标。**没跑过就如实写未执行**，不写成 0 分。"""
    from ..verify import load_verdicts

    verdicts = load_verdicts(run_dir)
    if verdicts is None:
        return {
            "executed": False,
            "note": "未执行 n2t verify —— 本次只做了证据定位，没有做语义支持判断",
        }
    return {
        "executed": True,
        "verifier": verdicts.verifier,
        "prompt_version": verdicts.prompt_version,
        "facts_checked": verdicts.facts_checked,
        "facts_total": verdicts.facts_total,
        "entailed": verdicts.counts.get("entailed", 0),
        "partially_supported": verdicts.counts.get("partially_supported", 0),
        "contradicted": verdicts.counts.get("contradicted", 0),
        "insufficient_evidence": verdicts.counts.get("insufficient_evidence", 0),
        "semantic_entailed_rate": round(verdicts.passed_rate, 6),
        "excluded_fact_count": len(verdicts.excluded_fact_ids),
        "note": "这是模型判定，不是人工审校；且只覆盖已校验的那部分事实",
    }


def _prompt_versions(run_dir: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted((run_dir / "extraction").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("prompt_version")
        provider = data.get("provider")
        if version:
            versions[f"extract:{provider}"] = version
    return versions


def _render_audit(
    run_dir: Path,
    *,
    book_title: str,
    card: CardV2,
    worldbook: WorldbookFile,
    begin_card: CardV2,
    after_card: CardV2,
    entries: list[PlannedEntry],
    blocked_begin: list[PlannedEntry],
    card_report,
    book_report,
    parity_report,
    stats: dict,
    digests: list[ChapterDigest],
    timeline: list[TimelineEvent],
    entities: list[CanonicalEntity],
    strict_result: dict | None = None,
) -> str:
    from ..timeline.worldbible import estimate_tokens

    refs: list[SourceRef] = [r for e in entries for r in e.source_refs]
    with_refs = sum(1 for e in entries if e.source_refs)
    characters = [e for e in entities if e.kind == "character"]

    evidence = _evidence_stats(run_dir)
    semantic = _semantic_metrics(run_dir)
    if semantic.get("executed"):
        semantic_cell = (
            f"{semantic['entailed']} / {semantic['facts_checked']} = "
            f"{semantic['semantic_entailed_rate']:.1%} 判为 entailed"
        )
    else:
        semantic_cell = "**未执行**"
    review_failures = len(_read_json(run_dir / "canonical" / "facts.json")) and sum(
        1
        for f in _read_json(run_dir / "canonical" / "facts.json")
        if f.get("review_status") == "needs_review"
    )

    lines = [
        "# 导出审计报告",
        "",
        f"- run_id：`{run_dir.name}`",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- 角色卡名称：{book_title}",
        f"- 目标格式：`chara_card_v2` / `2.0`（SillyTavern 1.19.0 源码核对，Tavo 未实测）",
        "",
        "## 产物",
        "",
        "| 文件 | 内容 | 条目数 |",
        "|---|---|---|",
        f"| exports/{CARD_NAME} | 主角色卡（内嵌 character_book） | {len(card.data.character_book.entries)} |",
        f"| exports/{WORLDBOOK_NAME} | 独立世界书（含全部条目） | {len(worldbook.entries)} |",
        f"| exports/{WORLDBOOK_BEGINNING} | 独立世界书（**已屏蔽全书剧情记录**） | {len(begin_card.data.character_book.entries)} |",
        f"| exports/{WORLDBOOK_AFTER_END} | 独立世界书（从结局之后开始，全部内容） | {len(after_card.data.character_book.entries)} |",
        f"| exports/{TIMELINE_NAME} | 时间线 | {len(timeline)} 个事件 |",
        f"| exports/{MANIFEST_NAME} | 导出清单 | — |",
        "",
        "## 指标口径（先读这一节）",
        "",
        "| 指标 | 数值 | 它说明了什么 | 它**不**说明什么 |",
        "|---|---|---|---|",
        f"| 引文逐字定位率 | {evidence['quotes_located']} / {evidence['quotes_total']} = "
        f"{evidence['quote_location_success_rate']:.2%} | 引文**逐字存在于原文**，行号是程序算的 "
        "| 事实被**正确解读/归属**，也没有说明抽取有没有漏 |",
        f"| 语义支持校验 | {semantic_cell} | 引文**支持**该主张 | "
        "见 `semantic_report.md`；未执行时这一列是空的 |",
        "",
        f"- 待人工复核（引文定位失败）：{review_failures} 条 —— 这**不是**「已人工审校」",
        "",
        "> 「引文 100% 定位」只证明引文在原文里存在。归属错误、漏掉否定、"
        "把角色信念当成客观事实，都不会被这一层发现。",
        "",
        "## 来源覆盖",
        "",
        f"- 章节摘要：{len(digests)} 章",
        f"- 世界书条目：{len(entries)}",
        f"- 带来源引用的条目：{with_refs} / {len(entries)}",
        f"- 条目携带的引文总数：{len(refs)}",
        f"- 实体：{len(entities)}（其中人物 {len(characters)}）",
        f"- 其中生成世界书条目的实体：{sum(1 for e in entries if e.entry_id.startswith('wb_entity_'))}"
        f"（**一条 canon 事实都没有的实体不生成条目**，见 timeline_report.md 的跳过名单）",
        f"- 时间线事件：{len(timeline)}",
        "",
        "## 校验结果",
        "",
        f"- 角色卡结构校验：{'通过' if card_report.ok else '**未通过**'}",
        f"- 独立世界书校验：{'通过' if book_report.ok else '**未通过**'}",
        f"- 内嵌/独立条目一致性：{'通过' if parity_report.ok else '**未通过**'}",
        f"- 密钥扫描：通过",
        f"- 警告 {len(card_report.warnings)} 条：",
    ]
    for warning in card_report.warnings[:20]:
        lines.append(f"  - {warning}")

    lines += [
        "",
        "## Token 预算（粗估）",
        "",
        f"- 常驻条目：{stats['always_on_entries']} 个，约 {stats['always_on_tokens']} token",
        f"- 触发条目：{stats['triggered_entries']} 个",
        f"- 全部条目合计：约 {stats['total_tokens']} token",
        f"- 按起始点从开头开始时屏蔽：{len(blocked_begin)} 个条目",
        "",
        "> 估算方式：CJK 约 1 字 1 token，其余约 4 字符 1 token。**不是**任何具体分词器的真实计数。",
        "",
        "## 用户可选的两个起点",
        "",
        f"1. **从故事开头开始** —— 第 1 章之前，屏蔽 {len(blocked_begin)} 条"
        "（全书剧情记录；人物与地点条目保留，见下方限制说明）。",
        f"2. **从故事最终结局之后开始** —— 第 {len(digests)} 章之后，全部内容可用。",
        "",
        "两个起点都能选：卡片的开场白会先让用户挑一个，"
        "并额外提供两条 alternate_greetings 直接进入对应场景。",
        "",
        "> ⚠️ **这一档是「尽力而为」，不是硬保证。** 人物与地点条目聚合了全书事实，"
        "剧情主线条目也在卡里（触发式）。剧透防护靠的是核心规则的时间纪律，"
        "不是访问控制。要硬保证请用下面的严格起始点产物。",
        "",
    ]

    if strict_result is not None:
        sp = strict_result["plan"]
        state = strict_result["state"]
        files = strict_result["files"]
        lines += [
            "## 严格起始点产物（结构性无剧透）",
            "",
            f"- 起点：**{state.start_chapter_label}**（第 {state.start_chapter_index + 1} 章）",
            "- 保证方式：起点之后的事实**不写入任何条目正文** —— 模型读不到不存在的东西",
            "",
            "| 产物 | 文件 | 条目数 |",
            "|---|---|---|",
            f"| 严格起始点角色卡 | exports/{files[0]} | "
            f"{len(strict_result['card'].data.character_book.entries)} |",
            f"| 严格起始点世界书 | exports/{files[1]} | {len(strict_result['worldbook'].entries)} |",
            f"| 起始状态快照 | exports/{files[2]} | — |",
            "",
            "### 删了什么",
            "",
            f"- canon 事实：采用 {sp.facts_included} 条，隐藏 {sp.facts_excluded} 条"
            f"（共 {sp.facts_total} 条）",
            f"- 事件：采用 {sp.events_included} 个，隐藏 "
            f"{sp.events_total - sp.events_included} 个（共 {sp.events_total} 个）",
            f"- 被整条删去的条目：{state.entries_dropped} 个",
            f"- 被截断的条目：{state.entries_truncated} 个",
            f"- 生成条目的实体：{sp.entities_with_entries} / {sp.entities_total}",
            "",
        ]
        if sp.dropped:
            lines += ["被删条目（起始点之前内容不足）：", ""]
            for delta in sp.dropped[:20]:
                lines.append(f"- {delta.title}：{delta.reason}")
            if len(sp.dropped) > 20:
                lines.append(f"- …另有 {len(sp.dropped) - 20} 个，见 start_state 文件")
            lines.append("")
        truncated = [d for d in sp.truncated if d.chars_before > d.chars_after]
        if truncated:
            lines += ["被截断的代表性条目：", ""]
            for delta in sorted(truncated, key=lambda d: d.chars_before - d.chars_after, reverse=True)[:10]:
                lines.append(
                    f"- {delta.title}：{delta.chars_before} → {delta.chars_after} 字"
                    f"（删去 {delta.chars_before - delta.chars_after} 字）"
                )
            lines.append("")

    lines += [
        "## 已知限制",
        "",
        "1. **Tavo 只验证到「导入成功」这一步**（角色卡与内嵌世界书能被接受并显示）。"
        "触发命中、常驻条目是否每轮都在、剧透纪律、实际 token 占用**都还没验证**。"
        "格式依据为 SillyTavern 1.19.0 源码逐行核对。",
        "2. 事件没有绝对时间：原文未明确给出时 `occurred_at` 一律为空，不予推算。",
        "3. 知识边界由「事件参与者」推断，标注为 `present_at_event`，"
        "不等于原著明文授权。",
        "4. 角色卡含全书剧情（「剧情主线」条目，触发词已收窄为"
        "「剧情/主线/前情/剧情走向/原著剧情/故事线」）。"
        "**剧透防护靠核心规则的时间纪律**，不是靠条目隔离。"
        "人物与地点条目**聚合了全书事实**，不按出场章节切分 —— "
        "角色在世界里本来就存在，与它在故事里第几章登场是两回事；"
        "从开头开始时这些条目仍在，故不是严格的零剧透方案。",
        "5. 事实来自自动抽取，`needs_review` 的条目已被排除在条目正文之外，"
        "但仍建议人工抽查主要角色条目。",
        "",
        "> 本报告不含小说原文。",
        "",
    ]
    return "\n".join(lines)
