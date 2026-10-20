# 配置参考：每个键读在哪里

这份文档回答一个问题：**改了某个配置，行为会不会变。**

为什么要单独写一份：本项目踩过一次 —— `config.py` 里 57 个字段有 24 个可变字段
从未被任何代码读取。用户把 `export.validate_before_export` 改成 `false`，
导出校验照跑；把 `pipeline.require_source_refs_for_canon` 改成 `true`，
也不会多出任何来源检查。**两种方向相反的谎，都比「没有这个开关」更误导。**

现在的规则是：

> 每个键要么有消费点，要么它的类型声明它只能取一个值。

这条规则不是靠自觉维持的 —— `tests/test_config_wiring.py` 会逐字段在 `src/` 里
查找消费点，找不到就失败。所以这份表是**测试的产物**，不是手抄的。

## 键 → 消费点

| 配置键 | 消费点 |
|---|---|
| `project.name` | `cli.py`、`ingest/source.py`、`ingest/pipeline.py`、`timeline/runner.py`、`llm/provider.py`、`export/runner.py`、`extract/runner.py`、`verify/runner.py`、`tavern/validator.py`、`resolve/runner.py`、`resolve/entities.py` |
| `project.source_path` | `ingest/pipeline.py` |
| `project.output_root` | `cli.py`、`ingest/pipeline.py` |
| `project.mode` | `export/startpoint.py`、`export/runner.py` |
| `input.formats` | `ingest/pipeline.py` |
| `input.encoding` | `ingest/pipeline.py`、`extract/runner.py` |
| `input.chapter_detection` | `ingest/pipeline.py` |
| `input.chapter_heading_regex` | `ingest/pipeline.py` |
| `input.chunk_target_chars` | `ingest/pipeline.py` |
| `input.chunk_max_chars` | `ingest/pipeline.py` |
| `input.preserve_chapter_boundaries` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `input.normalize_newlines` | `ingest/pipeline.py` |
| `llm.provider` | `llm/__init__.py`、`extract/runner.py`、`verify/runner.py` |
| `llm.precomputed_responses_dir` | `llm/__init__.py` |
| `llm.base_url_env` | `llm/__init__.py` |
| `llm.api_key_env` | `llm/__init__.py` |
| `llm.extraction_model` | `llm/__init__.py`、`llm/provider.py` |
| `llm.temperature_extract` | `llm/__init__.py`、`extract/runner.py` |
| `llm.request_timeout_seconds` | `llm/__init__.py` |
| `llm.max_retries` | `llm/__init__.py`、`llm/client.py` |
| `llm.retry_backoff_seconds` | `llm/__init__.py` |
| `llm.max_concurrent_requests` | `extract/runner.py` |
| `llm.max_output_tokens` | `llm/__init__.py`、`llm/provider.py`、`extract/runner.py` |
| `pipeline.resume` | `ingest/pipeline.py`、`extract/runner.py` |
| `pipeline.cache_enabled` | `extract/runner.py` |
| `pipeline.cache_dir` | `extract/runner.py` |
| `pipeline.quarantine_invalid_responses` | `extract/runner.py` |
| `worldbook.always_on_core_rules` | `export/runner.py` |
| `worldbook.always_on_world_overview` | `cli.py` |
| `worldbook.always_on_character_index` | `cli.py` |
| `worldbook.max_always_on_entries` | `export/runner.py` |
| `worldbook.max_always_on_tokens` | `export/runner.py` |
| `worldbook.target_runtime_budget_tokens` | `export/runner.py` |
| `worldbook.enable_recursive_scan` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `worldbook.allow_mvu` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `worldbook.allow_ejs` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `style.enabled` | `export/runner.py`、`cli.py`、`style/pipeline.py` |
| `style.max_runtime_tokens` | `style/compiler.py`（预算检查与压缩） |
| `style.worldbook_entries` | `style/pipeline.py` |
| `style.observe_max_chunks` | `style/observe.py`（确定性等距抽样） |
| `style.merge_batch_size` | `style/compiler.py` |
| `style.supplementary_path` | `style/compiler.py`、`config.py`（缺失警告） |
| `rendering.html.enabled` | `export/runner.py`（触发式条目、导出清单与审计）、`config_warnings()` |
| `rendering.html.mode` | `render/html_policy.py` |
| `rendering.html.allowed_properties` | `render/html_policy.py` |
| `rendering.html.allowed_font_sizes` | `render/html_policy.py` |
| `rendering.html.color_palette` | `render/html_policy.py` |
| `rendering.html.max_suggested_spans_per_reply` | `render/html_policy.py` |
| `export.character_card_spec` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `export.include_individual_npc_cards` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `privacy.never_log_api_keys` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `privacy.never_include_api_keys_in_exports` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |
| `privacy.do_not_upload_novel_without_explicit_user_action` | **声明型** —— 单值 `Literal`，只能取一个值，不是开关 |

## 「声明型」是什么意思

`preserve_chapter_boundaries: Literal[True]`、`enable_recursive_scan: Literal[False]`、
`include_individual_npc_cards: Literal[False]`、`allow_mvu` / `allow_ejs: Literal[False]`、
`privacy.*: Literal[True]` —— 这些字段在 schema 层就只允许一个取值。

它们**不是开关**，是声明：

- `Literal[True]` 表示「这是不变量，关不掉」（章节边界永远是分块边界；密钥永远不进导出物）。
- `Literal[False]` 表示「这条路还没修」（递归扫描、单张 NPC 卡、MVU/EJS/HTML 美化）。
  写成 `bool = False` 会让人以为自己打开了什么；写成 `Literal[False]`，
  改的时候会在配置校验处直接撞墙，并看到原因。

## 已删除的键（以及为什么）

以下键曾经存在于 `config.example.yaml` 与 `config.py`，但**没有任何代码读它们**。
删除的理由统一是「留着等于让配置文件撒谎」；删除后由
`test_removed_keys_stay_removed` 挡住，避免它们无声地回来。
最后一行是例外：它不是「从未接线」，而是被真实功能取代。

| 键 | 曾经看起来像什么 | 实际行为 |
|---|---|---|
| `project.default_start_chapter` | 默认起始章节 | 从来不生效，导出恒定走「尽力而为」档 |
| `llm.synthesis_model` | 综合阶段用哪个模型 | 没有综合阶段 |
| `llm.audit_model` | 审计用哪个模型 | 没有审计阶段 |
| `llm.temperature_synthesis` | 综合阶段温度 | 同上 |
| `llm.log_token_usage_when_available` | 记录 token 用量 | 从不记录 |
| `llm.never_auto_switch_provider` | 禁止自动切换引擎 | 本来就没有切换逻辑 |
| `pipeline.preserve_raw_responses` | 保留原始响应 | 缓存与隔离目录本来就在存 |
| `pipeline.require_source_refs_for_canon` | **强制 canon 必须有来源** | 真正的强制在抽取阶段，与这个开关无关 |
| `pipeline.merge_low_confidence_entities` | 合并低置信实体 | 归一从不自动合并低置信候选 |
| `pipeline.drop_characters_by_default` | 默认丢弃人物 | 与本项目「默认不丢人物」原则相反，且从未生效 |
| `pipeline.fail_on_invalid_model_json` | 非法 JSON 直接失败 | 重试 → 隔离 → 抛错，本来就是这条路 |
| `export.validate_before_export` | **导出前校验开关** | 校验**无条件执行**，写 `false` 也关不掉 |
| `export.overwrite_existing_run` | 允许覆盖已有 run | 从不覆盖，也没实现覆盖 |
| `export.include_embedded_character_book` | 是否内嵌世界书 | 永远内嵌（单文件导入是本项目的核心用法） |
| `export.also_export_standalone_worldbook` | 是否另出独立世界书 | 永远另出（严格档要用它） |
| `worldbook.allow_html_beautification` | 受控 HTML 开关（声明型，永远 `false`） | 已由 `rendering.html.enabled` 取代；写旧键会报 unknown 字段 |

> 如果你需要其中某一项成为真功能，正确的顺序是：先实现、再加测试、
> 最后把它加回 schema —— 那时 `test_config_wiring.py` 会自然通过。

### 从 `allow_html_beautification` 迁移

旧配置里的 `worldbook.allow_html_beautification: false` 现在会被拒绝
（未知字段）。删掉它，改用：

```yaml
rendering:
  html:
    enabled: false   # 改成 true 才会多出世界书触发条目
```

注意行为不同：旧键是一个**从未生效的声明**，新键是**真的会改变导出产物**的开关。

## 加新配置项的检查清单

1. 在 `config.py` 对应的 `*Config` 里加字段。
2. 在真正的执行路径上读它（不是只在 `summarize()` 或 `config_warnings()` 里提一句）。
3. 跑 `pytest tests/test_config_wiring.py` —— 它会告诉你有没有漏第 2 步。
4. 如果它影响解析 / 抽取 / 切分结果，**同时加进 `_config_fingerprint`**
   （`ingest/pipeline.py`），否则续跑会复用按旧配置产出的结果。
5. 在 `config/config.example.yaml` 加一行，并说明取值含义。
6. 加一条行为测试：改了它，产物**确实**变了。
