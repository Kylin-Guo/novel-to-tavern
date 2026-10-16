"""示例 fixture：能被解析、能通过严格校验、与 serializer 不漂移。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from novel_to_tavern.tavern import CardV2, WorldbookFile, dump_to, dumps, validate_card, validate_parity, validate_worldbook

REPO_ROOT = Path(__file__).resolve().parent.parent
CARD_PATH = REPO_ROOT / "examples" / "fixtures" / "minimal_world_simulator_v2.json"
WORLDBOOK_PATH = REPO_ROOT / "examples" / "fixtures" / "minimal_worldbook_standalone.json"


@pytest.fixture(scope="module")
def card() -> CardV2:
    return CardV2.model_validate(json.loads(CARD_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def worldbook() -> WorldbookFile:
    return WorldbookFile.model_validate(json.loads(WORLDBOOK_PATH.read_text(encoding="utf-8")))


def test_fixtures_exist():
    assert CARD_PATH.is_file()
    assert WORLDBOOK_PATH.is_file()


def test_card_is_strictly_valid(card):
    report = validate_card(card, strict=True, max_always_on=3)
    assert report.errors == []
    assert report.ok


def test_worldbook_is_strictly_valid(worldbook):
    report = validate_worldbook(worldbook, strict=True)
    assert report.errors == []


def test_card_and_worldbook_are_in_parity(card, worldbook):
    report = validate_parity(card, worldbook)
    assert report.errors == []


def test_card_has_expected_top_level_shape(card):
    raw = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    assert list(raw) == ["spec", "spec_version", "data"]
    assert raw["spec"] == "chara_card_v2"
    assert raw["spec_version"] == "2.0"
    assert card.data.character_book is not None
    assert len(card.data.character_book.entries) == 4


def test_worldbook_top_level_only_has_entries():
    """未实证的顶层键一律不加。"""
    raw = json.loads(WORLDBOOK_PATH.read_text(encoding="utf-8"))
    assert list(raw) == ["entries"]


def test_fixture_card_has_no_secret_like_strings():
    from novel_to_tavern.tavern import validate_no_secrets

    for path in (CARD_PATH, WORLDBOOK_PATH):
        assert validate_no_secrets(path.read_text(encoding="utf-8")).errors == []


def test_dump_to_produces_byte_identical_file(tmp_path, card, worldbook):
    """序列化必须是确定性的：同样输入 → 同样字节。"""
    out_card = dump_to(tmp_path / "card.json", card)
    assert out_card.read_text(encoding="utf-8") == CARD_PATH.read_text(encoding="utf-8")

    out_wb = dump_to(tmp_path / "book.json", worldbook, exclude_none=False)
    assert out_wb.read_text(encoding="utf-8") == WORLDBOOK_PATH.read_text(encoding="utf-8")


def test_fixtures_do_not_drift_from_serializer():
    """fixture 必须与 tools/build_example_fixtures.py 的输出保持一致。"""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "build_example_fixtures.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_roundtrip_is_stable_for_both_fixtures(card, worldbook):
    assert dumps(CardV2.model_validate(json.loads(dumps(card)))) == dumps(card)
    assert dumps(WorldbookFile.model_validate(json.loads(dumps(worldbook, exclude_none=False))), exclude_none=False) == dumps(
        worldbook, exclude_none=False
    )
