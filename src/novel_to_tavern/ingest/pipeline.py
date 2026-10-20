"""导入与章节索引流水线。

- 原文只读；产物全部写进 `runs/<run_id>/`。
- 每个来源处理完即落盘（manifest + state），中断后用同一 run 目录重跑即可续跑。
- 结束时校验区段是否无缝铺满文件，并把结论写进 `reports/ingest_summary.md`。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__, config as config_module, paths
from ..ingest.source import SourceReadError, SourceText, line_offsets, read_source, sha256_of
from .chapters import DEFAULT_HEADING_PATTERN, build_chapter_index, rebuild_text
from .chunker import chunk_chapter, rebuild_chapter
from .manifest import (
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    RunState,
    SourceRecord,
    SourceStats,
    stats_for_source,
)

MANIFEST_NAME = "manifest.json"
STATE_NAME = "state.json"
SUMMARY_NAME = "ingest_summary.md"


class IngestError(RuntimeError):
    """导入阶段的致命错误。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _config_fingerprint(config: config_module.Config) -> str:
    """只取会影响切分结果的配置项。"""
    payload = {
        "encoding": config.input.encoding,
        "chapter_detection": config.input.chapter_detection,
        "chapter_heading_regex": config.input.chapter_heading_regex,
        "chunk_target_chars": config.input.chunk_target_chars,
        "chunk_max_chars": config.input.chunk_max_chars,
        "preserve_chapter_boundaries": config.input.preserve_chapter_boundaries,
        # 换行归一化会改变切行结果，所以必须进指纹；否则改了它续跑会复用旧边界。
        "normalize_newlines": config.input.normalize_newlines,
    }
    return sha256_of(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def discover_sources(target: str | Path, *, formats: list[str] | None = None) -> list[Path]:
    """目标可以是单个文件，也可以是目录（按文件名排序）。

    目录模式按 `input.formats` 筛选后缀 —— 早先这里把 `.txt` / `.md` 写死，
    于是配置里改了 `formats` 而行为完全不变（见 docs/CONFIG_REFERENCE.md 的「每个键都要有消费点」）。
    单文件模式不看后缀：用户明确指了一个文件，就按他说的读。
    """
    allowed = {f".{f.lower().lstrip('.')}" for f in (formats or ["txt", "md"])}
    path = Path(target)
    if path.is_file():
        return [path]
    if path.is_dir():
        found = sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in allowed
        )
        if not found:
            raise IngestError(
                f"目录里没有 {'/'.join(sorted(allowed))} 文件：{path}"
                "（认哪些后缀由 input.formats 决定）"
            )
        return found
    raise IngestError(f"找不到输入路径：{path}")


def _load_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def ingest(
    config: config_module.Config,
    *,
    run_id: str | None = None,
    resume: bool | None = None,
    source_paths: list[Path] | None = None,
    log=None,
) -> tuple[Path, Manifest]:
    """执行导入。返回 `(run_dir, manifest)`。"""
    resume = config.pipeline.resume if resume is None else resume
    output_root = Path(config.project.output_root)
    run_dir = paths.create_run_dir(output_root, run_id, allow_existing=resume)

    manifest_path = run_dir / MANIFEST_NAME
    state_path = run_dir / STATE_NAME

    fingerprint = _config_fingerprint(config)
    existing = _load_json(manifest_path) if resume else None
    if existing and existing.get("config_fingerprint") != fingerprint:
        raise IngestError(
            "该 run 是用不同的切分配置生成的，不能续跑（否则章节边界会不一致）。"
            "请换一个 run_id，或去掉 --resume。"
        )

    manifest = Manifest.model_validate(existing) if existing else Manifest(
        parser_version=__version__,
        run_id=run_dir.name,
        created_at=_now(),
        updated_at=_now(),
        config_fingerprint=fingerprint,
    )

    state_payload = _load_json(state_path) if resume else None
    state = RunState.model_validate(state_payload) if state_payload else RunState(
        run_id=run_dir.name, started_at=_now(), updated_at=_now()
    )

    sources = (
        source_paths
        if source_paths is not None
        else discover_sources(config.project.source_path, formats=config.input.formats)
    )
    processed: list[str] = []
    skipped: list[str] = []

    for path in sources:
        try:
            source = read_source(
                path,
                encoding=config.input.encoding,
                normalize_newlines=config.input.normalize_newlines,
            )
        except SourceReadError as exc:
            raise IngestError(str(exc)) from exc

        recorded = state.completed_sources.get(source.source_id)
        if resume and recorded == source.sha256:
            skipped.append(source.source_id)
            if log:
                log.info("跳过已完成的来源：%s", source.source_id)
            continue
        if resume and recorded is not None and recorded != source.sha256:
            # 一个 run 是原文的快照。来源变了却只重跑这一个，会让同一次 run 里
            # 混入两种来源版本，后续阶段的来源引用就自相矛盾了。
            raise IngestError(
                f"来源内容已改变：{source.path}\n"
                f"  记录于 manifest 的 sha256：{recorded}\n"
                f"  当前文件的 sha256：      {source.sha256}\n"
                "一个 run 对应一次原文快照，不能只重跑其中一部分。"
                "请用新的 run_id 重新导入，或还原原文。"
            )

        _ingest_one(manifest, source, config)
        state.completed_sources[source.source_id] = source.sha256
        state.updated_at = _now()
        manifest.updated_at = _now()

        # 每个来源处理完立刻落盘 —— 中断后不必重跑整个文件。
        _write_json(manifest_path, manifest.model_dump(mode="json"))
        _write_json(state_path, state.model_dump(mode="json"))
        processed.append(source.source_id)
        if log:
            log.info("已处理来源：%s", source.source_id)

    _validate_and_report(run_dir, manifest, config, processed=processed, skipped=skipped, log=log)
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    return run_dir, manifest


def _ingest_one(manifest: Manifest, source: SourceText, config: config_module.Config) -> None:
    """把一个来源的章节与分块追加进 manifest（先清理该来源的旧记录，保证幂等）。"""
    manifest.sources = [s for s in manifest.sources if s.source_id != source.source_id]
    manifest.regions = [r for r in manifest.regions if r.source_id != source.source_id]
    manifest.chapters = [c for c in manifest.chapters if c.source_id != source.source_id]
    manifest.chunks = [c for c in manifest.chunks if c.source_id != source.source_id]
    manifest.warnings = [w for w in manifest.warnings if not w.startswith(f"[{source.source_id}]")]

    manifest.sources.append(
        SourceRecord(
            source_id=source.source_id,
            path=source.path,
            filename=source.filename,
            sha256=source.sha256,
            size_bytes=source.size_bytes,
            encoding=source.encoding,
            newline_style=source.newline_style,
            total_lines=source.total_lines,
            total_chars=source.total_chars,
        )
    )

    index = build_chapter_index(
        source.lines,
        source_id=source.source_id,
        pattern=config.input.chapter_heading_regex or DEFAULT_HEADING_PATTERN,
        strategy=config.input.chapter_detection,
        target_chars=config.input.chunk_target_chars,
    )
    manifest.detections[source.source_id] = index.detection
    manifest.regions.extend(index.regions)
    manifest.chapters.extend(index.chapters)

    if source.newline_style == "mixed":
        manifest.warnings.append(f"[{source.source_id}] 换行符风格混用，已按原样保留。")

    offsets = line_offsets(source.lines)
    next_index = len(manifest.chunks)
    oversized = 0
    for chapter in index.chapters:
        plan = chunk_chapter(
            source.lines,
            offsets,
            chapter,
            target_chars=config.input.chunk_target_chars,
            max_chars=config.input.chunk_max_chars,
            start_index=next_index,
        )
        manifest.chunks.extend(plan.chunks)
        next_index += len(plan.chunks)
        for line_no in plan.oversized_lines:
            oversized += 1
            manifest.warnings.append(
                f"[{source.source_id}] 第 {line_no + 1} 行单行超过 chunk_max_chars，"
                "已独占一块（行对齐优先于长度上限）。"
            )

    for note in index.detection.notes:
        manifest.warnings.append(f"[{source.source_id}] {note}")

    manifest.stats[source.source_id] = stats_for_source(
        manifest, source.source_id, oversized_lines=oversized
    )


def _validate_and_report(
    run_dir: Path,
    manifest: Manifest,
    config: config_module.Config,
    *,
    processed: list[str],
    skipped: list[str],
    log=None,
) -> None:
    """校验无损性并把结论写进报告。校验失败直接抛错，不留下"看起来成功"的产物。"""
    lines_by_source: dict[str, list[str]] = {}

    for record in manifest.sources:
        source = read_source(
            record.path,
            encoding=record.encoding,
            source_id=record.source_id,
            normalize_newlines=config.input.normalize_newlines,
        )
        if source.sha256 != record.sha256:
            raise IngestError(
                f"来源文件在处理后被修改：{record.path}。请重新跑一次导入。"
            )
        lines_by_source[record.source_id] = source.lines

        regions = [r for r in manifest.regions if r.source_id == record.source_id]
        if rebuild_text(source.lines, regions) != source.text:
            raise IngestError(f"区段无法无损重组原文：{record.source_id}")

        ok, problems = manifest.region_coverage(record.source_id, source.total_lines)
        if not ok:
            raise IngestError(f"区段覆盖不完整：{record.source_id} —— {'; '.join(problems)}")

        for chapter in manifest.chapters_of(record.source_id):
            restored = rebuild_chapter(
                source.lines, chapter, manifest.chunks_of(chapter.chapter_id)
            )
            expected = "".join(source.lines[chapter.start_line : chapter.end_line])
            if restored != expected:
                raise IngestError(f"章节分块无法无损重组：{chapter.chapter_id}")

    report = _render_summary(manifest, processed=processed, skipped=skipped)
    (run_dir / "reports" / SUMMARY_NAME).write_text(report, encoding="utf-8")
    if log:
        log.info("导入完成：%d 个来源，%d 章，%d 块", len(manifest.sources), len(manifest.chapters), len(manifest.chunks))


def _render_summary(manifest: Manifest, *, processed: list[str], skipped: list[str]) -> str:
    total_chars = sum(s.total_chars for s in manifest.sources)
    total_chunk_chars = sum(c.char_count for c in manifest.chunks)
    lines = [
        "# 导入与章节索引报告",
        "",
        f"- run_id：`{manifest.run_id}`",
        f"- 生成时间：{manifest.updated_at}",
        f"- manifest schema：v{MANIFEST_SCHEMA_VERSION}",
        f"- 本次处理来源：{', '.join(processed) or '（无）'}",
        f"- 续跑跳过来源：{', '.join(skipped) or '（无）'}",
        "",
        "## 总览",
        "",
        f"- 来源文件：{len(manifest.sources)}",
        f"- 原文总字符：{total_chars}",
        f"- 章节数：{len(manifest.chapters)}",
        f"- 分块数：{len(manifest.chunks)}",
        f"- 分块覆盖字符：{total_chunk_chars}",
        f"- 未分块字符：{total_chars - total_chunk_chars}"
        "（卷首与站点残留，不属于任何章节正文，不参与提取）",
        "",
        "## 逐来源",
        "",
        "| 来源 | 行数 | 字符 | 章节 | 分块 | 检测策略 | 标题数(原始/合并) |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in manifest.sources:
        detection = manifest.detections.get(record.source_id)
        stats = manifest.stats.get(record.source_id, SourceStats())
        lines.append(
            f"| {record.filename} | {record.total_lines} | {record.total_chars} | "
            f"{stats.chapters} | {stats.chunks} | {detection.strategy if detection else '-'} | "
            f"{detection.headings_found if detection else '-'}/"
            f"{detection.headings_merged if detection else '-'} |"
        )

    if manifest.warnings:
        lines += ["", "## 警告", ""]
        lines += [f"- {w}" for w in manifest.warnings]

    lines += [
        "",
        "## 无损性校验",
        "",
        "已通过：区段无缝铺满原文、按区段重组等于原文、每章按分块重组等于章节原文。",
        "（由 `_validate_and_report` 强制校验，失败即中止，不产出报告。）",
        "",
        "> 本报告不含小说原文，只含位置与统计。",
        "",
    ]
    return "\n".join(lines)
