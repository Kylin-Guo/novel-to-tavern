"""风格测试的共享装置：合成档案、预生成响应、离线引擎。

全部为自创内容，不含任何真实作品片段。
"""

from __future__ import annotations

import json

from novel_to_tavern.llm import Completion, MissingResponseError
from novel_to_tavern.style import STYLE_DIMENSIONS

DIMENSIONS = (*STYLE_DIMENSIONS, "genre_tone")


def dimension(summary="一条可操作规律", confidence="medium"):
    return {"summary": summary, "rules": [f"{summary}（行为规则）"], "confidence": confidence}


def style_profile_payload(**overrides) -> dict:
    payload = {
        "schema_version": "style_profile_v1",
        "profile_id": "",
        "author_label": "测试作者",
        "works_in_scope": ["novel.txt"],
        "created_at": "",
        "source_manifest": [{"kind": "novel", "locator": "novel.txt", "detail": ""}],
        "anti_patterns": ["避免爽文式的连续短句轰炸"],
        "contextual_variants": ["战斗场景句子更短"],
        "limitations": ["样本只覆盖测试章节"],
        "human_review_items": ["确认 narrative_voice 的置信度"],
        "runtime_rules": "旁白用短句；对白留白，不解释潜台词。",
        "eval_cases": [
            {
                "case_id": f"case_{index:02d}",
                "scenario_type": scenario,
                "instruction": f"写一段{scenario}。",
                "expected_traits": ["先给感官，再给人物"],
                "anti_patterns": ["不要堆砌形容词"],
            }
            for index, scenario in enumerate(
                ["场景铺陈", "人物对话", "内心活动", "冲突", "情绪克制爆发", "场景收束"],
                start=1,
            )
        ],
        "inputs_fingerprint": "",
    }
    for dim in DIMENSIONS:
        payload[dim] = dimension()
    payload.update(overrides)
    return payload


def merge_payload() -> dict:
    return {
        "dimensions": {
            dim: dimension(summary=f"{dim} 的合并结论") for dim in STYLE_DIMENSIONS
        },
        "contextual_variants": ["卷一的句子更短"],
        "anti_patterns": ["避免写成说明文"],
        "motifs": ["风", "灯"],
    }


def observation_payload() -> dict:
    return {
        "narrative_voice": "第三人称限知。",
        "sentence_rhythm": "短句为主。",
        "description_patterns": "环境先于人物。",
        "figurative_language": "比喻克制。",
        "dialogue_patterns": "对白短。",
        "psychological_narration": "以动作暗示内心。",
        "scene_pacing": "对话后收束。",
        "notable_motifs": ["风"],
        "anti_patterns_observed": ["不堆砌形容词"],
        "evidence": [{"aspect": "sentence_rhythm", "quote": "风从河面吹过来。"}],
    }


class DictProvider:
    """按 chunk_id 返回预生成 JSON 的离线引擎。"""

    name = "stub"
    endpoint_fingerprint = "stub"

    def __init__(self, responses: dict):
        self.responses = dict(responses)
        self.calls = 0
        self.chunk_ids: list[str] = []

    def complete(self, *, chunk_id, system_prompt, user_prompt):
        self.calls += 1
        self.chunk_ids.append(chunk_id)
        if chunk_id not in self.responses:
            raise MissingResponseError(f"no response for {chunk_id}")
        value = self.responses[chunk_id]
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return Completion(text=text, model="stub-model")
