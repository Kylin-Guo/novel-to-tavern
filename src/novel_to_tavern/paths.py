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


def resolve_run_dir(
    output_root: str | Path, run_id: str, *, must_exist: bool = True
) -> Path:
    """把 `--run-id` 解析成一个**确定落在 output_root 之下**的 run 目录。

    所有读/写既有 run 的子命令都必须走这里，不能自己 `Path(root) / run_id`。

    不做这一步会发生什么（都已实测）：

    - `--run-id /etc` → `/etc`。`Path("runs") / "/etc"` 是 `/etc` ——
      绝对路径直接吃掉前缀，而它通过 `is_dir()` 检查，于是工具会在 `/etc/exports/`
      下写产物。
    - `--run-id ''` → `runs` 本身，产物写进 run 根。
    - `--run-id '../../etc'` → 跑出受控目录。

    第一道闸是格式校验（run id 只能是 `<UTC 时间戳>_<6 位小写十六进制>`），
    它顺带挡掉了所有含 `/`、`..`、空串、反斜杠的取值；第二道闸是 `resolve()`
    后确认父目录就是 output_root，用来挡**符号链接**——那是格式校验看不见的。
    """
    if not is_valid_run_id(run_id):
        raise RunDirError(
            f"不合法的 run id：{run_id!r}。"
            "格式应为 <8位日期>T<6位时间>Z_<6位十六进制>，例如 20261016T120000Z_1a2b3c。"
        )

    root = Path(output_root).resolve()
    candidate = (root / run_id).resolve()
    if candidate.parent != root:
        raise RunDirError(
            f"run id 解析后跑出了 run 根目录：{run_id!r} → {candidate}（根：{root}）。"
            "若这是符号链接造成的，请先确认该链接指向哪里。"
        )
    if must_exist and not candidate.is_dir():
        raise RunDirError(f"找不到 run 目录：{candidate}")
    return candidate


def run_layout(run_dir: str | Path) -> dict[str, Path]:
    """返回 run 目录下各子目录的路径映射。"""
    base = Path(run_dir)
    return {name: base / name for name in RUN_SUBDIRS}
