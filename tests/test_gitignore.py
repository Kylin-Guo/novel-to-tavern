"""凭据与运行产物不得入库。"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _patterns() -> list[str]:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _is_ignored(path: str) -> bool:
    """只处理本仓库实际用到的模式：目录、通配符、`!` 取反与前导斜杠锚定。

    `/天之炽/` 只匹配仓库根下的 `天之炽/`；写成 `天之炽/` 会连带忽略
    `exports/天之炽/` 这类同名子目录。
    """
    ignored = False
    for pattern in _patterns():
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        anchored = candidate.startswith("/")
        if anchored:
            candidate = candidate[1:]
        base = candidate.rstrip("/")
        if not base:
            continue

        if anchored:
            hit = path == base or path.startswith(f"{base}/")
        else:
            hit = (
                fnmatch(path, base)
                or fnmatch(path, f"{base}/*")
                or f"/{base}/" in f"/{path}"
                or Path(path).name == base
            )
        if hit:
            ignored = not negated
    return ignored


def test_dotenv_is_ignored():
    assert _is_ignored(".env")


def test_dotenv_variants_are_ignored():
    assert _is_ignored(".env.local")


def test_env_example_is_tracked():
    assert not _is_ignored(".env.example")


def test_runtime_output_dirs_are_ignored():
    for path in ("runs/20261016T120000Z_abcdef/exports/card.json", "cache/x.json", "input/novel.txt"):
        assert _is_ignored(path), path


def test_venv_and_pycache_are_ignored():
    assert _is_ignored(".venv/lib/python3.12/site-packages/x.py")
    assert _is_ignored("src/novel_to_tavern/__pycache__/cli.cpython-312.pyc")


def test_build_artifacts_are_ignored():
    """`pip install -e .` 会在 src/ 下生成 egg-info，曾误提交过一次。"""
    assert _is_ignored("src/novel_to_tavern.egg-info/PKG-INFO")
    assert _is_ignored("src/novel_to_tavern.egg-info/SOURCES.txt")
    assert _is_ignored("build/lib/x.py")
    assert _is_ignored("dist/pkg-0.0.1.tar.gz")
    assert _is_ignored(".pytest_cache/v/cache/nodeids")


def test_source_files_are_not_ignored():
    for path in ("src/novel_to_tavern/cli.py", "docs/PLAN.md", "config/config.example.yaml"):
        assert not _is_ignored(path), path


def test_copyrighted_novel_is_ignored():
    """受版权保护的原文只作本地只读输入，绝不能进仓库。"""
    assert _is_ignored("天之炽/天之炽Ⅰ：红龙的归来.txt")
    assert _is_ignored("天之炽/天之炽Ⅱ：女武神1.txt")
    assert _is_ignored("天之炽/天之炽Ⅱ：女武神2.txt")


def test_novel_pattern_does_not_swallow_export_subdirectories():
    """`天之炽/` 写成不锚定的形式会连带忽略 exports/天之炽/，导出物就进不了库。"""
    assert not _is_ignored("exports/天之炽/world_simulator_v2.json")


def test_git_itself_confirms_the_novel_is_ignored():
    """用 git 自己的判定兜底，避免手写匹配器与 git 行为不一致。"""
    import subprocess

    novel = REPO_ROOT / "天之炽" / "天之炽Ⅰ：红龙的归来.txt"
    if not novel.exists():
        import pytest

        pytest.skip("本机没有该小说原文")
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(novel)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, "小说原文未被 .gitignore 排除"
