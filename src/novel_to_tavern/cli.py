"""命令行入口。

Phase 0 只有诊断类子命令；后续阶段的 `import` / `extract` / `resolve` /
`timeline` / `export` 都挂在这里。
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from . import TARGET_CLIENT, __version__, config as config_module, env as env_module
from .logging_setup import get_logger, setup_logging
from .paths import RunDirError, resolve_run_dir

PROG = "n2t"

#: 格式验证所锚定的目标客户端版本（见 docs/FORMAT_COMPATIBILITY.md）。
def _chapter_number(text: str) -> int:
    """章节号：从 1 开始的正整数。

    早先用 `type=int` 收下任何整数，随后 `start_chapter - 1 if start_chapter else None`
    把 **0 当成「没指定」**（0 是 falsy），把负数原样减 1 传下去。
    0 和负数都是真实会写错的输入，必须在参数层就报错，而不是让它走到下游才炸。
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"章节号必须是整数，收到 {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"章节号从 1 开始，不能是 {value}")
    return value


def _resolve_run(config, args) -> Path | None:
    """解析并校验 `--run-id`。不合法就说明原因并返回 `None`。

    每个读写既有 run 的子命令都必须走这里。早先各处直接
    `Path(output_root) / args.run_id`，于是 `--run-id /etc` 会解析到 `/etc`
    并通过 `is_dir()` 检查，接着在 `/etc/` 下写产物。详见 `paths.resolve_run_dir`。
    """
    try:
        return resolve_run_dir(config.project.output_root, args.run_id)
    except RunDirError as exc:
        print(f"run 目录不可用：{exc}", file=sys.stderr)
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="把小说文本转换成可导入 SillyTavern/Tavo 的世界模拟器角色卡与世界书。",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--config", metavar="PATH", help="配置文件路径，默认 config/config.yaml")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认 INFO）",
    )
    parser.add_argument("--log-file", metavar="PATH", help="日志写入文件；不指定则输出到 stderr")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("version", help="打印版本与目标格式版本")
    sub.add_parser("config-check", help="加载并校验配置文件，报告环境变量是否就绪")
    sub.add_parser("doctor", help="检查运行环境、配置与凭据隔离情况")

    ingest_parser = sub.add_parser("ingest", help="导入原文、建立章节索引与分块（Phase 1）")
    ingest_parser.add_argument("--run-id", help="复用/指定 run id；不指定则新建")
    ingest_parser.add_argument(
        "--no-resume", action="store_true", help="不复用已有状态，强制重新处理所有来源"
    )
    ingest_parser.add_argument(
        "--source", metavar="PATH", help="覆盖配置里的 source_path（文件或目录）"
    )

    extract_parser = sub.add_parser("extract", help="分块原子事实提取（Phase 2）")
    extract_parser.add_argument("--run-id", required=True, help="要抽取的 run id（来自 ingest）")
    extract_parser.add_argument(
        "--no-resume", action="store_true", help="忽略已有结果，重新抽取所有分块"
    )
    extract_parser.add_argument("--limit", type=int, metavar="N", help="只处理前 N 块（调试用）")

    resolve_parser = sub.add_parser("resolve", help="实体消歧与角色档案（Phase 3）")
    resolve_parser.add_argument("--run-id", required=True, help="要归一的 run id（来自 extract）")

    timeline_parser = sub.add_parser(
        "timeline", help="时间线、知识边界与世界书规划（Phase 4）"
    )
    timeline_parser.add_argument("--run-id", required=True, help="要构建时间线的 run id")
    timeline_parser.add_argument(
        "--start-chapter",
        type=_chapter_number,
        metavar="N",
        help="起始章节（1 起）。指定后会按 valid_from_chapter 屏蔽该章节之后的内容",
    )
    timeline_parser.add_argument(
        "--include-character",
        action="append",
        default=[],
        metavar="NAME",
        help="强制为这个实体生成独立条目，即使它没过「事实数/章节数」门槛。"
        "可重复。按主名或别名匹配 —— 想扮演一个被门槛刷掉的配角时用这个。",
    )

    verify_parser = sub.add_parser(
        "verify", help="语义支持校验：引文支不支持这条主张（Phase 6）"
    )
    verify_parser.add_argument("--run-id", required=True, help="要校验的 run id")
    verify_parser.add_argument(
        "--sample", type=int, metavar="N", help="只校验前 N 条（抽样；报告会写明是抽样）"
    )
    verify_parser.add_argument(
        "--only-high-impact",
        action="store_true",
        help="只校验高风险事实（身份/生死/秘密/关系/能力/立场）",
    )

    style_observe_parser = sub.add_parser(
        "style-observe", help="逐分块观察作者写作风格（旁路资料，非 canon）"
    )
    style_observe_parser.add_argument(
        "--run-id", required=True, help="要观察的 run id（来自 ingest）"
    )
    style_observe_parser.add_argument(
        "--no-resume", action="store_true", help="忽略已有观察，重新观察所有选中分块"
    )
    style_observe_parser.add_argument(
        "--limit", type=int, metavar="N", help="只处理选中的前 N 块（调试用）"
    )

    style_compile_parser = sub.add_parser(
        "style-compile", help="把风格观察合并、编译成风格档案（旁路资料，非 canon）"
    )
    style_compile_parser.add_argument(
        "--run-id", required=True, help="要编译的 run id（先跑 style-observe）"
    )
    style_compile_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="强制重编译：先清掉 author_style/ 下除 observations/ 以外的产物",
    )

    export_parser = sub.add_parser(
        "export", help="导出角色卡与世界书（Phase 5）"
    )
    export_parser.add_argument("--run-id", required=True, help="要导出的 run id")
    export_parser.add_argument(
        "--start-chapter",
        type=_chapter_number,
        metavar="N",
        help="（世界书计划在 timeline 阶段生成；要强制保留某个配角，"
        "用 n2t timeline --include-character 重跑计划再导出）"
        "额外产出一套严格起始点产物（1 起的章节号）："
        "第 N 章之后的内容不写入任何条目，做到结构性无剧透。"
        "不指定则只产出默认的「尽力而为」档。",
    )

    return parser


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"{PROG} {__version__}")
    print(f"目标客户端格式：{TARGET_CLIENT}")
    return 0


def _cmd_config_check(args: argparse.Namespace, log) -> int:
    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    path = args.config or (
        config_module.DEFAULT_CONFIG_PATH
        if config_module.DEFAULT_CONFIG_PATH.is_file()
        else config_module.EXAMPLE_CONFIG_PATH
    )
    print(f"配置文件：{path}")
    print("解析结果：")
    for key, value in config_module.summarize(config).items():
        print(f"  {key} = {value!r}")

    print("环境变量（只报告是否存在，不显示值）：")
    for name, present in config_module.env_status(config).items():
        print(f"  {name}: {'已配置' if present else '未配置'}")

    warnings = config_module.config_warnings(config)
    if warnings:
        print("提示：")
        for item in warnings:
            print(f"  - {item}")
    log.info("config-check 完成（%d 项提示）", len(warnings))
    return 0


#: doctor 的检查级别。FAIL 影响退出码；WARN 只提示。
FAIL = "FAIL"
WARN = "WARN"
OK = "OK"

_MARKS = {OK: "OK", WARN: "--", FAIL: "!!"}


def _cmd_doctor(args: argparse.Namespace, log) -> int:
    checks: list[tuple[str, str, str]] = []

    checks.append(
        ("Python 版本", OK if sys.version_info >= (3, 10) else FAIL, platform.python_version())
    )

    config_path = Path(args.config) if args.config else None
    try:
        config = config_module.load_config(config_path)
        checks.append(("配置文件", OK, str(config_path or "自动发现")))
    except config_module.ConfigError as exc:
        config = None
        checks.append(("配置文件", FAIL, str(exc).splitlines()[0]))

    dotenv = Path(env_module.DEFAULT_DOTENV)
    checks.append((".env 文件", OK, "存在" if dotenv.is_file() else "不存在（当前用不到）"))

    gitignore = Path(".gitignore")
    ignored = False
    if gitignore.is_file():
        lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
        ignored = ".env" in lines
    checks.append((".env 已被 .gitignore 排除", OK if ignored else FAIL, str(gitignore)))

    if config is not None:
        # Phase 0 不需要凭据，所以缺凭据只是提示，不当失败 —— 否则 doctor 永远非零退出。
        for name, present in config_module.env_status(config).items():
            checks.append(
                (
                    f"环境变量 {name}",
                    OK if present else WARN,
                    "已配置" if present else "未配置（进入 Phase 2 前需要）",
                )
            )

    print(f"{PROG} {__version__} 环境检查")
    print(f"目标客户端格式：{TARGET_CLIENT}")
    print()
    for label, level, detail in checks:
        print(f"  [{_MARKS[level]:>2}] {label}: {detail}")

    failed = [label for label, level, _ in checks if level == FAIL]
    warned = [label for label, level, _ in checks if level == WARN]
    if warned:
        print()
        print(f"提示：{', '.join(warned)}")
    if failed:
        print()
        print(f"未通过：{', '.join(failed)}")
        log.warning("doctor 未通过项：%s", ", ".join(failed))
        return 1
    log.info("doctor 通过（%d 项提示）", len(warned))
    return 0


def _cmd_ingest(args: argparse.Namespace, log) -> int:
    from .ingest import IngestError, ingest

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    if args.source:
        config = config.model_copy(
            update={"project": config.project.model_copy(update={"source_path": args.source})}
        )

    try:
        run_dir, manifest = ingest(
            config,
            run_id=args.run_id,
            resume=not args.no_resume,
            log=log,
        )
    except (IngestError, config_module.ConfigError) as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1

    print(f"run 目录：{run_dir}")
    print(f"来源文件：{len(manifest.sources)}")
    print(f"章节数：{len(manifest.chapters)}")
    print(f"分块数：{len(manifest.chunks)}")
    print(f"警告数：{len(manifest.warnings)}")
    print(f"报告：{run_dir / 'reports' / 'ingest_summary.md'}")
    return 0


def _cmd_extract(args: argparse.Namespace, log) -> int:
    from .extract import ExtractionError, run_extraction
    from .llm import ProviderError, build_provider

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    try:
        provider = build_provider(config, log=log)
    except ProviderError as exc:
        print(f"无法装配抽取引擎：{exc}", file=sys.stderr)
        return 1

    try:
        result = run_extraction(
            config, run_dir, provider, resume=not args.no_resume, limit=args.limit, log=log
        )
    except ExtractionError as exc:
        print(f"抽取失败：{exc}", file=sys.stderr)
        return 1

    print(f"抽取引擎：{provider.name}")
    print(f"已完成分块：{len(result.done)}")
    print(f"本次跳过：{len(result.skipped)}")
    print(f"失败分块：{len(result.failed)}")
    print(f"报告：{run_dir / 'reports' / 'extraction_summary.md'}")
    return 0 if result.ok else 1


def _cmd_resolve(args: argparse.Namespace, log) -> int:
    from .resolve import ResolutionError, resolve

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    try:
        result = resolve(run_dir)
    except ResolutionError as exc:
        print(f"实体归一失败：{exc}", file=sys.stderr)
        return 1

    print(f"实体总数：{len(result.entities)}")
    print(f"合并判定：{len(result.decisions)}")
    print(f"待人工复核：{len(result.review_queue)}")
    print(f"排除泛称：{len(result.excluded_role_nouns)}")
    print(f"报告：{run_dir / 'reports' / 'entity_resolution.md'}")
    log.info("resolve 完成：%d 个实体", len(result.entities))
    return 0


def _cmd_timeline(args: argparse.Namespace, log) -> int:
    from .timeline import TimelineError, build

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    start_chapter = args.start_chapter
    start_index = start_chapter - 1 if start_chapter is not None else None

    try:
        result = build(
            run_dir,
            start_chapter=start_index,
            always_on_world_overview=config.worldbook.always_on_world_overview,
            always_on_character_index=config.worldbook.always_on_character_index,
            force_include=frozenset(args.include_character or ()),
        )
    except TimelineError as exc:
        print(f"构建时间线失败：{exc}", file=sys.stderr)
        return 1

    stats = result["plan_stats"]
    print(f"事件数：{len(result['timeline'])}")
    print(f"知识边界实体数：{len(result['knowledge'])}")
    print(f"冲突数：{len(result['contradictions'])}")
    print(
        "从开头开始时需屏蔽的未来内容："
        f"{len(result['leakage']['start_at_beginning'])} 条"
    )
    print(f"世界书规划条目：{stats['total_entries']}（常驻 {stats['always_on_entries']}）")
    coverage = result.get("coverage") or {}
    if coverage:
        print(
            f"实体覆盖：{coverage['entities_total']} 个实体，"
            f"{coverage['entities_with_entry']} 个有独立条目，"
            f"{coverage['entities_skipped']} 个被跳过（名单见报告）"
        )
        if args.include_character:
            matched = set(coverage.get("forced") or ())
            missed = [n for n in args.include_character if n not in matched]
            if missed:
                print(
                    f"警告：--include-character 里的 {missed} 没有匹配到任何实体（检查名字写法）",
                    file=sys.stderr,
                )
    print(f"报告：{run_dir / 'reports' / 'timeline_report.md'}")
    log.info("timeline 完成：%d 个事件，%d 个规划条目", len(result["timeline"]), stats["total_entries"])
    return 0


def _cmd_verify(args: argparse.Namespace, log) -> int:
    from .llm import ProviderError, build_provider
    from .verify import VerificationError, run_verification

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    try:
        provider = build_provider(config, log=log)
    except ProviderError as exc:
        print(f"无法装配校验引擎：{exc}", file=sys.stderr)
        return 1

    try:
        report = run_verification(
            run_dir,
            provider,
            sample=args.sample,
            only_high_impact=args.only_high_impact,
            log=log,
        )
    except VerificationError as exc:
        print(f"语义校验失败：{exc}", file=sys.stderr)
        return 1

    print(f"校验引擎：{report.verifier}")
    print(f"canon 事实总数：{report.facts_total}")
    print(f"本次校验：{report.facts_checked} 条")
    for verdict in ("entailed", "partially_supported", "contradicted", "insufficient_evidence"):
        if report.counts.get(verdict):
            print(f"  {verdict}：{report.counts[verdict]}")
    print(f"排除在条目正文之外：{len(report.excluded_fact_ids)} 条")
    print(f"报告：{run_dir / 'reports' / 'semantic_report.md'}")
    if args.sample:
        print("注意：这是抽样结果，报告里已写明，不要当成全量结论。")
    return 0


def _cmd_style_observe(args: argparse.Namespace, log) -> int:
    from .llm import ProviderError, build_provider
    from .style import StyleError, run_style_observation

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    try:
        provider = build_provider(config, log=log)
    except ProviderError as exc:
        print(f"无法装配风格观察引擎：{exc}", file=sys.stderr)
        return 1

    try:
        result = run_style_observation(
            config,
            run_dir,
            provider,
            resume=not args.no_resume,
            limit=args.limit,
            log=log,
        )
    except StyleError as exc:
        print(f"风格观察失败：{exc}", file=sys.stderr)
        return 1

    coverage = result["coverage"]
    print(f"观察引擎：{provider.name}")
    print(f"已完成观察：{len(result['done'])}")
    print(f"本次跳过：{len(result['skipped'])}")
    print(f"失败分块：{len(result['failed'])}")
    print(
        f"覆盖率：{coverage['observed']} / {coverage['selected']} 选中块"
        f"（全部分块 {coverage['total_chunks']}）"
    )
    print(f"报告：{result['report']}")
    return 0 if result["ok"] else 1


def _cmd_style_compile(args: argparse.Namespace, log) -> int:
    import shutil

    from .llm import ProviderError, build_provider
    from .style import StyleError, run_style_compile

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    if args.no_resume:
        # 只清产物，不动 observations/ —— 观察是花了调用换来的。
        base = run_dir / "author_style"
        if base.is_dir():
            for child in base.iterdir():
                if child.name == "observations":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    try:
        provider = build_provider(config, log=log)
    except ProviderError as exc:
        print(f"无法装配风格编译引擎：{exc}", file=sys.stderr)
        return 1

    try:
        profile = run_style_compile(run_dir, config, provider, log=log)
    except StyleError as exc:
        print(f"风格编译失败：{exc}", file=sys.stderr)
        return 1

    from .timeline.worldbible import estimate_tokens

    entries_path = run_dir / "author_style" / "style_worldbook_entries.json"
    entry_count = 0
    if entries_path.is_file():
        import json

        entry_count = len(json.loads(entries_path.read_text(encoding="utf-8")))

    print(f"编译引擎：{provider.name}")
    print(f"profile_id：{profile.profile_id}")
    print(
        f"运行时规范：约 {estimate_tokens(profile.runtime_rules)} token"
        f"（预算 {config.style.max_runtime_tokens}）"
    )
    print(f"风格世界书条目：{entry_count}")
    print(f"审计：{run_dir / 'author_style' / 'audit.md'}")
    return 0


def _cmd_export(args: argparse.Namespace, log) -> int:
    from .export import ExportError, export
    from .llm import ProviderError, build_provider
    from .style import StyleError

    try:
        config = config_module.load_config(args.config)
    except config_module.ConfigError as exc:
        print(f"配置校验失败：{exc}", file=sys.stderr)
        return 1

    run_dir = _resolve_run(config, args)
    if run_dir is None:
        return 1

    # 风格产物新鲜时**不需要**引擎 —— 没有凭据也能导出。
    provider = None
    if config.style.enabled:
        from .style.pipeline import style_artifacts_fresh

        if not style_artifacts_fresh(run_dir, config):
            try:
                provider = build_provider(config, log=log)
            except ProviderError as exc:
                print(
                    f"风格产物不存在/已过期且无法装配引擎：{exc}",
                    file=sys.stderr,
                )
                return 1

    start_chapter = args.start_chapter - 1 if args.start_chapter is not None else None
    try:
        result = export(
            run_dir, config, start_chapter=start_chapter, provider=provider, log=log
        )
    except (ExportError, StyleError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1

    card = result["card"]
    stats = result["stats"]
    print(f"角色卡：{run_dir / 'exports' / 'world_simulator_v2.json'}")
    print(f"内嵌世界书条目：{len(card.data.character_book.entries)}")
    print(f"常驻条目：{stats['always_on_entries']}（约 {stats['always_on_tokens']} token，粗估）")
    print(f"开场白：1 个主开场 + {len(card.data.alternate_greetings)} 个备用开场")
    print(f"按起始点屏蔽：{len(result['blocked_begin'])} 个条目")

    strict = result.get("strict")
    if strict:
        plan = strict["plan"]
        state = strict["state"]
        print()
        print(f"严格起始点：{state.start_chapter_label}（结构性无剧透）")
        print(f"  角色卡：{run_dir / 'exports' / strict['files'][0]}")
        print(f"  世界书：{run_dir / 'exports' / strict['files'][1]}")
        print(f"  状态快照：{run_dir / 'exports' / strict['files'][2]}")
        print(
            f"  canon 事实：采用 {plan.facts_included}，隐藏 {plan.facts_excluded}"
            f"；条目删 {state.entries_dropped} / 截断 {state.entries_truncated}"
        )

    print(f"审计报告：{run_dir / 'reports' / 'audit.md'}")
    log.info("export 完成：%d 个条目", len(card.data.character_book.entries))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    log = setup_logging(args.log_level, log_file=args.log_file)

    if args.command == "version":
        return _cmd_version(args)
    if args.command == "config-check":
        return _cmd_config_check(args, log)
    if args.command == "doctor":
        return _cmd_doctor(args, log)
    if args.command == "ingest":
        return _cmd_ingest(args, log)
    if args.command == "extract":
        return _cmd_extract(args, log)
    if args.command == "resolve":
        return _cmd_resolve(args, log)
    if args.command == "timeline":
        return _cmd_timeline(args, log)
    if args.command == "verify":
        return _cmd_verify(args, log)
    if args.command == "style-observe":
        return _cmd_style_observe(args, log)
    if args.command == "style-compile":
        return _cmd_style_compile(args, log)
    if args.command == "export":
        return _cmd_export(args, log)

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
