# 受控 HTML 输出规范

> **这不是运行时沙箱。** 本模块生成的是一条**世界书触发条目**（提示词约束）。
> 它不能过滤 Tavo 运行时的模型输出，也不保证客户端会渲染 HTML。
> 客户端是否渲染、模型是否遵守，只能实测（见 `docs/TAVO_IMPORT_CHECKLIST.md` §6.7）。

## 1. 边界

- 只允许 `<span>` 标签，只允许 `style` 属性。
- `style` 内只允许 `font-size` / `color` / `font-style` 的子集。
- 字号只能取配置里的 em 值；颜色只能取配置色板；`font-style` 只能是 `italic`。
- 禁止：其他标签、嵌套 span、外部资源、事件属性、任意 `class` / `id`、
  内联脚本与内嵌框架。
- 规范**不进 Description**，而是作为触发式世界书条目 `wb_rendering_html`。
- 默认关闭；关闭时导出结果与加入本模块前一致。

## 2. 配置

```yaml
rendering:
  html:
    enabled: false
    mode: controlled_span
    allowed_properties: [font-size, color, font-style]
    allowed_font_sizes: ["0.88em", "1em", "1.08em", "1.12em"]
    color_palette:
      muted: "#9298A3"
      emphasis: "#B08A38"
      warning: "#B05A5A"
      mystery: "#7C8FA6"
    max_suggested_spans_per_reply: 3
```

非法值会在 `config-check` 就报错，不会等到导出：

| 错误 | 例子 |
|---|---|
| 字号不是 em 相对单位 | `allowed_font_sizes: ["12px"]` |
| 颜色不是 `#RRGGBB` | `color_palette: {muted: "red"}` |
| 属性不在白名单 | `allowed_properties: [background]` |
| 色板为空 | `color_palette: {}` |
| 语义名不合法 | `color_palette: {"Muted": "#9298A3"}` |

## 3. 色板语义

色板名只是**约定**，不是客户端识别的语义。规范文本会列出 `名字 = 颜色` 对照表：

| 语义名 | 默认值 | 建议用途 |
|---|---|---|
| `muted` | `#9298A3` | 时间、地点、旁注 |
| `emphasis` | `#B08A38` | 关键线索、强调 |
| `warning` | `#B05A5A` | 警示、危险 |
| `mystery` | `#7C8FA6` | 悬念、未知 |

浅色与深色主题下的可读性**未实测**，换主题后应重新看一遍。

## 4. 触发条目

- `entry_id`：`wb_rendering_html`
- 标题：`输出格式：受控 HTML 规范`
- 类别：`rendering`，`always_on=false`，`priority=30`
- 触发词：`输出格式规范` / `排版规则` / `HTML格式` / `视觉样式` / `字号颜色`
- 正文末尾注明「本条目是格式约定，不是世界设定」
- 导出清单的 `rendering` 段写明 `note: 提示词约束，无 Tavo 运行时过滤`；
  `reports/audit.md` 也会单列一节声明这一点。

## 5. 规则文本怎么生成

`render/html_policy.py`：

- `build_html_rules_text(policy)`：全部取值从 policy 渲染，不写死；
- `build_html_entry(policy)`：包装成 `PlannedEntry`；
- `validate_html_sample(text, policy)`：标准库 `html.parser` 校验，
  返回违规原因列表（空 = 通过）。

**`validate_html_sample` 只用于校验本项目生成的文本与静态 fixture。**
它的存在是为了让「规则文本里自己的示例」不会违反规则，
以及让测试能锁住白名单；它不是客户端的过滤层。

## 6. 已知限制

1. 提示词不是沙箱：模型可能写别的标签，或客户端直接显示标签原文。
2. 不同客户端对 `<span style>` 的支持不同；Tavo 未实测。
3. HTML 规范条目本身占用触发预算；`reports/worldbook_budget.md` 会把它算进去。
4. 色板对比度没有自动校验；浅色/深色主题需要人工看。
5. 关闭 `rendering.html.enabled` 不删除已导出的旧文件，只影响下一次导出。
