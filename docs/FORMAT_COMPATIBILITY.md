# 目标格式兼容性核查

核查日期：**2026-10-16**
验证锚点：**SillyTavern 1.19.0**（GitHub release tag `1.19.0`，发布于 2026-09-14）

> 本文记录「本项目实际采用的字段」及其证据来源。**任何未列在此处的字段都不得进入 serializer 输出。**
> 证据分级：① 目标客户端源码 > ② 已实测成功的本地产物 > ③ 社区规范文档。冲突时以 ① 为准。

---

## 0. 为什么要锚定 1.19.0

| 事实 | 依据 |
|---|---|
| 生产酒馆运行的是 ST 1.19 | `sillytavern-deployment/k8s/deployment.yml` 部署记录（2026-09-22 迁入 K8S，namespace `sillytavern`） |
| 1.19 是最新的正式 release | GitHub API `/repos/SillyTavern/SillyTavern/releases`，`1.19.0` @ 2026-09-14 |
| 镜像 tag 是 `:latest`，会漂移 | deployment.yml 用 `registry.example.invalid/ghcr-io/sillytavern/sillytavern:latest` |

**结论**：本项目按 **1.19.0 的源码**实现。若生产镜像升级跨越版本，必须重跑 `tests/test_format_*.py` 并复核本文。

---

## 1. 证据来源清单

### ① 目标客户端源码（从 tag `1.19.0` 拉取，逐行核对）

| 文件 | 用途 |
|---|---|
| `public/scripts/char-data.js` | V2 类型定义的权威副本（`v2CharData` / `v2WorldInfoBook` / `v2DataWorldInfoEntry`） |
| `public/scripts/world-info.js:5617` | `convertCharacterBook()` —— 内嵌 `character_book` 转运行时的**唯一映射代码** |
| `public/scripts/world-info.js:855` | `world_info_position` 数值枚举 |
| `public/scripts/world-info.js:96` | `DEFAULT_DEPTH = 4`、`DEFAULT_WEIGHT = 100` |
| `public/scripts/world-info.js:33` | `world_info_logic`（`AND_ANY:0`） |
| `public/scripts/world-info.js:4127` | `newWorldInfoEntryDefinition` —— 独立世界书条目 **42 个字段**及其 type/default |
| `src/endpoints/worldinfo.js` | 独立世界书文件格式与校验（`File must contain a world info entries list`） |
| `src/endpoints/characters.js` | 角色目录扫描只认 `.png`；导入路由 `POST /import` 读 `body.file_type` |
| `src/character-card-parser.js` | PNG tEXt chunk 名与 V2/V3 处理 |

### ② 本机已实测成功的产物

`sillytavern-deployment/character-cards/` 下 4 张卡，均已导入生产酒馆。**只作对照，未复制任何内容进本仓库。**

### ③ 社区规范文档

| 文档 | 说明 |
|---|---|
| `character-card-spec-v2`（malfoyslastname） | V2 权威类型定义。**注意：全文只有 TS 类型，没有任何 JSON 示例** —— "照抄官网示例"这条路不存在 |
| `character-card-spec-v3`（kwaroran） | V3 规范，V2 的超集 |
| `docs.sillytavern.app` | 只有 UI 层字段说明，**未记载** `spec_version` / `character_book` / `extensions`，不可作字段级依据 |
| Tavo 官方文档 https://docs.tavoai.dev/ | **无任何字段级信息**（见 §7） |

---

## 2. 角色卡 V2 顶层结构

必须**逐字**为这两个值，客户端按字面量匹配：

```json
{
  "spec": "chara_card_v2",
  "spec_version": "2.0",
  "data": { "...": "..." }
}
```

`spec_version` 必须是字符串 `"2.0"`（不是数字 `2.0`）。

---

## 3. `data` 字段

本项目**输出**的字段（其余一律不写）：

| 字段 | 类型 | 本项目是否输出 | 说明 |
|---|---|---|---|
| `name` | string | ✅ | |
| `description` | string | ✅ | 放**少量**模拟器运行规则，不放百科 |
| `personality` | string | ✅ | |
| `scenario` | string | ✅ | |
| `first_mes` | string | ✅ | |
| `mes_example` | string | ✅ | |
| `creator_notes` | string | ✅ | **不得进入提示词** |
| `system_prompt` | string | ✅ | 可含 `{{original}}` |
| `post_history_instructions` | string | ✅ | 可含 `{{original}}` |
| `tags` | string[] | ✅ | |
| `creator` | string | ✅ | 仅展示 |
| `character_version` | string | ✅ | 仅展示/排序 |
| `alternate_greetings` | string[] | ✅ | 可为空数组 |
| `character_book` | object | ✅ | 见 §4 |
| `extensions` | object | ✅ | 默认 `{}`；只写本项目自己的命名空间键 |

> V2 规范要求：可选属性即便不被编辑器支持，也「**must never be destroyed if already in the data**」。
> 本项目解析他人卡时保留未知字段；输出自己的卡时只写上表字段。

---

## 4. 内嵌 `data.character_book`

```json
{
  "name": "string",
  "description": "string",
  "scan_depth": 4,
  "token_budget": 900,
  "recursive_scanning": true,
  "extensions": {},
  "entries": [ { "…": "…" } ]
}
```

**`entries` 是数组，不是对象。** 这是与独立世界书最大的结构差异。

### 4.1 条目字段（本项目输出集）

| 字段 | 类型 | 必填 | 本项目处理 |
|---|---|---|---|
| `id` | number | **是（本项目强制）** | ST 用它作 uid；缺省时回退数组下标 |
| `keys` | string[] | 是 | 主触发词 |
| `content` | string | 是 | 条目正文 |
| `enabled` | boolean | **是（本项目强制无默认）** | 见 §6 陷阱 2 |
| `insertion_order` | number | 是 | 排序 |
| `position` | `"before_char"` \| `"after_char"` | 是 | **字符串**，见 §6 陷阱 1 |
| `comment` | string | 是（本项目强制） | **条目标题/备注真正生效的字段** |
| `secondary_keys` | string[] | 否 | `selective` 为真时才有意义 |
| `selective` | boolean | 否 | 需同时命中 `keys` 与 `secondary_keys` |
| `constant` | boolean | 否 | 常驻，不依赖关键词 |
| `extensions` | object | 是 | 客户端扩展设置放这里 |

**本项目不输出**：`name`、`priority`、`case_sensitive`、`use_regex`（理由见 §6）。

---

## 5. 独立世界书（standalone worldbook）

### 5.1 文件结构

```json
{ "entries": { "0": { "uid": 0, "…": "…" }, "1": { "…": "…" } } }
```

- 顶层**必须含 `entries` 键**，否则服务端拒绝：`File must contain a world info entries list`。
- `entries` 是**以 uid 字符串为键的对象**，不是数组。

### 5.2 条目字段（依 `newWorldInfoEntryDefinition`，共 42 项）

本项目输出的字段与默认值（均取自 ST 模板，非推测）：

| 字段 | 默认 | 字段 | 默认 |
|---|---|---|---|
| `uid` | — | `position` | `0` |
| `key` | `[]` | `disable` | `false` |
| `keysecondary` | `[]` | `ignoreBudget` | `false` |
| `comment` | `''` | `excludeRecursion` | `false` |
| `content` | `''` | `preventRecursion` | `false` |
| `constant` | `false` | `delayUntilRecursion` | `0` |
| `vectorized` | `false` | `probability` | `100` |
| `selective` | **`true`** | `useProbability` | `true` |
| `selectiveLogic` | `0`（AND_ANY） | `depth` | `4`（`DEFAULT_DEPTH`） |
| `addMemo` | `false` | `outletName` | `''` |
| `order` | `100` | `group` | `''` |
| `groupOverride` | `false` | `groupWeight` | `100`（`DEFAULT_WEIGHT`） |
| `scanDepth` | `null` | `caseSensitive` | `null` |
| `matchWholeWords` | `null` | `useGroupScoring` | `null` |
| `automationId` | `''` | `role` | `0`（system） |
| `sticky` / `cooldown` / `delay` | `null` | `triggers` | `[]` |

> 注意 `selective` 的默认值在两侧**不一致**：ST 独立模板是 `true`，而 `convertCharacterBook` 用 `entry.selective || false`。
> 跨两种格式搬运时**必须显式写值**，不能沿用默认。

### 5.3 字段名对照表

| 独立世界书 | 内嵌 character_book | 备注 |
|---|---|---|
| `key` | `keys` | |
| `keysecondary` | `secondary_keys` | |
| `order` | `insertion_order` | 原样拷贝，**不取反** |
| `disable` | `enabled` | **极性相反** |
| `position`（数字 0–7） | `position`（字符串） | **类型不同** |
| `uid` | `id` | |
| `depth` / `probability` / `caseSensitive` / `group` / … | `extensions.*` | 内嵌形态只在 `extensions` 里读 |

---

## 6. ⚠️ 会把 JSON 写"对"但行为写错的 6 个陷阱

这些都不会报错，只会静默失效 —— 是 Phase 0 存在的主要理由。

### 陷阱 1：内嵌 `position` 写成数字 → 静默错位

```js
position: entry.extensions?.position ?? (entry.position === 'before_char' ? 0 : 1)
```

- 字符串 `'before_char'` → `0`
- **其余任何值（含数字 `0`、`null`、缺失）→ `1`（after_char）**

即：内嵌条目想表达"放在角色定义之前"，写数字 `0` 得到的是 **after**。

**本项目规则**：内嵌条目只接受字符串；`position.py` 的 `coerce_char_book_position()` 对 `int`/`bool` 直接抛错，不允许"碰巧对"。
独立世界书才用数字 0–7。

### 陷阱 2：缺 `enabled` → 条目被永久禁用

```js
disable: !entry.enabled   // 缺失时 !undefined === true
```

少写一个字段，条目永不触发，而 JSON 完全合法、不报任何错。

**本项目规则**：`enabled` 在模型里**必填、无默认值**。

### 陷阱 3：用 `name` 当条目标题 → 客户端看不到

`convertCharacterBook` 里**完全没有读取 `entry.name`**。标题来自 `comment`：

```js
comment: entry.comment || '',
addMemo: !!entry.comment,   // 没有 comment 就没有 memo
```

**本项目规则**：条目标题写进 `comment`；不输出 `name`。

### 陷阱 4：用 `uid` 而不是 `id`

```js
if (entry.id === undefined) { entry.id = index; }   // 注释原文：Not in the spec, but this is needed…
uid: entry.id,
```

内嵌条目读的是 **`id`**。写 `uid` 不报错，但会被数组下标顶替 —— 条目顺序一变，uid 就跟着变。

**本项目规则**：内嵌条目输出 `id`（0 起、唯一、整数）。

### 陷阱 5：顶层 `case_sensitive` / `scan_depth` / `probability` / `depth` 是无效字段

```js
caseSensitive: entry.extensions?.case_sensitive ?? null
```

内嵌形态**只从 `extensions.*` 读**这些设置，顶层同名键被忽略。

### 陷阱 6：`priority` 未被读取

`convertCharacterBook` 里没有任何 `priority` 映射。排序由 `insertion_order` + `position` 决定。

**本项目规则**：内嵌条目不输出 `priority`。

### 附：本机 4 张已导入卡的实际偏差（仅作对照记录）

`sillytavern-deployment/character-cards/*.json` 全部命中上述陷阱：

| 现象 | 影响 |
|---|---|
| `position: 1`（数字） | 恰好等于 `after_char`，**碰巧正确**；一旦改成 `0` 就会静默变 `after` |
| 用 `name` 作条目标题 | 在 ST 里不可见（无 memo） |
| 用 `uid` 而非 `id` | 被数组下标顶替 |
| `priority: 10` | 无效字段 |
| 顶层 `case_sensitive` | 被忽略 |

> 这 5 项都不影响「卡能导入、条目能触发」，所以此前没被发现。本项目不沿用这些写法。

---

## 7. Tavo 侧核查结果

| 项 | 结果 |
|---|---|
| Tavo 是什么 | 手机端 AI 角色扮演客户端，包名 `app.bitbear.tav`（Google Play / App Store） |
| 官方文档 | **https://docs.tavoai.dev/**（`/en/`、`/cn/`） |
| 官方文档说了什么 | 只有「可导入 SillyTavern 的卡、支持各大角色卡站点」。**没有任何字段级说明** —— 未记载 V1/V2/V3、PNG/JSON/CHARX、`character_book`、世界书。部分子页 404 或超时 |
| 应用商店页面宣称 | 支持 Spec V1/V2/V3、PNG/JSON/CHARX，与 SillyTavern / JanitorAI / Pygmalion / RisuRealm / Chub 互通。**属营销文案，官方文档未确认** |
| 对 `character_book` 的具体行为 | **完全无法离线验证** |

**结论**：本项目**不做任何 Tavo 专属假设**。策略是输出 ST 1.19 已验证过的格式，在 Tavo 里实际导入并观察（Phase 6），观察结果单独成文。

> ⚠️ 另需实测确认：ST 1.19 的内嵌 `character_book` **不会自动生效** —— `importEmbeddedWorldInfo()` 要用户确认后才把书转存并挂到角色上。Tavo 是否自动生效未知。

---

## 8. V3（备查，Phase 0 不实现）

- `spec: "chara_card_v3"` / `spec_version: "3.0"`，是 V2 的超集。
- PNG 用 `ccv3` tEXt chunk，与 `chara` 同时存在时 `ccv3` 优先。
- 本项目**仍用 V2**：与生产上 4 张可用卡一致，兼容面更宽，且 ST 导出时本身会把 V3 降级写回 `chara`（`src/character-card-parser.js` 注释：`ccv3 is not supported and removed not to create a mismatch`）。
- V3 条目新增 `use_regex`；**`use_regex` 不属于 V2 规范**，本项目 V2 产物不写。
- V3 独立世界书包成 `{ "spec": "lorebook_v3", "data": {...} }`。

---

## 9. 尚未验证 / 存疑项

按 AGENTS 要求显式列出，**不得当成已知事实使用**：

1. **`insertion_order` / `order` 的方向语义冲突。**
   V2 规范称"值越小越靠前"；ST 独立世界书文档称"值越大越靠近上下文末尾"；而 `convertCharacterBook` 是**原样拷贝、不取反**。
   两处说法方向相反，指向同一字段。**Phase 0 不预设方向** —— 条目顺序先用 ST 模板默认值（`order: 100` 起），Phase 6 实测后定论。
2. **内嵌 `character_book` 在 Tavo 中是否自动生效** —— 未知。
3. **Tavo 是否接受 `.json` 直接导入**（ST 1.19 的角色目录扫描只认 `.png`，导入需走 UI 或 `/api/characters/import`）—— 未知。
4. **ST 1.19.0 是否为生产镜像的确切版本。** 部署用 `:latest`；本文以 1.19.0 为准，但未从运行中的 Pod 里读取实际版本号。
5. **`scan_depth` / `token_budget` / `recursive_scanning` 在 `character_book` 顶层的实际生效情况。** 已确认它们在结构上存在，但未核对运行时的取值路径。
6. **`extensions` 的具体键名约定**（ST 回写时用 snake_case 如 `display_index`、`exclude_recursion`）—— 已观察到，但未逐项核对全部键。
7. **本文所有字段表未经过一次真实的「导出 → 导入」往返验证。** 源码级核对不等于实测。

第 7 条是本文最大的局限，也是 Phase 6 存在的原因。

---

## 10. 复核方法（换版本时照做）

```bash
# 1. 取目标 tag 的源码
TAG=1.19.0
base=https://raw.githubusercontent.com/SillyTavern/SillyTavern/$TAG
curl -sL -o world-info.js $base/public/scripts/world-info.js
curl -sL -o char-data.js  $base/public/scripts/char-data.js

# 2. 核对本文 §2–§6 引用的四处代码
grep -n "export function convertCharacterBook" world-info.js
grep -n "export const world_info_position"     world-info.js
grep -n "newWorldInfoEntryDefinition = "       world-info.js
grep -n "DEFAULT_DEPTH\|DEFAULT_WEIGHT"        world-info.js
```

源码与本文不一致时，**先改本文再改代码**。
