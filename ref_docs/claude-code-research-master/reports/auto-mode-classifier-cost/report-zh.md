# Auto Mode 的隱藏分類器成本 — 每次工具操作都在背後多發一次 LLM 請求

> **CLI 版本：** @anthropic-ai/claude-code v2.1.88（build 2026-03-30）
> **日期：** 2026-03-31
> **方法：** 靜態逆向 cli.js minified bundle（16,667 行，13 MB）

---

## 摘要

Claude Code 的 Auto Mode——標榜「只在必要時才詢問權限」的模式——在每一次有副作用的工具操作前，都會暗中發一次 API 請求。這個請求會把整段對話的精簡版送進一個分類器 LLM，由它決定操作該放行還是擋下。

在近期的版本（v2.1.88），分類器的模型從寫死的 Sonnet 改為繼承主對話模型。如果你是 Max 訂閱用戶，分類器也跑 Opus——跟主對話同等級。每次 Edit、Write、Bash、MCP 工具呼叫，都在額外消耗 Opus 等級的 token。

分類器有掛 `cache_control: ephemeral`，但只有固定不變的部分（system prompt 和 CLAUDE.md）能被快取。佔比最大、成長最快的對話記錄沒有快取斷點，每次都以全額 input 價計費。

Statsig 遠端還有一個 two-stage classifier 開關，開了以後每次工具操作最多跑兩次分類器——使用者完全看不到也控制不了。

---

## 目錄

1. [分類器在做什麼](#1-分類器在做什麼)
2. [什麼時候觸發、什麼時候跳過](#2-什麼時候觸發什麼時候跳過)
3. [分類器收到什麼內容](#3-分類器收到什麼內容)
4. [模型選擇——為什麼 Max 用戶付更多](#4-模型選擇為什麼-max-用戶付更多)
5. [快取的假象](#5-快取的假象)
6. [Two-Stage Classifier——遠端開關](#6-two-stage-classifier遠端開關)
7. [成本估算](#7-成本估算)
8. [緩解方案](#8-緩解方案)
9. [原始碼參考](#9-原始碼參考)

---

## 1. 分類器在做什麼

開啟 Auto Mode 後，Claude Code 不再每次操作都問你要不要放行，改由另一個 LLM 來做判斷。流程是這樣的：

```
Claude 提出一個工具操作（例如 Edit 一個檔案）
  │
  ├─ 這個工具在硬編碼白名單裡？
  │   是 → 直接執行，不發 API
  │
  ├─ alwaysAllowRules 有匹配？
  │   是 → 直接執行，不發 API
  │
  └─ 都不是 → 發一次分類器 API 請求
      │
      ├─ 分類器說 allow → 執行
      ├─ 分類器說 deny  → 擋下
      └─ 分類器說 ask   → 才問你
```

分類器是一個完整的 API 請求：有自己的 system prompt（權限策略），自己的對話記錄（精簡版 transcript），和一個專用的工具（`classify_result`）來回傳判定結果。設定 `temperature: 0`，`maxRetries: 10`。

**來源：** 函式 `kL8()`，byte offset 7,027,377。

---

## 2. 什麼時候觸發、什麼時候跳過

### 硬編碼白名單——完全跳過分類器

這些工具不管什麼模式，都不會觸發分類器：

```
Read, Grep, Glob, LSP, ToolSearch,
ListMcpResourcesTool, ReadMcpResourceTool,
TodoWrite, TaskCreate, TaskGet, TaskUpdate, TaskList, TaskStop, TaskOutput,
AskUserQuestion, EnterPlanMode, ExitPlanMode,
TeamCreate, TeamDelete, SendMessage, Sleep
```

**來源：** `isAutoModeAllowlistedTool()`，Set `N$Y`，byte offset 9,850,151。

### 使用者設定的規則——路徑匹配跳過

如果在 settings 裡設了 `alwaysAllowRules`，帶路徑 pattern（例如 `Edit(/your/project/**)`），權限檢查階段就直接回 allow，分類器不會被觸發。只對 Edit 和 Write 有效——Bash 和 MCP 工具沒辦法做路徑匹配。

**來源：** 函式 `Qj6()`，byte offset 11,419,986。

### 其他——全部觸發

Edit、Write、Bash、PowerShell、Agent spawn、MCP 工具呼叫、NotebookEdit、WebSearch、WebFetch、Skill、CronCreate/Delete，通通會觸發分類器。一個 turn 裡 Claude 連用 5 個工具，就是 5 次分類器呼叫。

---

## 3. 分類器收到什麼內容

分類器不是只看這次的操作。它會收到整段對話的精簡版。

### Transcript 建構（`tb4()`）

`tb4()` 位於 byte offset 7,020,034，處理完整的訊息陣列：

- **使用者訊息** → 保留文字內容（你打的每句話）
- **Claude 回覆** → 只保留 `tool_use` blocks（工具名 + input 參數）
- **工具執行結果** → 全部丟棄
- **Claude 的文字回覆** → 全部丟棄

也就是說，Claude 在這段對話中用過的每一個工具——包括 Read、Grep 這些本身不觸發分類器的白名單工具——都會出現在之後每次分類器呼叫的 transcript 裡。

### 各工具怎麼表達自己

每個工具都有一個 `toAutoClassifierInput()` 方法，決定送什麼進去：

```js
// Write — 路徑 + 完整檔案內容 💸
toAutoClassifierInput(input) { return `${input.file_path}: ${input.content}` }

// Edit — 路徑 + new_string（不含 old_string）
toAutoClassifierInput(input) { return `${input.file_path}: ${input.new_string}` }

// Bash / PowerShell — 完整指令字串
toAutoClassifierInput(input) { return input.command }

// Read — 只有路徑（不觸發分類器，但出現在 transcript）
toAutoClassifierInput(input) { return input.file_path }
```

Write 是最大的 token 消耗來源——Claude 寫一個 500 行的檔案，那 500 行全部進分類器的 input。

### 分類器實際看到的內容

```
User: 修一下 foo.ts 的錯誤處理
Read src/foo.ts                                          ← 在 transcript 裡，沒觸發分類器
Grep {"pattern":"handleError","path":"src/"}             ← 在 transcript 裡，沒觸發分類器
Edit {"file_path":"src/foo.ts","new_string":"..."}       ← 之前的操作，現在在 transcript 裡
User: 跑一下測試
Bash {"command":"npm test"}                              ← 之前的操作，現在在 transcript 裡
Edit {"file_path":"src/bar.ts","new_string":"..."}       ← 這次要判斷的操作
```

Transcript 隨著每次工具使用持續增長。讀了 10 個檔案、grep 了 5 次、編輯了 3 個檔案——這 18 次操作全部出現在下一次分類器呼叫的 input 裡。

**來源：** 函式 `tb4()` offset 7,020,034、`qx4()` offset 7,021,021。

---

## 4. 模型選擇——為什麼 Max 用戶付更多

### 解析鏈

分類器模型由 `lb4()` 決定，byte offset 7,031,025：

```js
function lb4() {
  // 1. Statsig 遠端覆蓋（最高優先）
  let config = featureFlag("tengu_auto_mode_config", {});
  if (config?.model) return config.model;

  // 2. 退回主對話模型
  return getMainLoopModel();
}
```

`getMainLoopModel()` 的解析路徑 `D5()` → `jS()` → `If()` → `KG()`：

```js
function KG() {
  if (isMaxSubscription())    return "claude-opus-4-6[1m]";
  if (isTeam5xSubscription()) return "claude-opus-4-6[1m]";
  return "claude-sonnet-4-6";  // 其他所有人
}
```

### 各訂閱類型的影響

| 訂閱類型 | 主對話模型 | 分類器模型 | 相對 input 成本 |
|---|---|---|---|
| Max | claude-opus-4-6 | claude-opus-4-6 | 1×（最貴） |
| Team 5x | claude-opus-4-6 | claude-opus-4-6 | 1× |
| Pro / Free | claude-sonnet-4-6 | claude-sonnet-4-6 | ~0.2× |
| Bedrock/Vertex | claude-sonnet-4-5 | claude-sonnet-4-5 | ~0.2× |

Max 用戶的分類器單次成本和主對話一樣。在更早的版本（v2.1.85），分類器是寫死用 `"claude-sonnet-4-6"`。改成繼承主對話模型之後，Max 用戶每次分類器呼叫的成本暴增約 5 倍。

---

## 5. 快取的假象

分類器請求在三個地方掛了 `cache_control: { type: "ephemeral" }`，看起來好像有快取。實際效果沒那麼好。

### 快取斷點分布

```
┌─ system prompt ─────────── cache_control ──┐  斷點 1（穩定）
│  權限策略、規則                               │
└────────────────────────────────────────────┘

┌─ CLAUDE.md ─────────────── cache_control ──┐  斷點 2（穩定）
│  使用者的 CLAUDE.md 內容                      │
└────────────────────────────────────────────┘
                                                 ↑ 快取命中到這裡為止
                                                 ↓ 以下每次都在變
┌─ Transcript + Action ─────────────────────┐
│  User: 你的第一句話                          │  無斷點
│  Read src/foo.ts                           │  無斷點
│  Edit {"file_path":..., "new_string":...}  │  無斷點
│  User: 你的第二句話                          │  無斷點
│  ...每次 tool use 後都在增長...              │
│  Bash {"command":"npm test"} cache_control │  斷點 3（每次不同）
└────────────────────────────────────────────┘
```

Anthropic API 的快取匹配方式是找**最長的、結尾有 cache 斷點的相同前綴**。Transcript 在斷點 2 之後，而且每次呼叫都在增長（新的工具操作被追加進去），所以快取只匹配到斷點 2 就斷了。

### 實際快取效率

| Session 階段 | 固定部分（快取，10% 計費） | Transcript（全額計費） | 實際省了多少 |
|---|---|---|---|
| 前段（5 turns） | ~2k tokens | ~2k tokens | ~45% |
| 中段（20 turns） | ~2k tokens | ~6k tokens | ~22% |
| 後段（50+ turns） | ~2k tokens | ~15k tokens | ~9% |

固定部分（system prompt + CLAUDE.md）大約 1-2k tokens，不會變。Transcript 隨工具使用量線性增長。到中後段，快取能省的已經很有限了。

**來源：** `pU()`（cache_control 工廠）offset 11,539,575；`qMz()`（CLAUDE.md 注入）offset 7,021,531。

---

## 6. Two-Stage Classifier——遠端開關

Statsig 遠端閘門可以啟用第二階段分類。函式 `OMz()`，byte offset ~7,024,500：

### 運作方式

Feature flag `tengu_auto_mode_config.twoStageClassifier` 可以設定為：

| 值 | 行為 | 每次 tool use 最多幾次 API call |
|---|---|---|
| `false`（預設） | 單次分類 | 1 |
| `"fast"` | 快速判斷：max_tokens=256，遇到 `</block>` 就停 | 1 |
| `"thinking"` | 完整推理：max_tokens=4096，帶 thinking | 1 |
| `true` 或 `"both"` | 先跑 fast，如果沒有立即放行就再跑 thinking | **2** |

設定為 `true` 或 `"both"` 時，一次 Edit 操作最多觸發兩次分類器 API call——Max 用戶兩次都是 Opus。

### 使用者能控制嗎

不能。這個 flag 由 Statsig（Anthropic 的 feature flag 服務）控制，可以在不通知的情況下對特定用戶、群組或全域啟用。沒有環境變數或設定可以覆蓋它。

**來源：** `$x4()` offset 7,031,120；`wMz()` 和 `OMz()` offset ~7,024,500。

---

## 7. 成本估算

### 單次分類器呼叫

假設中段對話 transcript 約 4k tokens，system prompt + CLAUDE.md 約 2k tokens：

| 用戶類型 | 模型 | 快取部分（2k @ 10%） | 非快取部分（4k @ 100%） | Output（~100 tokens） | 單次成本 |
|---|---|---|---|---|---|
| Max | Opus | $0.003 | $0.060 | $0.008 | ~$0.071 |
| Pro | Sonnet | $0.001 | $0.012 | $0.003 | ~$0.016 |

### 整個 Session 的累積

20 個 turn、每 turn 3 次有副作用的操作 = 60 次分類器呼叫：

| 用戶類型 | 分類器總成本 | 主對話總成本 | 分類器開銷佔比 |
|---|---|---|---|
| Max（Opus） | ~$4.3 | ~$15–30 | **15–28%** |
| Pro（Sonnet） | ~$1.0 | ~$3–6 | **15–28%** |

如果 two-stage 被開啟：上面的數字乘以 1.5–2×。

### 複利效應

Transcript 隨著每次工具操作增長。前期的分類器呼叫很便宜（transcript 小），後期的越來越貴。在 50 turn 的重度 session 裡，最後幾次分類器呼叫的 transcript 可以超過 15k tokens——接近主對話 system prompt 的規模了。

---

## 8. 緩解方案

### 方案 1：設定路徑白名單（零修改）

在 `.claude/settings.local.json` 裡：

```json
{
  "permissions": {
    "allow": [
      "Edit(/your/project/**)",
      "Write(/your/project/**)"
    ]
  }
}
```

匹配的操作直接跳過分類器。只對 Edit/Write 有效，Bash、Agent、MCP 工具仍然會觸發分類器。

### 方案 2：Patch 分類器模型降為 Haiku（推薦）

把 cli.js 裡的 `lb4()` 改成固定回傳 Haiku：

```
找：  function lb4(){let q=g8("tengu_auto_mode_config",{});if(q?.model)return q.model;return D5()}
換成：function lb4(){return"claude-haiku-4-5-20251001"}
```

Input 成本降約 60 倍（Opus → Haiku）。分類器做的是簡單的放行/擋下判斷，Haiku 綽綽有餘。

**唯一性檢查：** 該 find pattern 在 cli.js 中只匹配 1 處。

### 方案 3：直接關掉分類器

Patch `kL8()` 永遠回傳 allow：

```
找：  async function kL8(q,K,_,z,Y){let $=eb4(_),
換成：async function kL8(q,K,_,z,Y){return{shouldBlock:!1,reason:"patched"};let $=eb4(_),
```

分類器 API call 完全消失。Auto Mode 變成完全自動、無安全檢查。

### 方案 4：不要用 Auto Mode

每次操作手動確認。零分類器開銷，最大的操作摩擦。

---

## 9. 原始碼參考

| 符號 | Byte offset | 功能 |
|---|---|---|
| `kL8()` | 7,027,377 | 分類器主函式 |
| `tb4()` | 7,020,034 | 對話 transcript 建構 |
| `qx4()` | 7,021,021 | 訊息 → 純文字轉換 |
| `qMz()` | 7,021,531 | 分類器專用 CLAUDE.md 注入 |
| `lb4()` | 7,031,025 | 分類器模型選擇 |
| `KG()` | 2,429,000 | 主對話模型解析（Max → Opus） |
| `HS()` | 3,508,465 | Max 訂閱檢查 |
| `DG6()` | 3,462,663 | Auto Mode 啟用條件 |
| `N$Y` | 9,850,151 | 硬編碼白名單 Set |
| `Qj6()` | 11,419,986 | alwaysAllowRules 權限檢查 |
| `OMz()` | ~7,024,500 | Two-stage classifier |
| `$x4()` | 7,031,120 | twoStageClassifier flag 讀取 |
| `CN()` | 11,567,782 | API 呼叫包裝器 |
| `pU()` | 11,539,575 | cache_control 工廠 |

### 版本差異

| 項目 | v2.1.85 | v2.1.88 |
|---|---|---|
| 分類器模型 | 寫死 `"claude-sonnet-4-6"` | 動態：Max → Opus，其他 → Sonnet |
| Max 用戶分類器成本 | Sonnet 等級 | **Opus 等級（約 5 倍）** |
| Two-stage classifier | 不存在 | 新增，Statsig 閘門控制 |
| 白名單快速放行 | 不存在 | 新增，唯讀工具跳過 |
| alwaysAllowRules 繞過 | 未確認 | 確認有效 |
| Prompt caching | 未確認 | 確認啟用（ephemeral，3 個斷點） |
