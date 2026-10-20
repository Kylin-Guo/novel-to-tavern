"""作者风格 schema：严格字段、未知维度、评估样例。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from novel_to_tavern.style.schema import (
    RawStyleObservation,
    StyleDimension,
    StyleEvalCase,
    StyleProfile,
)


def _dim(summary="一句话概括", confidence="medium"):
    return StyleDimension(summary=summary, rules=["一条可操作规律"], confidence=confidence)


def _profile() -> StyleProfile:
    return StyleProfile(
        profile_id="style-abc123",
        author_label="测试作者",
        works_in_scope=["测试纪事"],
        created_at="2026-10-20T00:00:00+00:00",
        source_manifest=[{"kind": "novel", "locator": "sample_novel.txt"}],
        narrative_voice=_dim(),
        sentence_rhythm=_dim(),
        description_patterns=_dim(),
        figurative_language=_dim(),
        dialogue_patterns=_dim(),
        psychological_narration=_dim(),
        scene_pacing=_dim(),
        genre_tone=_dim(),
        anti_patterns=["不要写成网文爽文节奏"],
        contextual_variants=["战斗场景句子更短"],
        limitations=["只有三章样本"],
        human_review_items=["narrative_voice 的置信度需要人工确认"],
        runtime_rules="旁白用短句；对白留白。",
        eval_cases=[
            {
                "case_id": "case_01",
                "scenario_type": "场景铺陈",
                "instruction": "写一段渡口清晨。",
                "expected_traits": ["先给感官，再给人物"],
            }
        ],
        inputs_fingerprint="fp",
    )


def test_profile_roundtrip():
    profile = _profile()
    dumped = profile.model_dump(mode="json")
    assert StyleProfile.model_validate(dumped) == profile


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        RawStyleObservation.model_validate(
            {"narrative_voice": "第三人称", "unexpected_field": "多出来的"}
        )
    profile = _profile().model_dump(mode="json")
    profile["extra"] = 1
    with pytest.raises(ValidationError):
        StyleProfile.model_validate(profile)


def test_dimension_defaults_unknown():
    dim = StyleDimension()
    assert dim.summary == "unknown"
    assert dim.confidence == "unknown"
    assert dim.rules == []


def test_eval_case_min_fields():
    case = StyleEvalCase(
        case_id="case_01",
        scenario_type="人物对话",
        instruction="写一段两人试探彼此的对话。",
        expected_traits=["潜台词多于明说"],
    )
    assert case.anti_patterns == []

    with pytest.raises(ValidationError):
        StyleEvalCase(case_id="case_02", scenario_type="冲突", instruction="写一段冲突。")
