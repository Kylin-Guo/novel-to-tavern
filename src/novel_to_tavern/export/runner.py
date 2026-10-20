"""导出流水线（Phase 5）。

产出：主角色卡（内嵌 character_book）、独立世界书、两个分别对应起始点、
按起始章节过滤的世界书、时间线、导出清单与审计报告。

导出前一律经过严格校验与"内嵌/独立条目语义一致"比对；
任何一项不通过就不写文件，避免产出"看起来成功"的卡。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import TARGET_CLIENT, __version__, config as config_module
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
from ..tavern.triggers import audit_triggers
from ..timeline.worldbible import PlannedEntry, summarize_plan
from .playmode import mode_block, mode_notice
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
BUDGET_NAME = "worldbook_budget.md"

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


def _describe_outputs(names: list[str], exports_dir: Path) -> list[dict]:
    """产物清单：文件名 + sha256 + 字节数 + 是否真的落盘。

    早先只记文件名。那意味着拿到一份 `export_manifest.json` 无法回答
    「我手上这张卡是不是这次生成的」—— 而这正是清单存在的理由。
    """
    described: list[dict] = []
    for name in names:
        path = exports_dir / name
        if path.is_file():
            data = path.read_bytes()
            described.append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "exists": True,
                }
            )
        else:
            # 没写出来的文件也要出现在清单里 —— 静默省略会让人以为它不存在过。
            described.append({"name": name, "sha256": "", "bytes": 0, "exists": False})
    return described


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


def _extra_entries(style_artifacts, config) -> list[PlannedEntry]:
    """旁路 Runtime 条目：风格档案（+ 受控 HTML 规范，见 render/html_policy.py）。

    它们都不进 canon，也不参与剧情主线。
    """
    extra: list[PlannedEntry] = []
    if style_artifacts is not None:
        extra.extend(style_artifacts.entries)
    return extra


def _assemble_entries(
    plan: list[PlannedEntry],
    digests: list[ChapterDigest],
    *,
    upto_chapter: int | None = None,
    strict_label: str = "",
    include_plot: bool = True,
    include_core_rules: bool = True,
    extra_entries: list[PlannedEntry] | None = None,
) -> list[PlannedEntry]:
    """核心规则 + 规划条目 + 剧情主线。顺序决定插入次序。

    `include_plot=False` 用于严格起始点路径 —— 那里剧情主线已经由
    `startpoint.plan_strict` 放进 `plan` 里了，不能重复添加。
    """
    always_on = [e for e in plan if e.always_on]
    triggered = [e for e in plan if not e.always_on]

    entries: list[PlannedEntry] = []
    if include_core_rules:
        entries.append(build_core_rules_entry(strict_start=strict_label))
    for entry in always_on:
        if entry.entry_id != "wb_core_rules":
            entries.append(entry)

    if include_plot:
        plot = build_plot_entry(digests, upto_chapter=upto_chapter)
        if plot is not None:
            entries.append(plot)
    entries.extend(triggered)
    # 风格 / 呈现类条目是旁路 Runtime 资料，不是 canon；排在规划条目之后。
    entries.extend(extra_entries or ())
    return entries


def export(
    run_dir: str | Path,
    config: config_module.Config,
    *,
    start_chapter: int | None = None,
    provider=None,
    log=None,
) -> dict:
    """导出。

    `start_chapter`（**0 基**）非空时，除了默认产物，还会另外产出**严格起始点**的一整套：
    起点之后的事实不进任何条目正文。默认产物不受影响。

    `config.style.enabled=true` 时这里会装配风格产物：新鲜则直接用（不需要
    凭据），缺失或过期则用 `provider` 自动蒸馏。这是「导出阶段不调 LLM」
    的唯一例外，见 docs/ARCHITECTURE.md。
    """
    run_path = Path(run_dir)
    exports_dir = run_path / "exports"
    reports_dir = run_path / "reports"

    manifest = _read_json(run_path / "manifest.json")
    book_title = derive_book_title(
        [s["filename"] for s in manifest.get("sources", [])], fallback=config.project.name
    )

    style_artifacts = None
    if config.style.enabled:
        from ..style.pipeline import ensure_style_artifacts

        style_artifacts = ensure_style_artifacts(
            run_path, config, provider, log=log
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

    extra_entries = _extra_entries(style_artifacts, config)
    entries = _assemble_entries(
        plan,
        digests,
        include_core_rules=config.worldbook.always_on_core_rules,
        extra_entries=extra_entries,
    )

    try:
        greetings: Greetings = build_greetings(
            book_title=book_title, digests=digests, entities=entities, timeline=timeline
        )
    except ValueError as exc:
        raise ExportError(str(exc)) from exc

    # 游玩模式写进卡面 —— 用户要在客户端里就能看到自己拿到的是哪一种
    play_mode = config.project.mode
    greetings.description = greetings.description + mode_notice(play_mode)
    if style_artifacts is not None:
        greetings.description += (
            "\n\n【叙事风格规范】\n" + style_artifacts.runtime_text.strip()
        )

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
            extra_entries=extra_entries,
            style_runtime_text=(
                style_artifacts.runtime_text if style_artifacts is not None else ""
            ),
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
        "provenance": _provenance(run_path),
        "entry_counts": {
            "main_card_entries": len(card.data.character_book.entries),
            "standalone_entries": len(worldbook.entries),
            "blocked_for_beginning": len(blocked_begin),
        },
        "token_estimate": stats,
        # 只列文件名等于没法核对「你手上这份是不是这次生成的」。
        # 逐个记 sha256 与字节数，且如实标注文件到底有没有落盘。
        "outputs": _describe_outputs(
            [CARD_NAME, WORLDBOOK_NAME, WORLDBOOK_BEGINNING, WORLDBOOK_AFTER_END, TIMELINE_NAME],
            exports_dir,
        ),
        "validation": {
            "card_errors": card_report.errors,
            "worldbook_errors": book_report.errors,
            "parity_errors": parity_report.errors,
            "card_warnings": card_report.warnings,
        },
        "play_mode": mode_block(play_mode),
        "style": _style_manifest_block(style_artifacts),
        "rendering": {"enabled": False},
        "metrics": {
            **_evidence_stats(run_path),
            "quote_location_success_rate_meaning": (
                "引文在原文里逐字定位成功的比例。**这是来源定位指标，"
                "不是事实正确率** —— 引文存在不等于主张被正确解读或归属。"
            ),
            "unique_quote_rate_meaning": (
                "已定位的引文中**只有一处命中**的比例。与上一个指标是两回事："
                "上一个回答「能不能找到」，这个回答「是不是只有一处」。"
                "只取首次匹配而不报歧义，会让「同一句话在书里出现两次」静默地"
                "落到靠前的那一处。"
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
        export_manifest["outputs"].extend(
            _describe_outputs(strict_result["files"], exports_dir)
        )
    else:
        export_manifest["strict_start_point"] = {
            "enabled": False,
            "guarantee": "无结构性保证 —— 全书剧情在可触发条目内，靠核心规则的时间纪律约束",
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
        config_mode=play_mode,
        style_artifacts=style_artifacts,
    )
    _write_text(reports_dir / AUDIT_NAME, audit)

    budget = audit_triggers(
        entries,
        probes=_trigger_probes(entities, digests),
    )
    _write_text(
        reports_dir / BUDGET_NAME,
        render_budget_report(
            budget,
            run_dir=run_path,
            max_always_on_tokens=config.worldbook.max_always_on_tokens,
            target_runtime_budget_tokens=config.worldbook.target_runtime_budget_tokens,
        ),
    )

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
    extra_entries: list[PlannedEntry] | None = None,
    style_runtime_text: str = "",
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

    # 风格/呈现条目里本来就不该有章节指涉；有就说明蒸馏或手工产物把剧情带进来了。
    from ..style.worldbook import StyleLeakError, check_style_no_plot_leak

    try:
        check_style_no_plot_leak(list(extra_entries or ()), start_chapter)
    except StyleLeakError as exc:
        raise ExportError(str(exc)) from exc

    assembled = _assemble_entries(
        plan.entries,
        digests,
        strict_label=start.chapter_label,
        include_plot=False,
        include_core_rules=config.worldbook.always_on_core_rules,
        extra_entries=extra_entries,
    )
    greetings = build_greetings(
        book_title=book_title,
        digests=digests,
        entities=entities,
        timeline=timeline,
        strict_label=start.chapter_label,
        strict_chapter_index=start_chapter,
    )
    if style_runtime_text:
        greetings.description += "\n\n【叙事风格规范】\n" + style_runtime_text.strip()
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


def _trigger_probes(
    entities: list[CanonicalEntity], digests: list[ChapterDigest]
) -> list[str]:
    """探测句：一句提到主角、一句提到配角、一句与故事无关的闲聊。

    这三句就能看出「一句话会不会拉起一大片」和「常驻预算有多大」。
    """
    characters = sorted(
        (e for e in entities if e.kind == "character"), key=lambda e: -e.evidence_count
    )
    probes = []
    if characters:
        probes.append(f"{characters[0].canonical_name}是谁？")
    if len(characters) > 1:
        probes.append(f"{characters[1].canonical_name}现在在哪？")
    if digests:
        probes.append("今天天气不错，我们随便聊聊吧。")
    return probes


def render_budget_report(
    budget,
    *,
    run_dir: Path,
    max_always_on_tokens: int,
    target_runtime_budget_tokens: int | None = None,
) -> str:
    lines = [
        "# 世界书触发与上下文预算体检",
        "",
        f"- run_id：`{run_dir.name}`",
        f"- 条目总数：{budget.entry_total}（常驻 {budget.always_on_entries}，触发 {budget.triggered_entries}）",
        f"- 全部条目粗估：{budget.total_tokens} token"
        + (
            f"（单轮预算上限 {target_runtime_budget_tokens}）"
            f"{' —— **超出单轮预算**' if budget.total_tokens > target_runtime_budget_tokens else ''}"
            if target_runtime_budget_tokens is not None
            else ""
        ),
        f"- **常驻预算**：{budget.always_on_tokens} token"
        f"（配置上限 {max_always_on_tokens}）"
        f"{' —— **超出上限**' if budget.always_on_tokens > max_always_on_tokens else ''}",
        "",
        "> 常驻条目与消息内容无关，**每一轮**都在上下文里。"
        "优化常驻预算是唯一确定有效的省额度手段。",
        "",
        "## 按类别的开销",
        "",
        "| 类别 | 条目数 | 正文字符 | 粗估 token |",
        "|---|---|---|---|",
    ]
    for category, count in sorted(budget.by_category.items(), key=lambda kv: -budget.tokens_by_category.get(kv[0], 0)):
        lines.append(
            f"| {category} | {count} | {budget.chars_by_category.get(category, 0)} "
            f"| {budget.tokens_by_category.get(category, 0)} |"
        )

    lines += [
        "",
        "## 最坏情况",
        "",
        f"- 最「贵」的一条：**{budget.worst_entry_title}**（`{budget.worst_entry_id}`）",
        f"- 把它的全部触发词同时写进一句话，会拉起 {budget.worst_case_entries} 个条目 ≈ "
        f"**{budget.worst_case_tokens} token**",
        "",
        "> 这是构造出来的上界，真实对白很少这么巧 —— 但设计触发词时该看这个数字。",
        "",
        "## 触发词风险",
        "",
    ]
    if budget.key_risks:
        lines += ["| 触发词 | 关联条目数 | 问题 |", "|---|---|---|"]
        for risk in budget.key_risks[:25]:
            lines.append(f"| `{risk.key}` | {risk.entry_count} | {risk.reason} |")
    else:
        lines.append("没有发现过短的键，也没有发现被大量条目共用的键。")

    if budget.single_key_entries:
        lines += [
            "",
            f"## 只有单个触发词的条目（{len(budget.single_key_entries)} 个）",
            "",
            "单个键意味着：**任何**含这个词的句子都会命中，包括否定、引用和转述。",
            "",
            "、".join(budget.single_key_entries[:40])
            + ("…" if len(budget.single_key_entries) > 40 else ""),
        ]

    if budget.probes:
        lines += ["", "## 探测句", ""]
        for probe in budget.probes:
            lines.append(f"### 「{probe.message}」")
            lines.append("")
            triggered = [m for m in probe.matched if not m.always_on]
            lines.append(
                f"- 命中触发条目 **{len(triggered)}** 个，常驻 {len(probe.matched) - len(triggered)} 个"
                f"，粗估 **{probe.total_tokens} token**"
            )
            for item in triggered[:10]:
                lines.append(f"  - {item.title}（命中键：{'、'.join(item.matched_keys)}）")
            if len(triggered) > 10:
                lines.append(f"  - …另有 {len(triggered) - 10} 个")
            lines.append("")

    lines += ["", "## 口径", ""]
    for note in budget.notes:
        lines.append(f"- {note}")

    lines += ["", "> 本报告不含小说原文。", ""]
    return "\n".join(lines)


def _evidence_stats(run_dir: Path) -> dict[str, int | float]:
    """从抽取结果汇总**证据定位**指标。

    名字要说清楚它是什么：这是 `quote_location_success_rate`
    —— 引文能不能在原文里逐字找到，**不是**事实正确率。
    """
    total = located = ambiguous = 0
    for path in sorted((run_dir / "extraction").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        total += int(data.get("evidence_total", 0) or 0)
        located += int(data.get("evidence_located", 0) or 0)
        ambiguous += int(data.get("evidence_ambiguous", 0) or 0)
    return {
        "quotes_total": total,
        "quotes_located": located,
        "quotes_ambiguous": ambiguous,
        "quote_location_success_rate": round(located / total, 6) if total else 0.0,
        # 只取首次匹配会掩盖「同一句话在书里出现两次」。这个指标把那一类单列出来。
        "unique_quote_rate": (
            round((located - ambiguous) / located, 6) if located else 0.0
        ),
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


def _style_manifest_block(style_artifacts) -> dict:
    if style_artifacts is None:
        return {"enabled": False}
    from ..timeline.worldbible import estimate_tokens

    profile = style_artifacts.profile
    return {
        "enabled": True,
        "profile_id": profile.profile_id,
        "inputs_fingerprint": profile.inputs_fingerprint,
        "runtime_tokens_est": estimate_tokens(style_artifacts.runtime_text),
        "worldbook_entries": len(style_artifacts.entries),
        "note": "风格资料非 canon；token 为粗估，不是分词器计数",
    }


def _provenance(run_dir: Path) -> dict:
    """运行溯源：这份产物到底是**怎么**来的。

    目的是让「同样输入 + 同样配置 + 同样预生成响应」能复现出同样的内部数据，
    并且在结果不对时能立刻判断是哪一环变了。

    **绝不记录密钥或 Authorization 头。**
    """
    from ..extract.prompts import PROMPT_VERSION as EXTRACT_PROMPT_VERSION
    from ..extract.runner import SCHEMA_VERSION, prompt_template_hash
    from ..verify.prompts import PROMPT_VERSION as VERIFY_PROMPT_VERSION

    providers: dict[str, int] = {}
    models: dict[str, int] = {}
    prompt_versions: dict[str, int] = {}
    for path in sorted((run_dir / "extraction").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        provider = data.get("provider") or "unknown"
        providers[provider] = providers.get(provider, 0) + 1
        model = data.get("model") or "(未记录)"
        models[model] = models.get(model, 0) + 1
        version = data.get("prompt_version") or "(未记录)"
        prompt_versions[version] = prompt_versions.get(version, 0) + 1

    from ..verify import load_verdicts

    verdicts = load_verdicts(run_dir)

    return {
        "package_version": __version__,
        "extraction": {
            "providers": providers,
            "models": models,
            "prompt_versions": prompt_versions,
            "prompt_version_expected": EXTRACT_PROMPT_VERSION,
            "prompt_template_sha256": prompt_template_hash(),
            "output_schema_version": SCHEMA_VERSION,
            "provider_note": (
                "`file` 表示结果来自预生成响应，**不是**实时 API 调用"
                if "file" in providers
                else "结果来自实时 API 调用"
            ),
        },
        "verification": (
            {
                "executed": True,
                "verifier": verdicts.verifier,
                "prompt_version": verdicts.prompt_version,
                "prompt_version_expected": VERIFY_PROMPT_VERSION,
            }
            if verdicts is not None
            else {"executed": False, "note": "未跑 n2t verify"}
        ),
        "cache_invalidation_keys": [
            "模型", "引擎", "提示词版本", "提示词模板 hash",
            "输出 schema 版本", "输入 chunk 的 sha256", "temperature",
        ],
        "note": "不记录任何凭据、密钥或 Authorization 头。",
    }


def _style_observation_coverage(run_dir: Path) -> tuple[int, int]:
    directory = run_dir / "author_style" / "observations"
    observed = len(
        [p for p in directory.glob("*.json") if not p.name.startswith("_")]
    ) if directory.is_dir() else 0
    manifest_path = run_dir / "manifest.json"
    total = 0
    if manifest_path.is_file():
        total = len(json.loads(manifest_path.read_text(encoding="utf-8")).get("chunks", []))
    return observed, total


def _style_dropped_count(run_dir: Path) -> int:
    """从编译审计里读压缩丢弃项数。读不到就如实写 0。"""
    path = run_dir / "author_style" / "audit.md"
    if not path.is_file():
        return 0
    match = re.search(r"丢弃规律数：(\d+)", path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else 0


def _style_audit_lines(run_dir: Path, style_artifacts) -> list[str]:
    lines = ["## 作者风格（旁路资料，非 canon）", ""]
    if style_artifacts is None:
        lines += ["- 启用：否 —— 本次导出结果与未启用风格模块时一致。", ""]
        return lines

    from ..timeline.worldbible import estimate_tokens

    profile = style_artifacts.profile
    observed, total = _style_observation_coverage(run_dir)
    coverage = f"{observed} / {total} 块"
    if observed < total:
        coverage += "（`observe_max_chunks` 抽样，不是全量）"
    lines += [
        "- 启用：是",
        f"- profile_id：`{profile.profile_id}`",
        f"- inputs_fingerprint：`{profile.inputs_fingerprint}`",
        f"- 观察覆盖：{coverage}",
        f"- 【叙事风格规范】粗估：{estimate_tokens(style_artifacts.runtime_text)} token",
        f"- 风格世界书条目：{len(style_artifacts.entries)}（触发式，非常驻）",
        f"- 压缩丢弃项：{_style_dropped_count(run_dir)}",
        "- 风格资料**不写** facts / entities / timeline / knowledge；canon 数据未受影响。",
        "",
    ]
    return lines


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
    config_mode: str = "branch_start",
    style_artifacts=None,
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
        f"- 目标格式：`chara_card_v2` / `2.0`（{TARGET_CLIENT}）",
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
        f"| 唯一定位率 | {evidence['quotes_located'] - evidence['quotes_ambiguous']} / "
        f"{evidence['quotes_located']} = {evidence['unique_quote_rate']:.2%} "
        f"（多处命中 {evidence['quotes_ambiguous']} 条） "
        "| 引文在原文里**只有一处**命中，所以「来源」是确定的 | "
        "找得到但有多处时，取的是最靠前的那一处，未必是这条事实的出处 |",
        f"| 语义支持校验 | {semantic_cell} | 引文**支持**该主张 | "
        "见 `semantic_report.md`；未执行时这一列是空的 |",
        "",
        f"- `facts.json` 里 `needs_review` 的事实：{review_failures} 条"
        "（引文定位失败**或**多处命中）—— 这**不是**「已人工审校」",
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
        "## 游玩模式",
        "",
        f"- 模式：**{mode_block(config_mode)['label']}**（`{config_mode}`）",
        f"- 承诺：{mode_block(config_mode)['promise']}",
        f"- 前提：{mode_block(config_mode)['caveat']}",
        f"- canon 策略：{mode_block(config_mode)['canon_policy']}",
        f"- 分支策略：{mode_block(config_mode)['branch_policy']}",
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

    lines += _style_audit_lines(run_dir, style_artifacts)

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
