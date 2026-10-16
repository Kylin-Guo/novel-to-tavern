"""公开仓库的入库卫生：原文、运行产物、派生卡片各自该在哪里。

`.gitignore` 只约束**将来的** `git add`。这组测试换成从 `git ls-files`
反向校验**当前已入库**的内容 —— 忽略规则改坏了、或者有人 `git add -f` 过，
都会在这里暴露。

另外核对 Git **历史**：在公开仓库里删掉一个文件不会把它从历史里抹掉，
所以「现在没跟踪」不等于「从未泄露」。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 绝不允许出现在 Git 跟踪列表里的目录前缀。
NEVER_TRACKED = (
    "runs/",
    "precomputed/",
    "cache/",
    ".cache/",
    "nginx-exports/",
    "天之炽/",
    "input/",
    ".venv/",
    "build/",
    "dist/",
)

#: 允许入库的衍生产物白名单。原样列出，多一个都要先改这里并说明理由。
DERIVATIVE_ALLOWLIST = {
    "exports/README.md",
    "exports/天之炽/world_simulator_v2.json",
}

#: 内部标识符：出现在公开仓库里就是泄露。
INTERNAL_MARKERS = (
    "tech-trans",
    "tech_trans",
    "kylin-registry",
    "gitlab-devops",
    "Deployment-Agent",
    "/home/kylin",
    "/media/kylin",
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout


def _tracked_files() -> list[str]:
    return [line for line in _git("ls-files", "-z").split("\0") if line]


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    try:
        files = _tracked_files()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("不是 git 工作区，或没有 git 可执行文件")
    if not files:
        pytest.skip("git 跟踪列表为空")
    return files


# --- 当前跟踪列表 ----------------------------------------------------------


def test_no_runtime_or_source_material_is_tracked(tracked):
    offenders = [p for p in tracked if any(p.startswith(prefix) for prefix in NEVER_TRACKED)]
    assert offenders == [], f"这些路径不该入库（含原文/运行产物）：{offenders[:10]}"


def test_no_novel_text_files_are_tracked(tracked):
    """除了自创的测试夹具，不应有其它正文文本。"""
    allowed = {"tests/fixtures/sample_novel.txt"}
    novels = [p for p in tracked if p.endswith((".txt", ".md")) and "天之炽" in p]
    assert novels == [], f"疑似原文入库：{novels}"
    txts = {p for p in tracked if p.endswith(".txt")}
    assert txts <= allowed, f"出现未预期的 .txt：{sorted(txts - allowed)}"


def test_derivative_artifacts_live_only_under_exports(tracked):
    """世界书、时间线、审计报告这类含逐章剧情/逐字引文的产物一律不入库。

    `examples/fixtures/` 下同名的文件是自创的最小 fixture，不属于衍生内容。
    """
    for name in (
        "worldbook_standalone.json",
        "worldbook_start_beginning.json",
        "worldbook_start_after_ending.json",
        "timeline.json",
        "export_manifest.json",
    ):
        hits = [
            p for p in tracked if p.endswith(name) and not p.startswith("examples/")
        ]
        assert hits == [], f"{name} 不该入库：{hits}"


def test_exports_directory_contains_exactly_the_allowlisted_files(tracked):
    actual = {p for p in tracked if p.startswith("exports/")}
    assert actual == DERIVATIVE_ALLOWLIST, (
        f"exports/ 下的入库文件变了。实际 {sorted(actual)}，允许 {sorted(DERIVATIVE_ALLOWLIST)}"
    )


def test_the_published_card_is_the_only_derivative_sample(tracked):
    """唯一入库的衍生文件必须有明确的授权边界说明与其配对。"""
    card = REPO_ROOT / "exports" / "天之炽" / "world_simulator_v2.json"
    if not card.is_file():
        pytest.skip("没有入库的示例卡")
    assert (REPO_ROOT / "exports" / "README.md").is_file()
    assert "不在 MIT 授权范围内" in (REPO_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "移除" in (REPO_ROOT / "exports" / "README.md").read_text(encoding="utf-8")


def test_test_fixture_is_self_authored_and_tiny():
    """测试夹具必须是自创的占位文本，不能是原著切片。"""
    fixture = REPO_ROOT / "tests" / "fixtures" / "sample_novel.txt"
    assert fixture.is_file()
    assert fixture.stat().st_size < 20_000, "夹具过大，疑似真实原文"
    assert "测试纪事" in fixture.read_text(encoding="utf-8")


# --- 内容扫描 --------------------------------------------------------------


#: 本文件自己定义了这些标记串，扫描时要跳过，否则永远自报。
_SELF = "tests/test_repo_hygiene.py"


def test_no_internal_markers_in_tracked_files(tracked):
    """公司域名、内网主机名、本机绝对路径都不得出现在公开仓库里。"""
    offenders: list[str] = []
    for rel in tracked:
        if rel == _SELF:
            continue
        path = REPO_ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for marker in INTERNAL_MARKERS:
            if marker in text:
                offenders.append(f"{rel}: {marker}")
    assert offenders == [], f"公开仓库里出现内部标识符：{offenders}"


def test_tracked_json_parses(tracked):
    for rel in tracked:
        if not rel.endswith(".json") or rel.startswith("examples/"):
            continue
        raw = (REPO_ROOT / rel).read_text(encoding="utf-8")
        json.loads(raw)  # 解析失败会直接抛


# --- Git 历史 --------------------------------------------------------------


def test_history_never_contained_novel_source_or_run_outputs():
    """删除文件不会从历史里抹掉它，所以必须单独核对历史。"""
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        pytest.skip("浅克隆，历史不完整（CI 默认 fetch-depth=1）")

    added = _git("log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A")
    paths = [line.strip() for line in added.splitlines() if line.strip()]

    offenders = [
        p
        for p in paths
        if p.startswith(NEVER_TRACKED) or (p.endswith(".txt") and "天之炽" in p)
    ]
    assert offenders == [], f"历史上曾入库过原文或运行产物：{sorted(set(offenders))[:10]}"


def test_history_never_contained_other_derivative_artifacts():
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        pytest.skip("浅克隆，历史不完整")

    added = _git("log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A")
    paths = [line.strip().strip('"') for line in added.splitlines() if line.strip()]

    for name in (
        "worldbook_standalone.json",
        "worldbook_start_beginning.json",
        "worldbook_start_after_ending.json",
        "timeline.json",
        "export_manifest.json",
    ):
        hits = [p for p in paths if p.endswith(name) and not p.startswith("examples/")]
        assert hits == [], f"{name} 曾进过历史：{hits}"
