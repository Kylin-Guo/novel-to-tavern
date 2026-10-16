"""命令行入口。

Phase 0 只有诊断类子命令；后续阶段的 `import` / `extract` / `resolve` /
`timeline` / `export` 都挂在这里。
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from . import __version__, config as config_module, env as env_module
from .logging_setup import get_logger, setup_logging

PROG = "n2t"

#: 格式验证所锚定的目标客户端版本（见 docs/FORMAT_COMPATIBILITY.md）。
TARGET_CLIENT = "SillyTavern 1.19.0 / Tavo（待实测）"


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


def _cmd_doctor(args: argparse.Namespace, log) -> int:
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Python 版本", sys.version_info >= (3, 10), platform.python_version()))

    config_path = Path(args.config) if args.config else None
    try:
        config = config_module.load_config(config_path)
        checks.append(("配置文件", True, str(config_path or "自动发现")))
    except config_module.ConfigError as exc:
        config = None
        checks.append(("配置文件", False, str(exc).splitlines()[0]))

    dotenv = Path(env_module.DEFAULT_DOTENV)
    checks.append((".env 文件", True, "存在" if dotenv.is_file() else "不存在（当前用不到）"))

    gitignore = Path(".gitignore")
    ignored = False
    if gitignore.is_file():
        lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
        ignored = ".env" in lines
    checks.append((".env 已被 .gitignore 排除", ignored, str(gitignore)))

    if config is not None:
        status = config_module.env_status(config)
        for name, present in status.items():
            checks.append((f"环境变量 {name}", present, "已配置" if present else "未配置（Phase 2 前需配置）"))

    print(f"{PROG} {__version__} 环境检查")
    print(f"目标客户端格式：{TARGET_CLIENT}")
    print()
    for label, ok, detail in checks:
        print(f"  [{'OK' if ok else '!!'}] {label}: {detail}")

    failed = [label for label, ok, _ in checks if not ok]
    if failed:
        print()
        print(f"未通过：{', '.join(failed)}")
        log.warning("doctor 未通过项：%s", ", ".join(failed))
        return 1
    log.info("doctor 全部通过")
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

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
