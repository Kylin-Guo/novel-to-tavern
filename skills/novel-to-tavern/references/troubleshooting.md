# 排障：常见故障的症状、原因、处理

按「先读报错，再对号入座」处理。拿不准时用 `--log-level DEBUG` 重跑该阶段。

## 配置与启动

**`config-check` 报「未知键 / extra fields not permitted」**
配置模型对未知键直接报错。对照 `config/config.example.yaml` 或仓库
`docs/CONFIG_REFERENCE.md` 改成真实存在的键，不要发明配置项。

**`openai_compatible` 下报凭据缺失**
只有用户主动提供 endpoint 时才用这个 provider。`base_url_env` / `api_key_env`
写的是**环境变量名**，值放进 `.env` 或环境，不写进 yaml。修正后 `n2t doctor`
确认凭据隔离正常。默认路径（file 引擎）没有这一步。

**`extraction_model` 为 null**
仅在 `openai_compatible` 下需要，问用户用哪个模型。file 引擎下不用管。

## ingest：章节检测不对

症状：章节数明显不对（1 章/几千章）、标题乱码、章节切在奇怪位置。
处理：看 `manifest.json` 的 `chapters` 确认错误模式；给 `chapter_heading_regex`
写匹配该书标题格式的正则（或 `chapter_detection: manual`），
`n2t ingest --run-id <id> --no-resume` 重跑。章节错了不要继续往下跑——
后续每个阶段的产物都会错。

## extract：缺响应 / 引文定位失败多

**报错「缺少预生成响应」**：`precomputed/` 里缺 `<chunk_id>.json`。
用 `scripts/check_responses.py runs/<id> <目录>` 列出缺的块，补完再跑；
中断续跑同一命令即可。

**`needs_review` 偏多、定位率低于预期**：引文不是逐字摘录（改写/翻译/拼接）。
Agent 生成的响应要逐字复制原文引文；重新生成有问题的块（`extract --no-resume`
重跑该块）。

**限流 / 超时**（仅 openai_compatible）：调 `max_retries`、
`retry_backoff_seconds`、`max_concurrent_requests`；免费 endpoint 常见 429，
并发降到 1、退避加大后原命令续跑。

## resolve / timeline

**同名两个人被合并**：已知限制（测试锁定）。记录受影响条目并汇报，不手工改
中间产物。

**想扮演的配角没有条目**：`n2t timeline --run-id <id> --include-character 名字`
（可重复），重跑 export。

## export：校验报错不写文件

- **结构校验 error**：上游产物损坏或版本不匹配，重跑报错指向的阶段；
- **内嵌/独立世界书不一致**：重跑 export 本身即可；
- **密钥扫描命中**：凭据串混进了产物——检查 `.env` 与补充资料里是否含 key。
  清掉泄漏源再导出，不跳过扫描。

## 风格管线

**export 时要求生成风格响应**：`style.enabled: true` 且产物缺失/过期。
按 `style-observe --limit 4` 试运行，补齐它要求的响应文件后再 export；
不想跑就把 `style.enabled` 改回 false。产物「过期」由 `inputs_fingerprint`
判定：改预算、来源 hash、补充资料都会触发重跑。

**编译报超预算**：`max_runtime_tokens` 太小。调大（如 800→1200）后
`n2t style-compile --run-id <id> --no-resume`。

## 导入客户端之后

「导入成功」只说明 JSON 被接受。触发/常驻/剧透行为按仓库
`docs/TAVO_IMPORT_CHECKLIST.md` 核对。两个已确证的静默陷阱（导出侧已处理，
仅手工改 JSON 时才可能踩到）：

- 内嵌条目 `position` 必须是字符串 `"before_char"`；写数字 `0` 会被静默当成
  `after_char`；
- 条目缺 `enabled` 字段会被永久禁用，客户端不报任何错。
