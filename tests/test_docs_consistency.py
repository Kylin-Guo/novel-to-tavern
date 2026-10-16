"""文档与产物不得互相矛盾。

这一组测试锁住的是「文档漂移」这一类缺陷 —— 代码改了、产物重导了，
README / 运行报告 / 导入清单里的数字和结论却还停在上一版。
人眼很难发现这类不一致，所以用测试兜底。

只断言**具体的、可计算的**事实（条目数、文件名、验证状态措辞），
不断言文风，也不做整文件快照。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CARD_PATH = REPO_ROOT / "exports" / "天之炽" / "world_simulator_v2.json"
FIXTURE_PATH = REPO_ROOT / "examples" / "fixtures" / "minimal_world_simulator_v2.json"
README = REPO_ROOT / "README.md"
RUN_REPORT = REPO_ROOT / "docs" / "RUN_REPORT.md"
CHECKLIST = REPO_ROOT / "docs" / "TAVO_IMPORT_CHECKLIST.md"
EXPORTS_README = REPO_ROOT / "exports" / "README.md"
NOTICE = REPO_ROOT / "NOTICE.md"

#: 文档里声明的离线测试数。三处必须一致，且等于实际收集到的用例数。
TEST_COUNT_DOCS = {
    README: r"(\d[\d,]*)\s*项离线",
    RUN_REPORT: r"(\d[\d,]*)\s*项离线",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def card_entries() -> list[dict]:
    payload = json.loads(_read(CARD_PATH))
    return payload["data"]["character_book"]["entries"]


@pytest.fixture(scope="module")
def collected_test_count() -> int:
    """实际收集到的用例数。跑一次 `--collect-only`，不执行任何用例。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    assert match, f"无法解析收集结果：\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    return int(match.group(1))


# --- 主卡的结构不变量 ------------------------------------------------------


def test_exported_card_exists():
    assert CARD_PATH.is_file(), "导出的主卡不在仓库里，README 却链接了它"


def test_card_is_v2_with_embedded_book(card_entries):
    payload = json.loads(_read(CARD_PATH))
    assert payload["spec"] == "chara_card_v2"
    assert payload["spec_version"] == "2.0"
    assert card_entries, "内嵌世界书是空的"


def test_every_entry_carries_the_fields_that_fail_silently(card_entries):
    """缺 `enabled` 会永久禁言，`position` 写数字会被静默当成 after_char。"""
    for entry in card_entries:
        assert entry.get("enabled") is True, f"条目未显式启用：{entry.get('comment')!r}"
        assert isinstance(entry["position"], str), f"position 不是字符串：{entry.get('comment')!r}"
        assert entry["position"] in {"before_char", "after_char"}
        assert (entry.get("comment") or "").strip(), "条目标题为空，客户端会显示成无标题条目"
        assert (entry.get("content") or "").strip(), f"条目正文为空：{entry.get('comment')!r}"


def test_entry_ids_are_sequential(card_entries):
    assert [e["id"] for e in card_entries] == list(range(len(card_entries)))


def test_non_constant_entries_have_trigger_keys(card_entries):
    """非常驻条目必须有键，否则永远不触发 —— 这种死条目曾经出现过 839 条。"""
    dead = [e["comment"] for e in card_entries if not e.get("constant") and not e.get("keys")]
    assert dead == [], f"存在永不触发的死条目：{dead[:5]}"


# --- 数字一致性 ------------------------------------------------------------


def _entry_counts(text: str) -> set[int]:
    """文中与「条目」二字相邻的数字（前后各 40 字符内）。

    只用于确认「真实条目数在文中出现过」，不做全文数字校验 ——
    运行报告里会合法地出现历史数字（508 → 266）和别的量纲。
    """
    found: set[int] = set()
    for match in re.finditer("条目", text):
        window = text[max(0, match.start() - 40) : match.end() + 40]
        for raw in re.findall(r"\d[\d,]*", window):
            found.add(int(raw.replace(",", "")))
    return found


def test_entry_count_in_docs_matches_the_card(card_entries):
    expected = len(card_entries)
    for path in (README, RUN_REPORT, EXPORTS_README):
        stated = _entry_counts(_read(path))
        assert expected in stated, (
            f"{path.name} 没有把真实条目数 {expected} 写在「条目」旁边；"
            f"相邻数字是 {sorted(stated)}"
        )


def test_constant_entry_count_in_docs_matches_the_card(card_entries):
    expected = len([e for e in card_entries if e.get("constant")])
    for path in (README, RUN_REPORT, EXPORTS_README, CHECKLIST):
        text = _read(path)
        stated = {int(n) for n in re.findall(r"常驻\s*(\d+)", text)}
        assert expected in stated, f"{path.name} 的常驻条目数与实际 {expected} 不符：{sorted(stated)}"


def test_docs_agree_on_the_offline_test_count(collected_test_count):
    for path, pattern in TEST_COUNT_DOCS.items():
        stated = {int(n.replace(",", "")) for n in re.findall(pattern, _read(path))}
        assert collected_test_count in stated, (
            f"{path.name} 声明的测试数 {sorted(stated)} 与实际收集到的 {collected_test_count} 不符"
        )


def test_run_report_standalone_counts_match_the_local_run_files():
    """独立世界书的条目数必须与同一次运行的产物一致（产物不在则跳过）。"""
    export_dir = REPO_ROOT / "runs" / "20261016T043701Z_aead30" / "exports"
    standalone = export_dir / "worldbook_standalone.json"
    beginning = export_dir / "worldbook_start_beginning.json"
    if not standalone.is_file() or not beginning.is_file():
        pytest.skip("本机没有那次运行的独立世界书产物")

    text = _read(RUN_REPORT)
    for path in (standalone, beginning):
        payload = json.loads(_read(path))
        entries = payload["entries"]
        count = len(entries)
        assert f"| {count}（常驻" in text or f"| {count}（" in text, (
            f"{path.name} 实际有 {count} 条，运行报告里没有这个数字"
        )


# --- 导入清单：文件名与状态 ------------------------------------------------


def test_checklist_imports_the_real_card_not_the_fixture():
    text = _read(CHECKLIST)
    assert "选 `world_simulator_v2.json`" in text, "导入步骤没有指向真实的主卡文件"
    # fixture 只能作为 fixture 出现，不能出现在「选这个文件」的导入动作里
    for line in text.splitlines():
        if "minimal_world_simulator_v2.json" in line:
            assert "不是" in line or "fixture" in line, (
                f"导入步骤疑似指向了 fixture：{line.strip()!r}"
            )


def test_checklist_no_longer_denies_the_observed_import():
    """导入已经实测过，清单不能还写着「尚未执行」「不得声称导入成功」。"""
    text = _read(CHECKLIST)
    for stale in ("尚未执行", "没有任何 Tavo 实测记录", "不得声称导入成功"):
        assert stale not in text, f"清单里还残留过时说法：{stale!r}"
    assert "已验证" in text


def test_checklist_separates_fixture_from_full_output():
    """fixture 是 4 条，真产物是 180 条，两者不得混写。"""
    fixture_entries = json.loads(_read(FIXTURE_PATH))["data"]["character_book"]["entries"]
    assert len(fixture_entries) == 4, "fixture 的条目数变了，文档里的说明需要同步"

    text = _read(CHECKLIST)
    assert "fixture" in text.lower()
    assert "180" in text and "4" in text


def test_checklist_distinguishes_the_unverified_runtime_behaviour():
    text = _read(CHECKLIST)
    for level in ("常驻条目每轮注入", "关键词 / 别名触发", "不误触发", "起始点剧透行为"):
        assert level in text, f"清单缺少验证等级：{level}"
    assert "未验证" in text


# --- 剧透：不得再写过头的承诺 ----------------------------------------------


def test_readme_does_not_promise_spoiler_proof():
    text = _read(README)
    assert "不会把后面的剧情或秘密泄露给早期角色" not in text, "README 还在承诺无剧透"
    assert "不是访问控制" in text, "README 必须写明时间纪律不是访问控制"


def test_readme_separates_quote_location_from_correctness():
    text = _read(README)
    assert "来源定位" in text
    assert "语义蕴含评估" in text
    assert "没有" in text or "未做" in text


def test_run_report_explains_what_the_metric_does_not_prove():
    text = _read(RUN_REPORT)
    assert "未证明" in text or "没有做语义蕴含评估" in text or "没有" in text
    assert "来源定位" in text


def test_docs_do_not_claim_tavo_runtime_behaviour_is_verified():
    """任何文档都不得把触发/常驻/剧透写成已验证。"""
    forbidden = [
        "触发命中已验证",
        "常驻条目已验证",
        "剧透防护已验证",
        "Tavo 完全兼容",
    ]
    for path in (README, RUN_REPORT, CHECKLIST, EXPORTS_README):
        text = _read(path)
        for phrase in forbidden:
            assert phrase not in text, f"{path.name} 声称了未验证的行为：{phrase!r}"


# --- 入库范围 --------------------------------------------------------------


def test_run_report_no_longer_claims_the_card_was_not_committed():
    text = _read(RUN_REPORT)
    assert "未提交到 GitLab" not in text
    assert "已发布" in text or "确实发布" in text


def test_exports_readme_states_the_card_is_published_and_provides_a_takedown_path():
    text = _read(EXPORTS_README)
    assert "已发布" in text or "发布在本公开仓库" in text
    assert "移除" in text, "导出的衍生作品必须写明权利人可要求移除"


def test_notice_lists_the_derivative_file_and_keeps_it_out_of_mit():
    text = _read(NOTICE)
    assert "exports/天之炽/world_simulator_v2.json" in text
    assert "不在 MIT 授权范围内" in text
    assert "Git 历史" in text, "应说明历史清理的意愿"
