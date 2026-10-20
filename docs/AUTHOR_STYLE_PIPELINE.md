# 作者风格自动蒸馏

> 这是**旁路资料流**，默认关闭。风格资料不是 canon：不写 facts / entities /
> timeline / knowledge，不改变任何原著事实。**「蒸馏成功」不等于「与作者文风完全一致」。**

## 1. 方法来源与取舍

方法论参考 [nuwa-skill](https://github.com/alchaincyf/nuwa-skill)（MIT，检索日期 2026-10-20）。
本仓库**不分发、不导入**其代码或产物，也没有 `style-import` 命令 —— 蒸馏由本项目
自己的 LLM 管线完成。

| Nuwa 的概念 | 本仓库的落点 | 说明 |
|---|---|---|
| 表达 DNA | 七个观察维度（`narrative_voice` / `sentence_rhythm` / `description_patterns` / `figurative_language` / `dialogue_patterns` / `psychological_narration` / `scene_pacing`） | 逐块观察，证据不足填 `unknown` |
| 反模式 | `anti_patterns` / `anti_patterns_observed` | 写「与本作不相容的生成倾向 + 理由」 |
| 诚实边界 | `limitations` / `human_review_items` / `audit.md` | 证据薄、样本少、补充资料冲突都写出来 |
| 心智模型 / 决策启发式 / Agentic Protocol | **不采用** | 面向咨询与实时调研，与小说旁白无关 |
| 多 Agent 调研编排 | **不采用** | 本项目是单模型、可恢复的本地 CLI |

## 2. 管线

```text
observations/*.json   ← style-observe（逐分块，带逐字引文证据）
      │                 引文用 locate_quote 在原文里定位；定位失败丢弃并计数
      ▼
merged/batch_*.json   ← style-merge（每批 merge_batch_size 份）
      ▼
style_profile.json    ← style-compile（完整档案 + runtime_rules + eval_cases）
      │                 runtime 超预算时 → style-compress → 仍超则报错，不截断
      ├─ style_profile.md            人工阅读版
      ├─ runtime_style_prompt.md     注入 Description 的唯一风格主体
      ├─ style_worldbook_entries.json 8 组触发式条目
      ├─ style_eval_cases.json       ≥6 个评估样例
      └─ audit.md                    覆盖率 / 置信度 / 丢弃项 / 局限 / 复核项
```

产物目录：`runs/<run_id>/author_style/`。

## 3. 操作

### 3.1 开启自动蒸馏

```yaml
style:
  enabled: true
  max_runtime_tokens: 800   # 【叙事风格规范】粗估上限；超出自动压缩，再超报错
  worldbook_entries: true   # 8 组完整档案进世界书（触发式，非常驻）
  observe_max_chunks: 0     # 0 = 全部；>0 时确定性等距抽样
  merge_batch_size: 30
  supplementary_path: null  # 可选：作者访谈/创作谈笔记（外部证据）
```

之后正常跑 `n2t export --run-id <run_id>`：

- 风格产物**缺失或过期** → 自动执行 `style-observe → style-compile`；
- 产物**新鲜** → 直接加载，**不需要凭据**；
- 产物过期且没有可用引擎 → 报错中止，不静默产出「没有风格规范」的卡。

### 3.1.1 Description 的组成

开启后 Description 的顺序固定为：

1. **【写作要求：作者风格】** —— 放在最开头，要求模型尽量模仿该作品的文风，
   并明确指向世界书里标题以「作者风格：」开头的 8 组条目（提到作者风格 /
   叙事风格 / 语言风格 / 文风特点 / 写作风格 时触发）。
2. 原有的世界模拟器说明与游玩模式提示。
3. **【叙事风格规范】** —— 精简运行时规则（`max_runtime_tokens` 约束）。

完整档案在世界书条目里，Description 只放「去读它们」的指令和精简规范，
避免每轮重复整份档案。严格起始点档同样把写作要求放在开头。

### 3.2 分步执行

```bash
n2t style-observe --run-id <run_id>              # 先观察
n2t style-compile --run-id <run_id>              # 再编译
n2t style-compile --run-id <run_id> --no-resume  # 清掉产物（保留 observations/）后重编译
```

`style-observe` 失败分块非空时退出码为 1；失败响应隔离在
`author_style/observations/_errors/`，不会被当成成功。

### 3.3 离线预生成（file provider）

没有 API 凭据时，把预生成响应放进 `llm.precomputed_responses_dir`，
文件名即 `chunk_id`：

| 阶段 | 文件名 |
|---|---|
| 观察 | `<chunk_id>.json` |
| 合并 | `style_merge_batch_000.json`、`style_merge_batch_001.json` … |
| 编译 | `style_compile.json` |
| 压缩 | `style_compress.json` |

`FileProvider` 是正式路径，不是测试替身；报告会如实标注 `provider=file`。

## 4. 缓存与指纹

### 4.1 缓存键

四个阶段共用 `style/cache.py`，键包含：

```text
阶段 kind · 模型 · endpoint 指纹 · 提示词版本 · 提示词模板 sha256
观察 schema 版本 · 档案 schema 版本 · 输入内容 sha256 · temperature
输出长度上限 · 阶段附加项（chunk sha / batch index / 预算 / 补充资料 sha）
```

改提示词却忘改版本号也会失效 —— 模板 hash 单独参与。

### 4.2 `inputs_fingerprint`（产物新鲜度）

写入 `style_profile.json`，由以下内容拼接后 sha256：

```text
四个提示词版本 + 模板 hash + 两个 schema 版本 + 模型 + endpoint（调用方给）
+ 全部来源 sha256 + observe_max_chunks + merge_batch_size
+ max_runtime_tokens + 补充资料 sha256
```

导出时的判定**不使用** endpoint（新鲜产物必须在没有凭据时也能识别），
因此编译写入的指纹同样使用空 endpoint。改预算、改来源、换补充资料都会让产物过期。

## 5. 世界书条目

8 组固定分组（`style/worldbook.py`），全部：

- `category="author_style"`、`always_on=False`、`priority=40`、`chapter_gated=False`；
- 触发词是组合词：`作者风格` / `叙事风格` / `语言风格` / `文风特点` / `写作风格`；
- 全组维度都是 `unknown` 时不生成该条目；
- 正文末尾统一注明「以上为非原著事实的写作风格规则」。

严格起始点导出前，`check_style_no_plot_leak` 会扫描「第 N 章」指涉并拦截
起始点之后的引用。风格条目本来就不该提剧情，这是双保险。

## 6. 评估样例

`style_eval_cases.json` 至少 6 个，覆盖：场景铺陈 / 人物对话 / 内心活动 /
冲突 / 情绪克制爆发 / 场景收束。`expected_traits` 是抽象规律，不是原文逐字匹配。

评估只能回答「生成的文本是否符合档案里的规则」，**不能**回答「是否等于作者本人写的」。
`docs/RUN_REPORT.md` 记录了一次**合成档案上的机制演练**，不能作为作者风格证据。

## 7. 已知局限

1. **观察成本**：默认全部块各一次调用。抽样时报告写明覆盖率，不冒充全量。
2. **编译可能编造「作者习惯」**：提示词要求 `unknown`，schema 要求证据，
   `audit.md` 列置信度分布与人工复核项；测试断言低证据维度不高置信。
3. **补充资料是外部证据**：作者自述不会自动升格为作品风格事实，
   交叉检查结论写在 `limitations`。
4. **Description 膨胀**：开头只有一段固定的写作要求，完整规则在世界书；
   Description 里只多【叙事风格规范】一个分节。HTML 规则也在世界书里。
   预算硬约束是 `max_runtime_tokens`。
5. **导出语义变化**：`style.enabled=true` 时导出可能调用 LLM；默认关闭不受影响。
6. **不保证文风一致**：这是辅助规范，不是作者本人。
