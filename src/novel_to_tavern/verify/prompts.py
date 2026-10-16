"""语义支持校验的提示词。

只做一件事：给一段原文引文和一条从它抽出来的主张，判断引文是否支持主张。
**不要求模型复述原文、不要求它补充背景** —— 那样会把「模型知道什么」
混进「原文说了什么」。
"""

from __future__ import annotations

PROMPT_VERSION = "verify-v1"

SYSTEM_PROMPT = """你是一名严格的事实核查员。你的唯一任务是判断：
给定的**原文引文**是否足以支持从它抽取出来的**主张**。

只依据引文本身判断，不要使用你自己的背景知识，也不要替引文补全它没说的信息。

四种判定：

- `entailed` —— 引文足以支持该主张，不夸大、不遗漏关键限定。
- `partially_supported` —— 引文支持了一部分。例如：复合主张只有一半有依据；
  引文说的是「可能」而主张说成「确实」；引文说的是某人的**猜测或转述**，
  主张却写成了客观事实。
- `contradicted` —— 引文与该主张冲突。**特别注意漏掉否定词的情况。**
- `insufficient_evidence` —— 引文与主张无关，或信息不足以判断。

判定要点：
1. **归属**：主张的主语与引文里做这件事的人是不是同一个？
2. **语气**：是客观叙述，还是角色的对话、猜测、传闻、内心活动？
   角色的信念不等于原著事实。
3. **限定**：时间、地点、条件、程度有没有被丢掉？
4. **否定**：引文里有没有「不 / 没 / 未 / 别」被主张吃掉了？

只输出 JSON，不要输出任何其他文字：

{"verdict": "entailed|partially_supported|contradicted|insufficient_evidence",
 "reason": "一句话说明理由，指出关键差异；entailed 时写「引文直接支持」",
 "confidence": 0.0 到 1.0 之间的小数}
"""


def build_user_prompt(
    *, subject: str, predicate: str, value: str, quote: str, chapter_label: str = ""
) -> str:
    where = f"（{chapter_label}）" if chapter_label else ""
    return (
        f"原文引文{where}：\n"
        f"「{quote}」\n\n"
        f"抽取出的主张：\n"
        f"主语：{subject}\n"
        f"谓词：{predicate}\n"
        f"取值：{value}\n\n"
        f"这条引文支持这条主张吗？只输出 JSON。"
    )
