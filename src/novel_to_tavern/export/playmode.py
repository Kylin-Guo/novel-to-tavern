"""游玩模式：canon / branch / freeform。

**为什么要显式区分。** 导出的角色卡里混着两类东西：

- **原著 canon** —— 有原文引文支撑、经过证据定位的事实；
- **本次游玩新产生的** —— 用户扮演带来的分支事件、模型即兴的补充。

两者混进同一段文字之后就无法再分开：分不清哪句是原著、哪句是即兴，
回到 canon 重开一局时也没法确定「哪些该丢掉」。所以：

1. 模式**写进产物**（卡面描述、导出清单、审计报告），用户看得见自己拿到的是哪一种；
2. 条目正文**只取 canon**（`fact_type == "canon_fact"`），
   `user_added` / `reconstructed` / `inference` 一律不进 —— 这条在
   `worldbible._render_facts` 里强制执行；
3. 分支数据**只增不改**：新事件挂在新的 id 上，不覆盖任何 canon 事件。
   本项目目前不写入分支数据（那是客户端运行时的事），但把规则先钉在这里。
"""

from __future__ import annotations

from typing import Literal

PlayMode = Literal["canon_start", "branch_start", "freeform_start"]

#: 各模式的承诺。**只写能做到的**，不写「保证不偏离原著」这种做不到的话。
MODE_SPEC: dict[str, dict[str, str]] = {
    "canon_start": {
        "label": "严格原著线",
        "promise": "起点由用户选择；世界按原著设定运转。用户仍可自由行动，但设定不因情节方便而改动。",
        "caveat": "「按原著」是设定层面的一致，**不是**剧情层面的强制 —— 用户一开口就已经在分支了。",
    },
    "branch_start": {
        "label": "分支线（默认）",
        "promise": "原著走向作为参考，不强制遵循；新事件与原著事件分开对待。",
        "caveat": "分支事件可能与原著后续冲突，这是设计意图，不是缺陷。",
    },
    "freeform_start": {
        "label": "自由线",
        "promise": "只借用人物与设定，不承诺剧情走向。",
        "caveat": "自由线里原著剧情只作背景资料，仍可能被触发条目带入上下文。",
    },
}


def describe_mode(mode: str) -> str:
    spec = MODE_SPEC.get(mode, MODE_SPEC["branch_start"])
    return f"{spec['label']}：{spec['promise']}（{spec['caveat']}）"


def mode_block(mode: str) -> dict[str, str]:
    """写进导出清单的模式说明。"""
    spec = MODE_SPEC.get(mode, MODE_SPEC["branch_start"])
    return {
        "mode": mode,
        "label": spec["label"],
        "promise": spec["promise"],
        "caveat": spec["caveat"],
        "canon_policy": (
            "条目正文只取 fact_type=canon_fact 的事实；"
            "user_added / reconstructed / inference / rumor / character_belief "
            "一律不进条目正文"
        ),
        "branch_policy": (
            "分支数据只增不改：新事件使用新 id，不覆盖任何 canon 事件；"
            "本项目不写入分支数据，运行时的即兴内容由客户端负责区分"
        ),
    }


def mode_notice(mode: str) -> str:
    """追加到角色卡描述末尾的一段话，让用户在卡面就能看到模式。"""
    spec = MODE_SPEC.get(mode, MODE_SPEC["branch_start"])
    return f"\n\n游玩模式：{spec['label']}。{spec['promise']}"
