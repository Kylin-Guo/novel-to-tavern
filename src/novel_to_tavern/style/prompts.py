"""作者风格蒸馏的四个版本化提示词。

版本号与模板 hash 都进入缓存键：改提示词必然使旧缓存失效。
行号永远由代码定位（`extract.evidence.locate_quote`），提示词不要求模型输出行号。
"""

from __future__ import annotations

import hashlib
import json

PROMPT_VERSION_OBSERVE = "style-observe-v1"
PROMPT_VERSION_MERGE = "style-merge-v1"
PROMPT_VERSION_COMPILE = "style-compile-v1"
PROMPT_VERSION_COMPRESS = "style-compress-v1"


SYSTEM_PROMPT_OBSERVE = """你是一个文学风格分析器。你只分析给定章节正文的**写作风格**，
不复述剧情、不提取人物或事件事实、不评价好坏。

对下面七个维度各给 1–3 条**可操作**的规律（「怎么写」，而不是「写得好」）：
- narrative_voice：叙述视角与人称、叙述者与故事的距离
- sentence_rhythm：句长、断句、段落节奏
- description_patterns：环境与感官描写的取景方式
- figurative_language：比喻、意象、修辞的用法
- dialogue_patterns：对白长度、潜台词、对话中的动作
- psychological_narration：内心活动如何呈现
- scene_pacing：场景推进、转场、高潮与收束

硬性规则：
1. 只输出 JSON，不要解释、前后缀或 Markdown 代码块。
2. 证据不足的维度填 "unknown"，**禁止编造**。
3. 每条规律尽量附 1 条 ≤40 字的**逐字**引文，放进 evidence：
   {"aspect": "维度名", "quote": "原文片段"}。
   引文必须逐字来自正文，不得改写、不得拼接不相邻的两段话。
4. notable_motifs（反复出现的意象/母题）与 anti_patterns_observed
   （本段明显回避的写法）可为空数组。
5. 字段名与下面结构一致，不多字段：

{
  "narrative_voice": "…",
  "sentence_rhythm": "…",
  "description_patterns": "…",
  "figurative_language": "…",
  "dialogue_patterns": "…",
  "psychological_narration": "…",
  "scene_pacing": "…",
  "notable_motifs": ["…"],
  "anti_patterns_observed": ["…"],
  "evidence": [{"aspect": "sentence_rhythm", "quote": "原文逐字片段"}]
}"""


SYSTEM_PROMPT_MERGE = """你是一个文学风格分析器的合并环节。输入是同一部作品的若干份
章节级风格观察。请合并同类规律、去重、**保留分歧**：卷间或场景差异写进
contextual_variants，不得新造观察里没有的规律。

硬性规则：
1. 只输出 JSON，不要解释或 Markdown 代码块。
2. 每个维度输出 {"summary": "一句话概括", "rules": ["可操作规律"], "confidence": "high|medium|low|unknown"}。
3. 证据互相矛盾或样本太薄时**降低 confidence**，不要强行统一成高置信度。
4. 只使用输入里出现过的规律；输入里没有的写法不得凭空补充。
5. 结构：

{
  "dimensions": {
    "narrative_voice": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "sentence_rhythm": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "description_patterns": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "figurative_language": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "dialogue_patterns": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "psychological_narration": {"summary": "…", "rules": ["…"], "confidence": "medium"},
    "scene_pacing": {"summary": "…", "rules": ["…"], "confidence": "medium"}
  },
  "contextual_variants": ["…"],
  "anti_patterns": ["…"],
  "motifs": ["…"]
}"""


SYSTEM_PROMPT_COMPILE = """你把分批风格笔记整理成一份**小说叙事风格档案**（StyleProfile）。

硬性要求：
1. 小说文本观察是主要证据。补充资料（若有）是外部证据；
   作者自述不得自动升格为作品风格事实，交叉检查结论写进 limitations。
2. anti_patterns 写「与本作风格不相容的生成倾向 + 理由」。
3. 不写具体剧情事实，不复制原著句子。风格规则描述「怎么写」，不描述「写了什么」。
4. 证据不足的维度 summary 填 "unknown"、confidence 填 "unknown"，不强行填值。
5. 同时产出：
   a. runtime_rules：注入角色卡的**精简**运行时风格规范。用行为规则
      （如何组织段落、控制揭露节奏、描写情绪），不用形容词清单；
      旁白风格与 NPC 台词风格分开；不重复世界运行规则与人物事实；
      附一句「不生搬统计指标，优先保留情境功能」；目标不超过给定 token 预算。
   b. eval_cases：至少 6 个，覆盖场景铺陈/人物对话/内心活动/冲突/
      情绪克制爆发/场景收束；expected_traits 写抽象规律，不得用原文逐字匹配。
6. 只输出 JSON，不要解释或 Markdown 代码块。inputs_fingerprint 留空字符串，由代码填。
7. 结构：

{
  "schema_version": "style_profile_v1",
  "profile_id": "",
  "author_label": "…",
  "works_in_scope": ["…"],
  "created_at": "",
  "source_manifest": [{"kind": "novel", "locator": "…", "detail": "…"}],
  "narrative_voice": {"summary": "…", "rules": ["…"], "confidence": "high"},
  "sentence_rhythm": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "description_patterns": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "figurative_language": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "dialogue_patterns": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "psychological_narration": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "scene_pacing": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "genre_tone": {"summary": "…", "rules": ["…"], "confidence": "medium"},
  "anti_patterns": ["…"],
  "contextual_variants": ["…"],
  "limitations": ["…"],
  "human_review_items": ["…"],
  "runtime_rules": "…",
  "eval_cases": [
    {"case_id": "case_01", "scenario_type": "场景铺陈",
     "instruction": "写一段…", "expected_traits": ["…"], "anti_patterns": ["…"]}
  ],
  "inputs_fingerprint": ""
}"""


SYSTEM_PROMPT_COMPRESS = """把给定的运行时风格规范压缩到不超过 N token（CJK 约 1 字 1 token）。

硬性规则：
1. 优先保留高置信度、可执行、具情境功能的规则，删掉重复与形容词堆砌。
2. 删除高置信度规则必须给出理由。
3. 只输出 JSON，不要解释：

{"runtime_rules": "压缩后的规范正文", "dropped": ["被删规律及理由"]}"""


def build_observe_user_prompt(
    *, book_title: str, chapter_label: str, chapter_title: str, text: str
) -> str:
    return f"""作品：{book_title}
章节：{chapter_label}{chapter_title}

正文：
{text}"""


def build_merge_user_prompt(*, observations_json: str) -> str:
    return f"""以下是同一部作品的章节级风格观察（JSON 数组）。
请按系统提示合并。不要引入输入里没有的规律。

{observations_json}"""


def build_compile_user_prompt(
    *,
    batch_notes_json: str,
    digests: list[str],
    supplementary: str = "",
    max_runtime_tokens: int,
) -> str:
    digest_block = "\n".join(f"- {line}" for line in digests) or "（无章节摘要）"
    supplementary_block = supplementary.strip() or "（无补充资料）"
    return f"""分批风格笔记（JSON 数组）：
{batch_notes_json}

章节摘要清单（仅供语境，不要复述剧情）：
{digest_block}

补充资料（作者访谈/创作谈；外部证据，必须与小说文本交叉检查）：
{supplementary_block}

runtime_rules 的 token 预算：不超过 {max_runtime_tokens}。"""


def build_compress_user_prompt(*, runtime_rules: str, max_tokens: int) -> str:
    return f"""需要压缩到不超过 {max_tokens} token 的运行时风格规范：

{runtime_rules}"""


def prompt_template_hash() -> str:
    """四个模板文本 + 四个版本号的 sha256。

    只写版本号容易漏：改了提示词却忘了改版本号，缓存会命中旧结果，
    修复看起来「没生效」。
    """
    payload = json.dumps(
        {
            "observe": [PROMPT_VERSION_OBSERVE, SYSTEM_PROMPT_OBSERVE,
                        build_observe_user_prompt(
                            book_title="{book_title}", chapter_label="{chapter_label}",
                            chapter_title="{chapter_title}", text="{text}")],
            "merge": [PROMPT_VERSION_MERGE, SYSTEM_PROMPT_MERGE,
                      build_merge_user_prompt(observations_json="{observations}")],
            "compile": [PROMPT_VERSION_COMPILE, SYSTEM_PROMPT_COMPILE,
                        build_compile_user_prompt(
                            batch_notes_json="{batch_notes}", digests=["{digest}"],
                            supplementary="{supplementary}", max_runtime_tokens=0)],
            "compress": [PROMPT_VERSION_COMPRESS, SYSTEM_PROMPT_COMPRESS,
                         build_compress_user_prompt(runtime_rules="{rules}", max_tokens=0)],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
