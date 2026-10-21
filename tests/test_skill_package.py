"""Agent Skill 分发包的完整性与功能性测试。

`skills/novel-to-tavern/` 是随仓库分发的 Agent Skill（Claude Code / Kimi Code 等）。
这组测试锁住：frontmatter 合法且与目录同名、SKILL.md 里引用的文件都真实存在、
evals 数据可解析、随附脚本语法正确且 `check_card.py` 对真产物/坏产物都给出
正确判定 —— 防止文档或脚本漂移后，用户装上一个「看起来是技能、实际跑不动」的包。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "novel-to-tavern"
SKILL_MD = SKILL_DIR / "SKILL.md"
REAL_CARD = REPO_ROOT / "exports" / "天之炽" / "world_simulator_v2.json"
FIXTURE_CARD = REPO_ROOT / "examples" / "fixtures" / "minimal_world_simulator_v2.json"

ALLOWED_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}


@pytest.fixture(scope="module")
def frontmatter() -> dict:
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert match, "SKILL.md 缺少 YAML frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


# --- frontmatter ------------------------------------------------------------


def test_skill_directory_and_skill_md_exist():
    assert SKILL_DIR.is_dir(), "skills/novel-to-tavern/ 不存在"
    assert SKILL_MD.is_file(), "SKILL.md 不存在"


def test_frontmatter_only_uses_allowed_keys(frontmatter):
    unexpected = set(frontmatter) - ALLOWED_FRONTMATTER_KEYS
    assert not unexpected, f"frontmatter 出现不允许的键：{sorted(unexpected)}"


def test_skill_name_matches_directory_and_is_kebab_case(frontmatter):
    name = frontmatter["name"]
    assert name == SKILL_DIR.name, "name 必须与目录同名，否则装上后引用混乱"
    assert re.fullmatch(r"[a-z0-9-]+", name), "name 必须是 kebab-case"
    assert len(name) <= 64


def test_description_within_limits_and_no_angle_brackets(frontmatter):
    description = frontmatter["description"].strip()
    assert description, "description 是技能的主要触发机制，不能为空"
    assert len(description) <= 1024, f"description 超长：{len(description)}"
    assert "<" not in description and ">" not in description


def test_compatibility_within_limits(frontmatter):
    compatibility = (frontmatter.get("compatibility") or "").strip()
    assert compatibility, "本技能有 Python/git/凭据前置条件，compatibility 应写明"
    assert len(compatibility) <= 500


# --- SKILL.md 引用完整性 -----------------------------------------------------


def test_files_referenced_in_skill_md_exist():
    text = SKILL_MD.read_text(encoding="utf-8")
    refs = set(re.findall(r"(references/[\w.-]+\.md|scripts/[\w.-]+)", text))
    assert refs, "SKILL.md 没有引用任何 references/ 或 scripts/ 文件"
    missing = [ref for ref in refs if not (SKILL_DIR / ref).is_file()]
    assert missing == [], f"SKILL.md 引用了不存在的文件：{missing}"


def test_skill_md_does_not_bind_a_remote_repository():
    """技能应当在哪都能跑：不硬编码 git clone / 仓库地址。"""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "git clone" not in text, "SKILL.md 不应包含 git clone 步骤"
    assert "github.com" not in text, "SKILL.md 不应硬编码远程仓库地址"


def test_skill_md_does_not_ask_user_for_credentials():
    """能调用技能的 Agent 本身就是 LLM：默认路径是 Agent 生成响应，不索要凭据。"""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "不主动向用户索要" in text, "SKILL.md 应明确不主动索要 API 凭据"
    assert "provider: file" in text, "SKILL.md 应把 file 引擎（Agent 即抽取模型）作为默认路径"


def test_skill_md_points_at_repo_docs_that_exist():
    """SKILL.md 提到仓库 docs/ 下的文件时，那些文件必须真实存在。"""
    text = SKILL_MD.read_text(encoding="utf-8")
    refs = set(re.findall(r"docs/[\w.-]+\.md", text))
    missing = [ref for ref in refs if not (REPO_ROOT / ref).is_file()]
    assert missing == [], f"SKILL.md 引用了不存在的仓库文档：{missing}"


# --- evals -------------------------------------------------------------------


def test_evals_json_is_valid_and_matches_skill():
    payload = json.loads((SKILL_DIR / "evals" / "evals.json").read_text(encoding="utf-8"))
    assert payload["skill_name"] == SKILL_DIR.name
    evals = payload["evals"]
    assert len(evals) >= 3, "至少 3 个真实用户语气的测试提示"
    ids = [e["id"] for e in evals]
    assert len(ids) == len(set(ids)), "eval id 重复"
    for e in evals:
        assert e["prompt"].strip() and e["expected_output"].strip()


# --- 随附脚本 -----------------------------------------------------------------


def test_pipeline_script_has_valid_bash_syntax():
    script = SKILL_DIR / "scripts" / "n2t_pipeline.sh"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash 语法错误：{result.stderr}"
    assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def _run_check_card(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SKILL_DIR / "scripts" / "check_card.py"), str(path)],
        capture_output=True,
        text=True,
    )


def test_check_card_accepts_the_published_card():
    result = _run_check_card(REAL_CARD)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "条目总数：188" in result.stdout


def test_check_card_accepts_the_minimal_fixture():
    result = _run_check_card(FIXTURE_CARD)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "条目总数：4" in result.stdout


def test_check_card_rejects_silently_broken_fields(tmp_path):
    """enabled 缺失 / position 写数字 / 死条目 —— 这些在客户端都不报错，必须被拦下。"""
    broken = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "坏卡",
            "character_book": {
                "entries": [
                    {"id": 0, "comment": "缺enabled", "content": "x", "position": "before_char", "keys": ["a"]},
                    {"id": 1, "comment": "数字position", "content": "x", "position": 0, "enabled": True, "keys": ["a"]},
                    {"id": 2, "comment": "死条目", "content": "x", "position": "after_char", "enabled": True},
                ]
            },
        },
    }
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")

    result = _run_check_card(path)
    assert result.returncode == 1
    assert "enabled" in result.stdout
    assert "position" in result.stdout
    assert "触发键" in result.stdout
