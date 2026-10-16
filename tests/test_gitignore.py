"""凭据与运行产物不得入库。"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _patterns() -> list[str]:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _is_ignored(path: str) -> bool:
    """只处理本仓库实际用到的模式：目录、通配符与 `!` 取反。"""
    ignored = False
    for pattern in _patterns():
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        base = candidate.rstrip("/")
        if fnmatch(path, base) or fnmatch(path, f"{base}/*") or Path(path).name == base:
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


def test_source_files_are_not_ignored():
    for path in ("src/novel_to_tavern/cli.py", "docs/PLAN.md", "config/config.example.yaml"):
        assert not _is_ignored(path), path
