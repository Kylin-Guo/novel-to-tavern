# 审查发现本地复核（REVIEW_RECHECK）

- 复核对象：`docs/AGENT_REVIEW_REPORT.md`（2026-10-17 版）中的 P1 / P2 / P3 全部条目
- 复核基线：本地 checkout，`master` @ `839695b`，测试 **472 passed**
- 复核方式：**逐条读当前源码 + 运行可执行证据**。凡标「已复现」的，都给出了可直接重跑的命令或脚本输出。
- 范围说明：按用户指示，**P1-07（`exports/天之炽/` 的公开分发授权）不在本次复核范围内**。

结论记号：

- `confirmed` —— 当前代码确实存在该问题
- `not_reproducible` —— 当前代码不存在该问题（附「为何不成立」）
- `partially_confirmed` —— 部分成立
- `needs_user_decision` —— 事实成立，但修法涉及既定设计取向，需用户定夺

---

## 0. 总表

| ID | 报告判断 | 本地复核结果 | 关键证据 | 决定 |
|---|---|---|---|---|
| P1-01 | 严格导出调用与函数签名不一致，可能 TypeError | **not_reproducible** | `builder.py:180-188` 已有 `strict_label` / `strict_chapter_index` | 无需修复 |
| P1-02 | 严格档仍把全量数据交给 greeting builder | **confirmed** | `builder.py:305` `_character_roster(entities)` 未按起始点过滤 | 修：过滤 entities |
| P1-03 | 缺 `fact_type` 默认成 canon | **confirmed** | `extract/schema.py:62,72` 默认 `CANON`；`:53` 默认 `"character"` | 修：改默认 + 进复核队列 |
| P1-04 | `partially_supported` 仍当通过 | **confirmed，维持现状** | `verify/schema.py:20,81`；已运行证明未支持部分留在条目正文 | **口径已定**：卡是世界模拟器资料 → 不排除，只如实计数 |
| P1-05 | 引文「命中」不等于唯一定位 | **confirmed** | `extract/evidence.py:74` `.find()` 只取首次；`:91` `matched_text` 为整行拼接 | 修：返回全部命中 + 歧义标记 |
| P1-06 | 主线条目用「剧情 / 主线」做触发词 | **confirmed** | 真实卡内 `keys` 含 `剧情`/`主线`，正文 25,483 字 | 修：改显式检索词 |
| P1-07 | 公开仓库含衍生角色卡 | **不在本次范围** | 按用户指示跳过 | —— |
| P2-01 | pyproject 许可证与 LICENSE 冲突 | **confirmed** | `pyproject.toml:11` `Proprietary` vs `LICENSE` MIT | 修 |
| P2-02 | 子命令缺统一 run_id 边界校验 | **confirmed** | `cli.py:247/283/312/350/395`；`--run-id /etc` → `/etc` | 修：加 `resolve_run_dir` |
| P2-03 | `--start-chapter` 范围校验不足 | **confirmed** | `cli.py:318,400` `if start_chapter else None` | 修：正整数校验 |
| P2-04 | 缓存键未区分真实 endpoint | **confirmed** | `extract/runner.py:113-132` 只含 `provider.name` | 修：加 base_url 指纹 |
| P2-05 | 配置项未消费 / 未入指纹 | **confirmed** | 57 个字段中 **24 个可变字段无任何功能消费** | 修：接通或删除 |
| P2-06 | 语义审核未跑就导出，缺 strict-fidelity 门 | **partially_confirmed，不加门** | 透明标记**已有**（`executed:false`）；**门禁没有** | **口径已定**：不加阻断门，理由见 §6 |
| P2-07 | 实体覆盖阈值静默丢弃小角色 | **partially_confirmed** | 跳过名单与原因**已进报告**（`worldbible.py:182-216`）；缺「仅索引」名单与强制保留选项 | 修：补覆盖统计 + 强制保留 |
| P2-08 | 世界书触发需真实运行测试 | **confirmed** | `TAVO_IMPORT_CHECKLIST.md` §9：除导入外全部「未测」 | 需用户在 Tavo 实测 |
| P2-09 | 严格导出 / CLI 状态文档漂移 | **confirmed** | `cli.py:20` 写「Tavo（待实测）」；`PLAN.md`/`IMPLEMENTATION_PLAN.md` 对 `verify` **零提及** | 修文档 |
| P2-10 | 100% 指标命名可能高估可靠性 | **partially_confirmed** | 已拆 `quote_location_success_rate` / `semantic_entailed_rate`；缺 `unique_quote_rate` | 修：补唯一性指标 |
| P3-01 | `build_plot_entry()` 重复定义 | **not_reproducible** | 当前仅 `builder.py:77` 一处定义 | 已修 |
| P3-02 | 章节解析配置与文档一致 | **partially_confirmed** | `manifest.detections[].strategy` 只有 `regex`/`fallback`，**无 `manual`**；<2 个标题有警告 | 修：补 manual 标记 |
| P3-03 | 错误日志可能泄露长篇文本 | **partially_confirmed** | 日志全部有界（全仓 `log.debug` 零次）；但 quarantine **写全量响应** | 修：加长度上限 |
| P3-04 | 提示词/配置版本与 manifest 闭环 | **partially_confirmed** | prompt/schema/输入 sha256/校验结果都有；**缺输出文件哈希**，`config_fingerprint` 只覆盖 ingest 段 | 修：补输出哈希 |
| P3-05 | 测试计数应有单一来源 | **not_reproducible** | `tests/test_docs_consistency.py:131` 用 `pytest --collect-only` 锁住 README/RUN_REPORT | 已实现 |

---

## 1. P1 逐条

### P1-01 严格导出函数签名 —— `not_reproducible`

报告的观察基于一个旧版本。当前签名是**关键字参数**且已包含这两个：

```
src/novel_to_tavern/export/builder.py:180-188
    def build_greetings(
        *, book_title, digests, entities, timeline,
        strict_label: str = "", strict_chapter_index: int | None = None,
    ) -> Greetings:
```

调用侧 `export/runner.py:446-453` 传参一致，`build_greetings` 在 `strict_label` 非空时转入
`_build_strict_greetings`（`builder.py:198-205`）。`tests/test_startpoint.py:234` 覆盖该路径。

> 报告要求「不要只加两个未使用参数来消除异常」。实际情况符合要求：这两个参数**被真正使用**
> （`strict_chapter_index` 用于过滤 `digests`，`strict_label` 用于换掉规则尾注）。

### P1-02 严格档仍读全书数据 —— `confirmed`（已可执行复现）

`_build_strict_greetings` 只对 `digests` 做了过滤（`builder.py:308-311`），
`roster` 与 `places` 仍吃**全量** `entities`（`builder.py:305-306` → `:168-177`）。
`export/runner.py:449` 传的正是全量 `entities`。

复现（自造实体：人物0/1 前两章出场，人物3/4/5 第 4 章后才出场）：

```
=== 从第 2 章严格开始 ===
scenario = 世界：测试书。
当前时间点：第2章 标题1。
已出场人物：人物0、人物1、人物3、人物4、人物5   ← 后三人尚未出场
```

`first_mes` 与 `description` 干净，**`scenario` 泄漏未来人物名**。`scenario` 会随卡一起被
客户端常驻使用，所以这是实打实的剧透面。现有测试 `test_strict_greetings_offer_only_one_start`
只断言章节摘要标记 `_marker(later)` 不出现，**没有断言未来人物名不出现**，因此漏掉了这条。

修法（两处，都不大）：

1. `_character_roster` / `_places` 增加 `start_chapter` 形参，按
   `first_appearance_chapter <= start_chapter` 过滤；
2. `_export_strict` 把过滤后的 entities 传给 `build_greetings`，并把测试从
   「章节摘要标记」升级为「未来实体名 + 未来事件标记」。

### P1-03 缺字段静默变成正史 —— `confirmed`

```
src/novel_to_tavern/extract/schema.py:62    fact_type: FactType = CANON
src/novel_to_tavern/extract/schema.py:72    fact_type: FactType = CANON
src/novel_to_tavern/extract/schema.py:53    kind: EntityKind = "character"
```

`RawChunkExtraction` 用 `model_validate` 直接吃模型 JSON，字段缺失时 Pydantic 静默填默认值，
不报错、不进复核队列。报告的建议（缺字段降级 `unknown`）与提取提示词里
「拿不准不要用 canon_fact 兜底」的原则一致 —— 当前代码把这条原则在**最容易被绕过的位置**放空了。

修法：`fact_type` / `kind` 改为**必填无默认**（缺失即触发 schema 校验失败 → 走重试或进
`needs_review`），或保留默认但把默认改为 `unknown` 并在 `review_status` 上记为待审。
两条路都要加「缺字段响应」的测试。

### P1-04 `partially_supported` 当通过 —— `confirmed`（设计取向，需用户定夺）

```
src/novel_to_tavern/verify/schema.py:20   PROBLEM_VERDICTS = {contradicted, insufficient_evidence}
src/novel_to_tavern/verify/schema.py:81   return self.verdict not in PROBLEM_VERDICTS
```

已运行证明其下游后果 —— 一条「部分支持」的复合事实（前半句有据、后半句没有）仍然整条进入条目正文：

```
partially_supported 的 .ok = True | 是否进排除集 = False
条目正文是否仍含未经支持的「屠龙」： True
--- 正文 ---
ability：会用剑
background：出身骑士团，并曾独自屠龙   ← 「屠龙」无原文支持
state：受伤了
```

**这是本仓库有意的设计**：`tests/test_verify.py:113` 明确写了
「『部分支持』不是『错』，它只是不够 —— 排除它是过度反应」。报告的立场相反
（严格保真模式下应进复核队列）。两者都不算错，取决于这张卡的定位：**世界模拟器资料**
还是**严格出处考据**。故记为 `needs_user_decision`。

若要按报告的方向修，最小改动是：把 `partially_supported` 计入
`SemanticReport.review_required`（新字段），导出时**不排除**但**在 audit 里单列**，
并给 `--strict-fidelity` 一个开关——默认行为不变，严格模式才排除。

### P1-05 引文「命中」不等于唯一定位 —— `confirmed`

```
src/novel_to_tavern/extract/evidence.py:74    position = "".join(chars).find(needle)
src/novel_to_tavern/extract/evidence.py:91    matched_text = "".join(lines[first:last+1]).strip()
src/novel_to_tavern/extract/evidence.py       （无引文长度下限，只有 MAX_QUOTE_CHARS 上限）
```

已运行复现：

```
=== 同一句在 3 行里出现两次 ===
返回：{'start_line': 0, 'end_line': 1, 'matched_text': '他把剑放下了。'}
→ 只返回首个匹配，无 ambiguous 标记

2 字引文「剑」→ 定位到 (0, 1)，matched_text = '他把剑放下了。'
→ 无引文长度下限；matched_text 是整行拼接，不是模型给的短引文
```

`EvidenceStats`（`evidence.py:104-118`）只有 `total/located/unlocated`，没有
`unique_match` / `ambiguous`。所以 RUN_REPORT 里的「100% 定位」在字面意义上是对的，
但它统计的是「至少能找到一处」，报告说的「不能解释为唯一且准确的定位」成立。

修法：`locate_quote` 改为返回**全部**命中位置；命中多于一处时标记 `ambiguous` 并降级为
`needs_review`；给 `quote` 加最小长度（例如 ≥ 4 个非空白字符）；`matched_text` 拆成
`quote_exact`（模型原引文）与 `context_excerpt`（限长）。

### P1-06 主线条目触发词 —— `confirmed`（在真实产物上复现）

```
真实卡 exports/天之炽/world_simulator_v2.json：
  keys = ['剧情', '主线', '前情', '剧情走向', '原著剧情', '故事线']
  正文长度 = 25483
  「这个剧情怎么发展」会命中：True
  「主线任务是什么」会命中：True
```

`builder.py:45-47` 的注释写着「只用不会在日常对白里随便出现的词」，而 `剧情` / `主线`
恰好是中文对白里的高频词 —— 注释与取值自相矛盾。命中代价是把 25,483 字灌进上下文。

注意与严格档的关系：严格档条目不包含主线条目（`runner.py:444` `include_plot=False`），
所以这条只影响默认档。

修法（与报告一致）：把 `剧情` / `主线` 这类自然对白词从 `PLOT_ENTRY_KEYS` 移除，只留
需要用户明确检索才会输的短语（如 `原著逐章大纲`）；并加一组真实中文句子的误触发测试
（「剧情太慢了」「改一下剧情」「前情回顾」）。

---

## 2. P2 逐条

### P2-01 许可证元数据冲突 —— `confirmed`

```
pyproject.toml:11    license = { text = "Proprietary" }
LICENSE              MIT
README.md            「代码与文档采用 MIT 许可证」
```

三处互相矛盾，且 `LICENSE_POLICY.md` / `NOTICE.md` 已经把边界写清楚了，唯独打包元数据没跟上。
修法：改成与实际一致的 MIT 声明（并按当前 PEP 639 支持的写法），把 `exports/` 的例外写在
`NOTICE.md` 与 wheel 排除清单里，再加一条元数据一致性测试。

### P2-02 子命令缺 run_id 边界校验 —— `confirmed`（已可执行复现）

`is_valid_run_id()` 存在（`paths.py:42`），但只被 `create_run_dir`（`:59`）调用。
五个子命令各自直接拼路径，**没有任何一处校验**：

```
src/novel_to_tavern/cli.py:247, 283, 312, 350, 395
    run_dir = Path(config.project.output_root) / args.run_id
```

已运行复现：

```
run_id='/etc'      → /etc        is_dir=True    ← 绝对路径直接吃掉 output_root
run_id=''          → runs        is_dir=True    ← 空串落到 output_root 本身
run_id='../../etc' → runs/../../etc
run_id='a/b'       → runs/a/b
```

`run_id='/etc'` 会通过 `is_dir()` 检查继续往下跑，随后在 `/etc/exports/`、`/etc/reports/`
下写文件。`tests/test_cli.py` 对这个风险**零覆盖**。

修法：新增 `resolve_run_dir(output_root, run_id, *, must_exist)`，统一做
①格式校验（`is_valid_run_id`）②`resolve()` 后断言在 `output_root` 之下 ③拒绝符号链接越界；
五个子命令全部改用它。测试覆盖 `../escape`、绝对路径、空串、`a/b`、Unicode、符号链接。

### P2-03 `--start-chapter` 范围校验 —— `confirmed`

```
src/novel_to_tavern/cli.py:318    start_index = start_chapter - 1 if start_chapter else None
src/novel_to_tavern/cli.py:400    start_chapter = args.start_chapter - 1 if args.start_chapter else None
```

`0` 是 falsy，被静默当成「未指定」；负数直接减 1 后传给下游。下游
`resolve_start_point` 确实会拦越界（`startpoint.py` 抛「超出范围」，`tests/test_startpoint.py:145`
覆盖），所以**不会生成错误产物**，但**报错信息是内部异常而不是 CLI 用法错误**，
且 `0` 这个真实会写错的输入被静默接受。修法：在 argparse 层加正整数类型，
上限参考 `len(digests)`，并把 `if x else None` 改成 `if x is not None else None`。

### P2-04 缓存键缺 endpoint 指纹 —— `confirmed`

```
src/novel_to_tavern/extract/runner.py:113-132
cache_key(model=..., provider=self.provider.name, chunk_sha=..., temperature=...)
payload = {model, provider, prompt_template_sha256, schema_version, chunk_sha256, temperature}
```

`provider.name` 对 OpenAI 兼容引擎是常量 `"openai_compatible"`，**不含 base_url**。
换一家兼容服务但模型名相同时，会命中上一家的缓存，且命中是静默的。
修法：把规范化 base_url 的 sha256 前缀并入键（绝不放 API key）；顺带把
`max_output_tokens`、top_p 等影响输出的参数一并纳入（当前它们甚至没被消费，见 P2-05）。

### P2-05 配置项未消费 —— `confirmed`（本次复核中问题面最大的一条）

`config.py` 共 57 个字段。**24 个可变字段没有任何功能消费**：

| 分组 | 未消费的可变字段 |
|---|---|
| project | `default_start_chapter` |
| input | `formats`、`normalize_newlines`、`preserve_chapter_boundaries`（只入指纹，无切分逻辑） |
| llm | `synthesis_model`、`audit_model`、`temperature_synthesis`、`log_token_usage_when_available`、`never_auto_switch_provider` |
| pipeline | `preserve_raw_responses`、`require_source_refs_for_canon`、`merge_low_confidence_entities`、`drop_characters_by_default`、`fail_on_invalid_model_json` |
| worldbook | `always_on_core_rules`、`always_on_world_overview`、`always_on_character_index`、`target_runtime_budget_tokens`、`enable_recursive_scan` |
| export | `include_embedded_character_book`、`also_export_standalone_worldbook`、`include_individual_npc_cards`、`validate_before_export`、`overwrite_existing_run` |

另有一批**单值 Literal** 字段（`allow_mvu: Literal[False]`、`never_log_api_keys: Literal[True]`、
`character_card_spec: Literal["chara_card_v2"]` 等）。这些**不是**缺陷 —— 它们只能取一个值，
是声明而不是开关，只能当文档看。上面 24 个则不同：用户写 `false` 或写另一个值，行为**完全不变**。

最值得先处理的两个，因为它们看起来像安全阀：

- `pipeline.require_source_refs_for_canon` —— 名字表明它会强制 canon 必须有来源。实际未接线；
  真正的强制发生在 `resolve`/`extract` 内部，与这个开关无关。
- `export.validate_before_export` —— 导出校验**无条件执行**（`export/runner.py:205-213`），
  所以写 `false` 不会跳过校验。行为上没问题，但**配置撒谎**：一个想跳过校验的用户会以为自己跳过了。

run 级配置指纹（`ingest/pipeline.py:40-51`）只覆盖 6 个 `input.*` 字段。也就是说
**改 `llm.*` 不会让指纹变化**，resume 时可能复用按旧配置产出的结果。

修法：为每个字段建「定义 → 消费 → 测试」表（本复核已产出）；未实现的要么接通并测，
要么从 schema 与 example.yaml 里删掉并记入路线图。所有影响解析/抽取结果的字段必须入指纹。

### P2-06 缺 strict-fidelity 门 —— `partially_confirmed`

**透明标记已经有了**：没跑 `verify` 时，导出清单里写 `metrics.semantic_support.executed = false`
并附说明（`export/runner.py:628-637`），audit 报告里该列写 **未执行**（`:752`），
README 单列「语义支持校验：未执行」。这一半报告的要求已经满足。

**门禁没有**：`export` 不会因为高重要性事实未做语义校验而拒绝或要求确认（全仓搜
`strict_fidelity` 只命中审查报告自身）。这是产品取舍：加门会在无 API 额度时彻底阻塞离线导出。
记为 `needs_user_decision`；若加，建议做成 `--strict-fidelity` 显式开关，默认不变。

### P2-07 实体覆盖与小角色 —— `partially_confirmed`

**已经做到的部分**（比报告预期的好）：门槛是显式的
（`MIN_ENTITY_FACTS = 2`、`MIN_ENTITY_CHAPTERS = 3`，`worldbible.py:54-55`），
跳过名单由 `entities_skipped_from_worldbook()`（`:182-216`）产出，并渲染进
`reports/timeline_report.md`（`timeline/runner.py:299-318`），按原因分组列名。
在严格起始点下，原因还会被改写成「起始点之前只有 N 条事实 —— 此刻内容不足，
**不是抽取遗漏**」（`worldbible.py:209-215`）。也就是说**没有任何实体是被静默丢掉的**。

**仍缺的部分**（报告点到的两个）：

1. **覆盖统计不完整。** 报告里只有「被跳过的实体」这一侧；没有
   **实体总数**、**拥有独立条目的数量**、**只出现在人物索引里的名单**。
   人物索引上限 `MAX_INDEX_ENTRIES = 60`（`worldbible.py:67`），超出部分只在条目正文里
   写一句「另有 N 人及次要角色」（`:421-422`），**没有落成名单** ——
   与那份 docstring 承诺的「名单会写进报告」不符。
2. **没有强制保留选项。** 全仓搜 `--include-character` / `include_character` /
   `force_include` 在代码里零命中（唯一命中是审查报告自己）。`timeline` 与 `export`
   都只有 `--run-id` / `--start-chapter`。用户想扮演一个被门槛刷掉的配角时无法强制生成。

修法：①在 `timeline_report.md` 增一节覆盖表（总数 / 有独立条目 / 仅索引 / 被跳过+原因）；
②`build_chapter_index` 侧把索引溢出名单写进报告；③加 `--include-character NAME`，
让指定实体跳过门槛。

### P2-08 世界书触发需真实运行测试 —— `confirmed`

`docs/TAVO_IMPORT_CHECKLIST.md` 已把状态写得很诚实（§9）：

```
主卡导入：            ✅ 通过
内嵌世界书：          ✅ 出现并显示条目 → 自动 or 需手动：未分辨
关键词触发 / 常驻 / 剧透 / token 占用 / insertion_order：未测
结论：结构层面（导入 + 显示）兼容；运行时行为未验证。
```

清单覆盖了常驻、中文名触发、别名触发、无关词不触发、严格档剧透、token 占用等观察点，
数量上够；但报告点名的「两个条目冲突」「重复条目」「重新导入后的持久性」「未命中时的 fallback」
四项清单里没有。**这一条只能由用户在真机上完成**，代码侧无法代替。

### P2-09 文档状态漂移 —— `confirmed`

```
src/novel_to_tavern/cli.py:20    TARGET_CLIENT = "SillyTavern 1.19.0 / Tavo（待实测）"
```

而 README「验证等级」表 ④⑤ 写「已实测通过（导入 + 内嵌世界书识别）」。两处对同一件事
给出相反状态 —— 这次是 CLI 过于悲观，README 过于乐观，但它们仍然互相打架。

阶段编号也没统一：README 与 `cli` 用六阶段（含 `verify`），而
`docs/PLAN.md` 与 `docs/IMPLEMENTATION_PLAN.md` 对 `verify` / 语义支持 **零提及**
（`grep -c` 均为 0），`docs/QUALITY_GATES.md` 同样没有。新增的第四阶段没有回灌到计划类文档。

修法：统一四个状态（格式符合 / 能导入 / 世界书触发已测 / 无剧透已测），每个附证据与日期；
把 `verify` 补进 PLAN / IMPLEMENTATION_PLAN / QUALITY_GATES。

### P2-10 100% 指标的命名 —— `partially_confirmed`

已改善的部分：指标已改名为 `quote_location_success_rate`，清单里带一句
「**这是来源定位指标，不是事实正确率**」（`export/runner.py:315-318`），
语义支持单独作为 `semantic_support` 并区分「未执行」，README 与 audit 都有
「它证明 / 它不证明」对照表。

仍缺的部分：报告要求的 `unique_quote_rate`、`source_ref_valid_rate`、`human_reviewed_rate`
在代码里**不存在**（全仓搜索无命中）。根因是 P1-05 —— 没有唯一性判定就没法算唯一率。
所以这条的修法挂在 P1-05 上：`locate_quote` 先能给出 `ambiguous`，指标才拆得出来。

### P3 逐条（报告未强制，一并核）

#### P3-01 `build_plot_entry()` 重复定义 —— `not_reproducible`

当前 `src/novel_to_tavern/export/builder.py` 中 `build_plot_entry` 只有一处定义（`:77`）。
早先版本确有两处，已合并；同时删掉了引用已移除常量的死函数 `plot_skeleton_text`。

#### P3-02 章节解析来源标注 —— `partially_confirmed`

策略**有**记录，但不够：`Manifest.detections: dict[str, DetectionInfo]`
（`ingest/manifest.py:47`，字段见 `chapters.py:66-72`）里的
`strategy` 是 `Literal["regex", "fallback"]`（`chapters.py:67`）——
**没有 `manual` 取值**。用户配了 `chapter_detection: manual` 且成功时，
写进 manifest 的仍然是 `"regex"`，与自动检测**无法区分**。
配置模式本身只以 sha256 形式存在于 `config_fingerprint` 里，不可读。

做对的部分：`MIN_HEADINGS = 2`（`chapters.py:24`），标题数不足时
`manifest.warnings` 会明确写「默认规则只找到 N 个章节标题（阈值 2），
已改用按字符预算的自动分段」（`chapters.py:332-336` → `pipeline.py:220-221`），
并渲染进 `reports/ingest_summary.md` 的「检测策略」列与「警告」节。

修法：`strategy` 增加 `"manual"` 取值并在 `build_chapter_index` 里如实传递。

#### P3-03 日志与调试信息泄露 —— `partially_confirmed`

**日志侧是干净的。** 全仓 13 处日志调用，`log.debug` **零次**；
`llm/client.py:114` 把响应体截到 300 字符，`:140`/`:143` 截到 200 字符；
`extract/runner.py:547` 的错误串来自 pydantic `ValidationError`，
实测（pydantic 2.14）会把 `input_value` 截到每侧约 24 字符，
即便原始响应 5,000 字符，报错也只有约 242 字符。没有任何日志传
`user_prompt` / `system_prompt` / `chunk` 文本 / `completion.text`。

**落盘侧不是。** `extract/runner.py:299-304` 的 quarantine 把
**完整无截断的原始响应**写到 `runs/<run>/extraction/_errors/<chunk_id>.txt`，
默认开启（`config.py:83`），**无长度上限**。响应缓存（`runner.py:202-212`）
同样把完整响应写进 `cache_dir` —— 当前 checkout 的 `cache/` 里有 164 个这样的文件（约 1.9 MB）。

修法：quarantine 与缓存写入前加长度上限（或截断 + 记录原长度），
两者都在 `.gitignore` 内，所以风险限于本地磁盘，不涉及公开仓库。

#### P3-04 版本与 manifest 闭环 —— `partially_confirmed`

`export_manifest.json`（`export/runner.py:280-345`）+ `_provenance()`（`:654-714`）已经覆盖了
报告要求的**大部分**：

| 报告要求 | 现状 |
|---|---|
| 输入 hash | ✅ 每个来源文件的 sha256（`sources[].sha256`） |
| Schema 版本 | ✅ `schema_version: 1` + `provenance.extraction.output_schema_version` |
| prompt 版本 | ✅ `prompt_version` + 期望值 + 模板 sha256 |
| run id | ✅ `run_id` |
| 质量门禁结果 | ✅ `validation`（errors / warnings 列表） |
| 起始章节 | ⚠️ 只在 `strict_start_point.chapter_index`，**且只在传了 `--start-chapter` 时** |
| 配置 hash | ⚠️ `config_fingerprint` **只覆盖 ingest 的 6 个 `input.*` 字段**，导出段配置未入哈希 |
| 输出文件 hash | ❌ `outputs` **只有文件名**，没有内容哈希 |

修法：`outputs` 改为 `{name, sha256}`；`config_fingerprint` 拆成
按阶段的两个指纹；非严格路径也记录主卡的起始点约定（「尽力而为」）。

#### P3-05 测试计数单一来源 —— `not_reproducible`

已经实现，且是自动的：`tests/test_docs_consistency.py:31-35` 定义
`TEST_COUNT_DOCS`，用 `pytest --collect-only` 取真实收集数（`:48-59`），
再由 `test_docs_agree_on_the_offline_test_count`（`:131-136`）断言
README 与 RUN_REPORT 里出现的数字包含真值。两处当前都写 472。

一个诚实的局限：它只断言「真值**出现**在这些文档里」，
如果同一篇文档里另有一个过期的数字，测试**不会**失败。要更严可以改成
「文档里的所有 `N 项离线` 数字都必须等于真值」。

---

## 3. 复核过程中新发现（报告未提）

1. **`_character_roster` 的 `limit=12` 与 `_places` 的 `limit=8` 是硬编码**，
   与 `worldbook.max_always_on_entries` 无关，也不在任何报告里体现。
2. **`paths.py` 的 `RUN_SUBDIRS` 声明了 `manifests` 目录，但没人往里写东西** ——
   `ingest/pipeline.py:95` 把 `manifest.json` 写在 run 根下，
   实际 run 目录里 `manifests/` 是空的（`extraction_batches.json`、`state.json`
   同样散在根下）。属 P3 级整洁度问题。
3. **P2-05 里最像缺陷的两个开关，行为方向是反的**：
   `export.validate_before_export=false` 不会跳过校验（校验无条件执行），
   `pipeline.require_source_refs_for_canon` 也没有接线。前者让用户以为自己关了门，
   后者让用户以为自己开了门 —— 两种都比「选项不存在」更容易误导。

---

## 4. 未独立复核项

**无。** 报告中 P1 / P2 / P3 的每一条都已给出结论，见 §0 总表。

唯一未复核的是 **P1-07**（`exports/天之炽/` 的公开分发授权），
按用户本次指示跳过。该条不是技术缺陷，而是权利状态确认，需要仓库所有者自行判断。

> 本文件不含小说原文；所有结论可依文中的文件行号或脚本重跑复现。

---

## 6. 修复记录（2026-10-17）

**口径先定：这张卡的定位是「多角色世界模拟器资料」，不是「逐字考据的原始文献」。**
这一句决定了下面两处「不修」为什么不是遗漏：

- **P1-04 不排除 `partially_supported`。** 一句只支持了一半的复合事实，
  在世界模拟器里仍然是有用的设定；在考据场景里才必须排除。
  当前的计数已经独立出现在校验报告里，所以「有多少条只是部分支持」是可查的。
  要换成严格口径，改动点是 `verify/schema.py` 的 `PROBLEM_VERDICTS`
  加上 `partially_supported`。已有测试锁着当前行为，改的时候会失败提醒。
- **P2-06 不加「语义校验没跑完就不许导出」的硬门禁。** 那会让没有 API 额度的人
  彻底无法离线导出 —— 而离线可跑通正是这个项目的既有能力。
  取而代之的是如实标注：导出清单里 `metrics.semantic_support.executed = false`，
  audit 报告该列写「未执行」，README 单列一行。三处都有了。

| ID | 状态 | 落地方式 |
|---|---|---|
| P1-01 | 已确认不成立 | 无需改动 |
| P1-02 | **已修** | `_visible_by()` 按 `first_appearance_chapter` 过滤名单；测试升级为「未来人物名不得出现」 |
| P1-03 | **已修** | 默认值改 `unknown`；`model_fields_set` 区分「模型说 unknown」与「模型漏写」；`unknown` 在类别兼容里当通配符 |
| P1-04 | **口径已定，维持现状** | 计数保留在报告里；口径写进 `QUALITY_GATES.md` §A2/§H |
| P1-05 | **已修** | `locate_quote` 统计全部命中；多处命中降级并写明次数；新增 `MIN_QUOTE_CHARS`；`SourceRef` 拆出 `quote_exact` |
| P1-06 | **已修** | 触发词只留组合词；新增 10 条真实中文说法的反向测试 |
| P2-01 | **已修** | `pyproject.toml` 改为 MIT，与 LICENSE / README 一致 |
| P2-02 | **已修** | 新增 `paths.resolve_run_dir()`，五个子命令统一走它；覆盖逃逸、空串、绝对路径、符号链接 |
| P2-03 | **已修** | argparse `type=_chapter_number`；两处 `if x else None` 改 `is not None` |
| P2-04 | **已修** | 缓存键纳入 endpoint 指纹（丢弃 query，避免密钥进文件名）与 `max_output_tokens` |
| P2-05 | **已修** | 删 15 个死键、3 个改单值 `Literal`、6 个真正接通；新增 `tests/test_config_wiring.py` 逐字段查消费点 |
| P2-06 | **口径已定，不加门** | 透明标注已有；理由见上 |
| P2-07 | **已修** | 新增覆盖表与 `index_overflow()` 名单；新增 `--include-character` |
| P2-08 | **清单已补，仍需人工实测** | 新增 §6.5 四类情形（条目冲突 / 未命中兜底 / 重复导入 / 重启持久性） |
| P2-09 | **已修** | `TARGET_CLIENT` 与 README 统一；`verify` 补进 PLAN / IMPLEMENTATION_PLAN / QUALITY_GATES |
| P2-10 | **已修** | 新增 `unique_quote_rate`；audit 指标表拆成两行并分别写明「说明什么 / 不说明什么」 |
| P3-01 | 已确认不成立 | 无需改动 |
| P3-02 | **已修** | `DetectionInfo.strategy` 增加 `manual`，与自动检测区分 |
| P3-03 | **已修** | quarantine 截断到 2 万字符并记录原始长度；缓存不截断（需逐字完整才能复用） |
| P3-04 | **已修** | `outputs` 改为 `{name, sha256, bytes, exists}`；非严格档补 `guarantee` 字段 |
| P3-05 | 已确认已实现 | 无需改动 |

**仍未完成的，只有一件：P2-08 的人工实测。** 触发、常驻注入、剧透行为、
token 占用这四类，代码侧无法代替真机验证；清单里一律标 ⬜，不写成通过。

---

## 5. 建议的修复顺序

按「先正确性、后一致性」排：

1. **P1-03**（改默认值，改动最小，风险最低，但仍可能改变既有 run 的产物）
2. **P1-02 + P1-05**（都涉及「过滤/定位」的语义，测试可一起补）
3. **P1-06**（只改一个常量列表 + 一组误触发测试）
4. **P2-02 + P2-03**（CLI 边界，纯增量，不动管线）
5. **P2-05 + P2-04**（配置表与缓存键，需要先决定「接通还是删除」）
6. **P2-07 + P2-09 + P3-02/P3-04**（报告完整性与文档一致性，纯增量）
7. **P3-03**（quarantine 加长度上限，一行改动）

**P1-04 与 P2-06 先别动** —— 这两条的修法会改变默认导出行为，属于产品口径，需要先定。

---

> 本文件由本地复核产出，不含小说原文。所有 `confirmed` 结论均可由文中给出的
> 文件行号或脚本重跑复现。
