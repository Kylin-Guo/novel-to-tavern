"""run 目录布局与非破坏式写入。

每次执行使用独立的 `runs/<run_id>/`。默认拒绝写入已存在的 run 目录，
绝不清空、覆盖或删除已有输入与中间结果。
"""

from __future__ import annotations

import re
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path

#: run 目录下的标准子目录。各阶段只写自己那几个。
RUN_SUBDIRS = (
    "manifests",
    "chunks",
    "extraction",
    "canonical",
    "worldbook",
    "exports",
    "reports",
    "logs",
)

_RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{6}$")


class RunDirError(RuntimeError):
    """run 目录相关错误。"""


def new_run_id(*, now: datetime | None = None) -> str:
    """生成 run id：`20261016T120000Z_1a2b3c`（UTC + 6 位随机后缀）。"""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{_secrets.token_hex(3)}"


def is_valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.match(run_id))


def create_run_dir(
    output_root: str | Path,
    run_id: str | None = None,
    *,
    allow_existing: bool = False,
) -> Path:
    """创建并返回 run 目录。

    目录已存在时默认抛 `RunDirError`；只有显式 `allow_existing=True` 才会复用，
    且复用时不删除任何已有文件。
    """
    root = Path(output_root)
    resolved_id = run_id or new_run_id()
    if not is_valid_run_id(resolved_id):
        raise RunDirError(f"不合法的 run id：{resolved_id!r}")

    run_dir = root / resolved_id
    if run_dir.exists() and not allow_existing:
        raise RunDirError(
            f"run 目录已存在：{run_dir}。"
            "如需复用请显式传 allow_existing=True；本项目不会自动覆盖已有产物。"
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    for name in RUN_SUBDIRS:
        (run_dir / name).mkdir(exist_ok=True)
    return run_dir


def run_layout(run_dir: str | Path) -> dict[str, Path]:
    """返回 run 目录下各子目录的路径映射。"""
    base = Path(run_dir)
    return {name: base / name for name in RUN_SUBDIRS}
