# 可选功能：作者风格蒸馏 与 受控 HTML 条目

两个功能都默认关闭。只在用户明确提出「要模仿作者文风」/「要彩色、排版效果」时开启，
并在汇报里写明开了什么、花了多少、有什么没验证。

## 作者风格蒸馏（style）

### 它做什么

自动执行四段管线：逐块**观察**文风（带逐字引文证据）→ 分批**合并** → **编译**成
8 组风格档案 → **压缩**进预算。最终效果是：

- Description 最开头多一段【写作要求：作者风格】，并指向世界书条目；
- Description 末尾多一节【叙事风格规范】精简规则（受 `max_runtime_tokens` 预算约束）；
- 世界书多 8 条**触发式**条目（总体原则、句式、对白、心理、描写、意象、节奏、
  反模式），标题以「作者风格：」开头，提到相关词才注入，不占常驻预算。

风格资料是旁路产物，**不进 canon**：风格蒸馏不会去改任何事实条目。

### 怎么开

```yaml
style:
  enabled: true
  max_runtime_tokens: 800   # 叙事风格规范分节的粗估上限；超出自动压缩，再超报错
  worldbook_entries: true   # 8 组完整档案进世界书（触发式）
  observe_max_chunks: 0     # 0 = 观察全部章块；>0 为确定性等距抽样（首尾必含）
  merge_batch_size: 30
  supplementary_path: null  # 可选：作者访谈/创作谈（md/txt），作为补充证据
```

然后正常 `n2t export --run-id ID`：风格产物缺失或输入指纹变化时会**自动**跑
`style-observe → style-compile`，不需要手动分步；产物新鲜时导出不再调用模型。
file 引擎下观察响应由 Agent 生成（与抽取响应同理）——先小样本试运行，按报错
补齐响应文件后再全量：

```bash
.venv/bin/n2t style-observe --run-id ID --limit 4   # 先试 4 块，确认响应文件命名与质量
.venv/bin/n2t style-observe --run-id ID             # 正式全量/抽样
.venv/bin/n2t style-compile --run-id ID
```

产物在 `runs/<id>/author_style/`；`audit.md` 记录覆盖率、置信度分布、
压缩丢弃项与人工复核项——汇报时覆盖率低要明说「这是抽样，不是全量」。

### token 成本（让用户知情再开）

实测参考（156 章 / 69.8 万字全量观察）：观察约 0.9M token，合并+编译约 0.16M，
合计约 1.0–1.1M。**粗算规则：每章约 6–7k token，外加 100–160k 合并/编译开销。**
预算有限就用 `observe_max_chunks` 抽样（48 ≈ 1/3 成本），代价是档案容易偏。
这是导出时的一次性模型调用，不是角色卡运行时占用；运行时每轮常驻增量约
850 token，风格条目触发时约 3.3k token。

### 汇报口径

风格档案是自动蒸馏产物，不是「与作者文风完全一致」的证明；证据不足的维度保留
`unknown`。汇报时用「蒸馏档案」，不说「完美还原文风」。

## 受控 HTML 条目（rendering.html）

### 它做什么

开启后世界书多一条**触发式**条目「输出格式：受控 HTML 规范」（comment 键
`wb_rendering_html`），内容是提示词规则：回复中允许少量 `<span>` 内联样式
（配置里的字号/色板/斜体），用于强调、心理、书信等场景。**不进 Description**，
不增加常驻负担，提到排版/HTML 相关词才触发。

### 怎么开

```yaml
rendering:
  html:
    enabled: true
    mode: controlled_span                       # 唯一取值
    allowed_properties: [font-size, color, font-style]   # 只能取这三者的子集
    allowed_font_sizes: ["0.88em", "1em", "1.08em", "1.12em"]  # 必须 em 相对单位
    color_palette: { muted: "#9298A3", emphasis: "#B08A38", warning: "#B05A5A", mystery: "#7C8FA6" }
    max_suggested_spans_per_reply: 3
```

白名单之外的取值（px 单位、其他 CSS 属性）在 `config-check` 就报错——配置阶段
修正即可，不用跑到导出才发现。

### 三条不要承诺

这是**提示词约束，不是运行时沙箱**：

1. 不保证 Tavo/SillyTavern 一定渲染这些样式（未实测）；
2. 不保证模型每次遵守规范；
3. 本工具不过滤运行时模型输出的 HTML。

用户要的是「稳定可靠的富文本」时，如实说做不到，建议关闭。
