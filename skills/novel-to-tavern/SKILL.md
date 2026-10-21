---
name: novel-to-tavern
description: 把小说文本（txt/md，中文或英文）导出成可导入 SillyTavern / Tavo（酒馆）的多角色世界模拟器角色卡与触发式世界书——每条事实都能回溯原文行号；可选作者风格蒸馏、受控 HTML 条目、按起始章节的结构性无剧透导出。当用户想把小说/故事/书籍做成 SillyTavern 或 Tavo 角色卡、世界书（worldbook / lorebook / 世界设定集）、酒馆卡，想把小说导入酒馆接着玩/续写，或提到 novel-to-tavern、n2t、novel_to_tavern 时使用本技能。即使用户只说「把这本书做成角色卡」「帮我把小说弄进 Tavo」「想要一个不剧透的酒馆卡」而没有点名工具，也应主动使用本技能，不要凭通用知识手写卡片 JSON。
license: MIT
compatibility: 需要本机 Python 3.10+ 与已安装的 novel-to-tavern 管线（n2t CLI，随本技能来源仓库提供）。不需要额外 API 凭据——事实抽取与风格观察由调用本技能的 Agent 自身完成（file 引擎 + 预生成响应）；若用户主动提供 OpenAI 兼容 endpoint 可切换。目标客户端：SillyTavern 1.19+ 或兼容 Character Card V2 的客户端（如 Tavo）。
---

# Novel to Tavern：小说 → 酒馆角色卡/世界书

驱动 `n2t` 管线，把一部小说转成可导入 SillyTavern / Tavo 的 Character Card V2 角色卡
（内嵌世界书）与独立世界书。模型输出的每条事实必须带逐字引文、行号由程序反查原文，
编造的内容进不了卡片。下文 `<skill>/` 指本技能所在目录（仓库内为
`skills/novel-to-tavern/`，随安装位置而变）。

## 开始前问四件事

1. **小说原文路径**（txt/md，文件或目录）。原文只读，任何情况下不修改。
2. **从第几章开始、怕不怕剧透**。默认单卡含全书剧情（提示词层面约束，尽力而为）；
   怕剧透就导出时加 `--start-chapter N`，起点之后的事实结构性不写入。
3. **要不要作者风格蒸馏**。默认**不开**：卡里多「模仿作者文风」要求和 8 条风格条目，
   代价是每章一轮观察调用。用户没提就不开。
4. **对话过程要不要 HTML 美化**。默认**不开**：世界书多一条受控 HTML 规范条目
   （只允许 span 字号/色板/斜体），模型按规范输出的 token 比正常要高，
   且只是提示词约束、不保证客户端渲染。

## 执行纪律

- 原文只读；规范化、摘要都写入新文件。
- 每次新建 run，产物写 `runs/<run_id>/`，不覆盖已有 run。
- 不伪造抽取结果：每条引文必须逐字摘自原文，找不到原文依据的内容写不进卡片。
- 凭据只走环境变量或 `.env`；只有用户主动提供 endpoint 时才用，不主动向用户索要。
- 如实汇报：没跑过的验证写「未执行」，没实测过的客户端行为写「未验证」。

## 工作流

### 1. 确认环境

```bash
n2t --version    # 或仓库里的 .venv/bin/n2t --version
```

`n2t` 不可用就说明管线没装——让用户按来源仓库的 README 完成安装（本技能不内置管线
代码，也不替你联网下载）。装好后继续。

### 2. 写配置

```bash
cp config/config.example.yaml config/config.yaml
```

- `project.source_path` → 用户的小说路径；
- `llm.provider: file`，`llm.precomputed_responses_dir: ./precomputed`。
  **你就是抽取模型**：管线通过 file 引擎读你按块生成的响应，不需要也不应该向用户
  索要 API key。用户主动提供 OpenAI 兼容凭据时，才改 `openai_compatible` 并把
  base URL/key 放进 `.env`（变量名见 `llm.base_url_env` / `api_key_env`）。

```bash
.venv/bin/n2t config-check
```

### 3. 跑管线

选描述性 run id（如 `wuxia-20261020`），用随附脚本：

```bash
<skill>/scripts/n2t_pipeline.sh <run_id> --require-responses ./precomputed
```

脚本顺序执行 config-check → ingest → 响应覆盖检查 → extract → resolve → timeline
→ export。**第一次在响应覆盖检查处会停下**：此时按第 4 步为每个缺失的分块生成响应，
然后加 `--skip-ingest` 重跑同一命令即可继续。想逐阶段手动控制（比如先检查章节
检测），各阶段命令见 references/pipeline.md。中断后同一 run id 原命令续跑，
不要换 run id。

### 4. 生成抽取响应（ingest 之后、extract 之前）

`ingest` 会建立 `runs/<run_id>/manifest.json`，其中 `chunks[*].chunk_id` 列出全部分块
（形如 `ch0001_p000`）。对每个 chunk_id，在 `precomputed_responses_dir` 下写一个
`<chunk_id>.json`，内容是该块的抽取结果，schema 以仓库
`src/novel_to_tavern/extract/schema.py` 的 `ChunkExtraction` 为准。规则：

- 逐块阅读原文对应行区间（`chunks[*]` 里有 start_line / end_line），只提取该块内容；
- 每条事实的 `quote` 必须逐字摘自原文——程序会回查行号，定位不到或多处命中的
  事实进不了卡片；
- 写完用 `<skill>/scripts/check_responses.py runs/<run_id> ./precomputed`
  核对覆盖率，缺哪个补哪个。

长篇（几十万字）全量生成响应消耗的 token 很大：先和用户确认要不要先小样
（extract 支持 `--limit N`，跑前几章看卡片质量）再全量。

### 5. 校验产物

```bash
python3 <skill>/scripts/check_card.py runs/<run_id>/exports/world_simulator_v2.json
```

导出本身已强制结构校验（有错不写文件）；check_card.py 独立复核「JSON 合法但客户端
静默出错」的字段并打印汇报数字。

### 6. 汇报

- 主卡路径：`runs/<run_id>/exports/world_simulator_v2.json`
- 条目数 / 常驻数 / 正文字数（check_card.py 输出）
- 引文定位率与 needs_review 数（`runs/<run_id>/reports/audit.md`）
- 验证状态：语义校验是否执行、客户端导入是否实测——没做就写「未执行/未验证」
- 可选项开关状态：风格蒸馏、HTML 条目、严格起始点

### 7. 导入

用户把主卡 JSON 导入 Tavo / SillyTavern。导入成功只是第一级；触发、常驻、剧透行为
的核对步骤在仓库 `docs/TAVO_IMPORT_CHECKLIST.md`。

## 可选功能

- **严格起始点**：`n2t export --run-id <id> --start-chapter N`（结构性无剧透）。
- **强制保留配角**：`n2t timeline --run-id <id> --include-character 名字` 后重跑 export。
- **作者风格蒸馏 / 受控 HTML**：开关、成本与局限见 references/style-and-html.md。
- **排障**：references/troubleshooting.md。

## 参考文件

- `references/pipeline.md` —— 六阶段命令、产物路径、恢复与缓存
- `references/style-and-html.md` —— 风格蒸馏与受控 HTML 的开关、成本、局限
- `references/troubleshooting.md` —— 常见故障的症状与处理
- `scripts/n2t_pipeline.sh` —— 顺序执行管线（含响应覆盖检查）
- `scripts/check_responses.py` —— 核对预生成响应覆盖率
- `scripts/check_card.py` —— 独立校验导出卡片并输出汇报数字
