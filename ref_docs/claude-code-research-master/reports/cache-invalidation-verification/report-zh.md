# 快取失效驗證 — 為什麼 MCP 工具的載入不會破壞提示快取

> **CLI 版本：** @anthropic-ai/claude-code v2.1.85（build 2026-03-26）
> **日期：** 2026-03-28
> **狀態：** 已驗證（原始碼 + 官方文件 + 實測）

---

## 摘要

我們本來要驗證一個看起來理所當然的結論：當 Claude Code 的延遲工具載入機制透過 ToolSearch 發現一個新的 MCP 工具時，工具陣列改變了，快取前綴就跟著變動，整個提示快取就得以 125% 的成本重建。cli.js 裡面的內嵌文件也這樣寫——「新增、移除或重新排序工具會讓整個快取失效」。

我們在 283k token 的對話中做了實測，然後盯著 /cost 看。什麼都沒動。

這篇報告記錄了完整的調查過程：逆向 CLI v2.1.85、搜尋 15 個以上的 GitHub issue、閱讀 Anthropic 官方 API 文件。答案是：`defer_loading` 不只是一個「延後載入工具 schema」的旗標，它從根本上改變了伺服器處理工具定義的方式。帶有延遲旗標的工具，完全不參與快取前綴的計算。快取毫髮無傷。

非延遲工具仍然會按照文件說明破壞快取。系統提示的快取策略本身會根據是否有非延遲 MCP 工具而切換。而且至少還有六種其他操作會觸發完整的快取重建。本報告把這些全部整理出來了。

---

## 目錄

1. [預測與矛盾](#1-預測與矛盾)
2. [提示快取的運作機制](#2-提示快取的運作機制)
3. [完整的快取斷點分布圖](#3-完整的快取斷點分布圖)
4. [系統提示處理器中的三種快取策略](#4-系統提示處理器中的三種快取策略)
5. [延遲工具載入的完整流程](#5-延遲工具載入的完整流程)
6. [為什麼延遲工具不會破壞快取——完整證據鏈](#6-為什麼延遲工具不會破壞快取完整證據鏈)
7. [哪些操作真的會破壞快取——實用情境指南](#7-哪些操作真的會破壞快取實用情境指南)
8. [研究方法](#8-研究方法)
9. [參考資料](#9-參考資料)

---

## 1. 預測與矛盾

### 原始推理鏈

我們的分析邏輯是這樣走的：

1. Anthropic 的提示快取使用**嚴格的前綴比對**。伺服器會按照固定的渲染順序 `tools → system → messages` 逐位元組計算快取金鑰。
2. Claude Code 的延遲工具載入機制一開始會把 MCP 工具**排除**在工具陣列外。當 ToolSearch 發現一個工具後，它會在下一輪被**加入**陣列。
3. 加入一個工具就改變了工具陣列。既然工具在渲染順序的位置 0，它後面的所有內容——系統提示、所有訊息——都變成前綴不匹配。
4. 前綴不匹配會強制整個快取以 125% 的基礎成本重新寫入。

在 283k token 的上下文中，完整重建的成本相當於大約 354k token 的寫入費用。這個幅度在 /cost 裡應該看得很清楚。

### 實驗

- **環境：** 執行中的 Claude Code CLI session（Opus 4，Claude Max 訂閱），283k 上下文，5 小時額度已用 27%，連接多個 MCP server。
- **動作：** 使用 ToolSearch 首次取得一個 MCP 工具的 schema。
- **預期結果：** /cost 跳升數個百分點（估計 3-7%）。
- **實際結果：** /cost 維持在 27%。沒有任何可觀察的變化。

### 問題

推理鏈在哪裡斷掉了？是快取重建確實發生了但看不到？還是機制本身就跟我們假設的不一樣？

---

## 2. 提示快取的運作機制

在解釋延遲工具為什麼是特例之前，先來搞清楚基礎：CLI v2.1.85 的快取系統到底怎麼運作？

### 渲染順序

Anthropic API 計算快取前綴時固定按照以下順序，跟 JSON key 的實際排列無關：

```
位置 0: tools 陣列       （所有工具定義）
位置 1: system prompt     （所有系統提示區塊）
位置 2: messages          （對話歷史）
```

cli.js 內嵌的文件（字元位移 ~12553825）這樣寫：

> *「渲染順序是：tools → system → messages。在最後一個 system block 上放斷點，可以同時快取 tools 和 system。」*

程式碼裡 JS 物件的 key 順序是 `model → messages → system → tools`，但這不重要。API 伺服器永遠用上面的標準渲染順序。

### cache_control 斷點的運作方式

在某個內容區塊上放一個 `cache_control` 標記，等於告訴伺服器：「從請求開頭到這個區塊為止，算一個快取金鑰。」如果金鑰命中現有的快取條目，這段內容就從快取讀取（只要 10% 的成本）。如果沒命中，就寫入新的快取條目（125% 的成本）。

產生這些標記的工廠函式是 `XU()`（字元位移 ~11366730）：

```js
function XU({scope, querySource} = {}) {
  return {
    type: "ephemeral",                              // 固定存在
    ...MVY(querySource) ? {ttl: "1h"} : {},         // 允許名單內的來源給 1h TTL
    ...scope === "global" ? {scope: "global"} : {}   // 跨 session 快取
  }
}
```

三個欄位，各有特定含義：
- **`type: "ephemeral"`** — 標準快取標記，永遠存在。
- **`ttl: "1h"`** — 延長存活時間（預設只有 5 分鐘）。寫入成本從 1.25 倍漲到 2 倍，但讀取仍然是 10%。
- **`scope: "global"`** — 跨對話共用的快取。只用在不會變動的靜態內容上。

### 哪些地方有斷點、哪些沒有

這正是原本分析的盲點。不是 request 的每個部分都會拿到 `cache_control` 標記：

| 內容 | 有 `cache_control`？ | Scope | 用途 |
|------|---------------------|-------|------|
| 工具定義 | **沒有**（預設） | — | 工具作為系統斷點之前的前綴，被隱式快取 |
| 系統提示靜態區 | **有** | `"org"` 或 `"global"` | 把 tools + system 一起快取 |
| 系統提示動態區 | **沒有** | — | 經常變動（日期、git 狀態），不快取 |
| 最後 1-2 則訊息 | **有** | 依請求而定 | 滑動視窗，每一輪往前推進 |

工具定義本身**沒有** `cache_control`。把工具轉成 API 格式的 `vm8()` 函式只在接收到 `cacheControl` 參數時才會加上標記——但主查詢函式 `vuK()` 從來不會傳這個參數：

```js
// vm8() — 工具 schema 建構器
async function vm8(tool, options) {
  let schema = {
    name: tool.name,
    description: await tool.prompt(...),
    input_schema: tool.inputSchema
  };
  if (options.deferLoading) schema.defer_loading = true;
  if (options.cacheControl) schema.cache_control = options.cacheControl;  // 實務上從未被呼叫
  return schema;
}
```

換句話說，工具會被快取，單純是因為它們排在系統提示斷點之前。系統提示的 `cache_control` 標記建立了一個斷點，涵蓋它前面的所有內容——包括所有工具。工具沒有獨立的快取層。

---

## 3. 完整的快取斷點分布圖

以下是 CLI v2.1.85 的 API request 中每一個會拿到 `cache_control` 標記的位置。

### 系統提示的斷點（透過 `yVY()` → `Z57()`）

系統提示被拆成多個區塊，由 `Z57()` 分配各區塊的 `cacheScope`，再由 `yVY()` 轉成實際的 `cache_control` 標記：

```js
// yVY() — 系統提示格式化
function yVY(blocks, cachingEnabled, options) {
  return Z57(blocks, options).map(block => ({
    type: "text",
    text: block.text,
    // 只在啟用快取 且 scope 不是 null 的情況下加 cache_control
    ...cachingEnabled && block.cacheScope !== null
      ? {cache_control: XU({scope: block.cacheScope, querySource: options?.querySource})}
      : {}
  }));
}
```

`cacheScope` 為 `null` 的區塊不會拿到任何快取標記——那是「動態區」，每一輪都會變。

### 訊息的斷點（透過 `kVY()` → `WVY()` / `ZVY()`）

```js
// kVY() — 訊息陣列處理器
function kVY(messages, cachingEnabled, querySource, ..., skipCacheWrite) {
  // 目標索引：最後一則訊息，或倒數第二則（skipCacheWrite 時）
  let targetIndex = skipCacheWrite ? messages.length - 2 : messages.length - 1;

  return messages.map((msg, index) => {
    let isTarget = index === targetIndex;
    if (msg.type === "user") return WVY(msg, isTarget, cachingEnabled, querySource);
    return ZVY(msg, isTarget, cachingEnabled, querySource);
  });
}
```

只有最後（或倒數第二）則訊息的最後一個 content block 會拿到斷點。這形成一個滑動視窗——每新增一輪對話，斷點就往前移，伺服器把斷點之前的內容都從快取讀取。

### 視覺化總覽

```
┌─────────────────────────────────────────────────┐
│ API Request（渲染順序）                            │
│                                                  │
│  ┌─ tools ───────────────────────────────────┐  │
│  │  內建工具（Read, Write, Bash, ...）         │  │
│  │  MCP 工具（帶 defer_loading: true）         │  │  ← 任何工具都沒有 cache_control
│  │  額外的工具 schema                          │  │
│  └───────────────────────────────────────────┘  │
│                                                  │
│  ┌─ system prompt ───────────────────────────┐  │
│  │  [帳單標頭]             scope: null        │  │  ← 不快取
│  │  [組織/版本區塊]         scope: "org"       │  │  ← cache_control: ephemeral
│  │  [靜態指令]              scope: "org"       │──│──── 斷點：同時快取 tools + system
│  │  [動態內容]              scope: null        │  │  ← 不快取（日期、git 狀態等）
│  └───────────────────────────────────────────┘  │
│                                                  │
│  ┌─ messages ────────────────────────────────┐  │
│  │  [訊息 1]                                  │  │
│  │  [訊息 2]                                  │  │
│  │  ...                                      │  │
│  │  [最後一則訊息 - 最後一個 content block]     │──│──── 斷點：快取之前所有訊息
│  └───────────────────────────────────────────┘  │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## 4. 系統提示處理器中的三種快取策略

`Z57()` 負責決定系統提示的快取策略。它分三條路徑，走哪條取決於兩個條件：全域快取是否開啟、以及是否存在非延遲的 MCP 工具。

### 分支一：標準模式（沒有全域快取）

**觸發條件：** 全域快取的 feature flag 關閉。

```
帳單標頭        → cacheScope: null    （不快取）
org 區塊       → cacheScope: "org"   （org 層級快取）
其餘內容        → cacheScope: "org"   （合併成一個區塊，org 層級快取）
```

最直接的路徑。系統提示的區塊拿到 `ephemeral` 快取標記，而系統斷點把它前面的所有內容（包括工具）一起快取。

### 分支二：全域快取 + 邊界標記

**觸發條件：** 全域快取開啟、沒有非延遲的 MCP 工具、且系統提示中存在 `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__` 邊界標記。

```
邊界之前的靜態區塊  → cacheScope: "global"   （跨 session 共用快取）
邊界之後的動態區塊  → cacheScope: null        （不快取）
```

`scope: "global"` 標記告訴伺服器：這段內容在所有對話中都一樣，只需要快取一次就可以共用。這是效率最高的模式，但要求內容穩定不變。

### 分支三：Tool-based cache 模式

**觸發條件：** 全域快取開啟，**且**目前使用的工具集裡有至少一個**非延遲**的 MCP 工具。

這個分支的名字很容易讓人誤解。「Tool-based cache」並不是指工具拿到了自己的 `cache_control`。具體來說就是：**系統提示的快取 scope 從 global 降為 org**，因為有非延遲 MCP 工具在工具陣列裡，tools-to-system 這段前綴隨時可能變動。

實際的程式碼邏輯：

```js
// 在 vuK()（主查詢函式）中：

// W = 全域快取是否開啟？
let W = isGlobalCacheEnabled() && (forceGlobalCache || featureFlag("tengu_system_prompt_global_cache"));

// Z = 這個工具是不是延遲的？
let Z = (tool) => toolSearchEnabled && (isDeferredTool(tool) || isLspConnecting(tool));

// G = 有沒有非延遲的 MCP 工具？
let G = W && activeTools.some(tool => tool.isMcp === true && !Z(tool));

// G 決定快取策略：
let globalCacheStrategy = W ? (G ? "none" : "system_prompt") : "none";

// G 被傳給 yVY 作為 skipGlobalCacheForSystemPrompt
let systemBlocks = yVY(prompt, cachingEnabled, {skipGlobalCacheForSystemPrompt: G, ...});
```

當 `G` 為 true（有非延遲 MCP 工具）：

```
帳單標頭    → cacheScope: null    （不快取）
org 區塊   → cacheScope: "org"   （從 "global" 降級為 "org"）
其餘內容    → cacheScope: "org"   （降級）
```

遙測事件 `tengu_sysprompt_using_tool_based_cache` 會在此時觸發，記錄這次降級。

**為什麼要降級？** 非延遲的 MCP 工具帶有完整的 schema 在工具陣列裡。如果 MCP server 重啟後工具描述改變了，工具前綴就會變動，導致任何 `scope: "global"` 的快取條目失效。把 scope 降為 `"org"` 可以避免跨對話共用一個可能不穩定的快取。

**對延遲工具的關鍵影響：** 延遲工具的 `Z(tool)` 返回 `true`，所以 `!Z(tool)` 是 `false`，它們**永遠不會觸發 `G`**。當所有 MCP 工具都是延遲的（ToolSearch 啟用時的常態），`G` 保持 `false`，系統提示維持原本的 `"global"` 或 `"org"` 快取 scope。延遲工具完全不影響這個計算。

---

## 5. 延遲工具載入的完整流程

這裡完整走一遍流程：從「工具被註冊」到「工具出現在 API request 裡」，每一步都發生了什麼。

### 第一步：所有 MCP 工具一開始都是延遲的

`isDeferredTool()`（內部代號 `I0()`，位移 ~5318984）的第一個判斷非常直接：

```js
function isDeferredTool(tool) {
  if (tool.isMcp === true) return true;   // 所有 MCP 工具都是延遲的
  if (tool.name === "ToolSearch") return false;
  // ... 其他 feature flag 檢查
  return tool.shouldDefer === true;
}
```

每一個 MCP 工具，不管怎麼設定，都會回傳 `true`。使用者無法改變這個行為。

### 第二步：Tool Search 模式決定什麼進入工具陣列

`Ir6()` 負責判斷工具載入模式：

| 模式 | 觸發條件 | 行為 |
|------|---------|------|
| `"tst"`（tool search） | `ENABLE_TOOL_SEARCH=true` 或 `=0` | ToolSearch 啟用，延遲工具被過濾 |
| `"tst-auto"` | 延遲工具的 token 數超過上下文閾值 | 自動啟用 tool search |
| `"standard"` | 以上皆非 | 所有工具都送出，ToolSearch 被排除 |

Tool search 模式啟用時（`J = true`），工具陣列會被過濾：

```js
// X = 實際送給 API 的工具
X = allTools.filter(tool => {
  if (!isDeferredTool(tool)) return true;     // 非延遲工具：一定包含
  if (tool.name === "ToolSearch") return true; // ToolSearch 本身：一定包含
  return discoveredTools.has(tool.name);       // 延遲工具：只有被發現過的才包含
});
```

尚未被發現的延遲工具，**完全不存在於** API request 中。

### 第三步：掃描器從對話歷史找出已發現的工具

每次 API 呼叫之前，掃描函式 `wU()` 會走過整個訊息歷史，找出 `tool_reference` 區塊——這些區塊是 ToolSearch 回傳結果時產生的：

```js
function extractDiscoveredToolNames(messages) {
  let discovered = new Set();
  for (let msg of messages) {
    if (msg.role !== "user") continue;
    for (let block of msg.content) {
      if (block.type === "tool_result") {
        for (let inner of block.content) {
          if (inner.type === "tool_reference") {
            discovered.add(inner.tool_name);
          }
        }
      }
    }
  }
  // 也從壓縮的 metadata 中恢復
  return discovered;
}
```

### 第四步：被發現的工具帶著 defer_loading: true 進入陣列

當工具被發現後，它通過了 `X` 的過濾、被送進 API request。但它**仍然**帶有 `defer_loading: true`：

```js
// Z = 這個工具是否標記為延遲？
let Z = (tool) => toolSearchEnabled && (isDeferredTool(tool) || isLspConnecting(tool));

// 在 vm8() 中：
if (options.deferLoading) schema.defer_loading = true;
// deferLoading = Z(tool) — 所有 MCP 工具都是 true，包括已發現的
```

工具帶著完整 schema（name, description, input_schema）**加上** `defer_loading: true` 旗標進入 API request。這個旗標就是給伺服器的關鍵訊號。

### 第五步：伺服器透過 tool_reference 在訊息中展開工具

對話歷史中的 `tool_reference` 區塊告訴伺服器要在哪裡讓工具可用。Anthropic 官方文件這樣說：

> 「Tool Search Tool 不會破壞提示快取，因為延遲工具完全被排除在初始提示之外。它們只有在 Claude 搜尋到之後才會加入上下文，所以你的系統提示和核心工具定義仍然可以被快取。」

伺服器在訊息歷史中展開 `tool_reference` 區塊，而不是去改動工具前綴。前綴——也就是決定快取金鑰的那段內容——保持穩定。

### 時序圖

```
第 1 輪（發現之前）：
  tools: [Bash, Read, Write, ..., ToolSearch]
  system: [...這裡有 cache_control 斷點...]
  messages: [user: "做些什麼"]
  → 快取：tools+system 一起被快取 ✓

第 2 輪（呼叫 ToolSearch）：
  tools: [Bash, Read, Write, ..., ToolSearch]          ← 沒有變化
  system: [一樣...]
  messages: [..., assistant: 呼叫 ToolSearch, user: tool_result 包含 tool_reference]
  → 快取：tools+system 命中 ✓，messages 延伸

第 3 輪（發現之後）：
  tools: [Bash, Read, Write, ..., ToolSearch, mcp__server__tool(defer_loading:true)]
  system: [一樣...]
  messages: [...]
  → client 端的 tools 陣列改變了，但伺服器忽略 defer_loading 的工具
  → 快取：tools+system 命中 ✓（伺服器把延遲工具排除在前綴計算之外）
```

---

## 6. 為什麼延遲工具不會破壞快取——完整證據鏈

原始預測錯了。以下把完整的證據鏈整理出來。

### 證據一：API 設計約束 — defer_loading 和 cache_control 互斥

Anthropic API 明確拒絕在同一個工具上同時設定 `defer_loading: true` 和 `cache_control`。來自 [GitHub Issue #30920](https://github.com/anthropics/claude-code/issues/30920)：

```
API Error 400:
"Tool 'mcp__atlassian__getConfluencePage' cannot have both defer_loading=true
and cache_control set. Tools with defer_loading cannot use prompt caching."
```

這不是 bug，是刻意的設計約束。如果延遲工具要參與快取前綴的計算，它們就需要 `cache_control` 標記來定義斷點。API 禁止兩者共存，正是因為**延遲工具在架構上就被排除在前綴之外**。

**證據強度：已確認**（API 行為，可重現的錯誤訊息）

### 證據二：官方文件

Anthropic 的 Tool Search Tool 文件寫道：

> 「Tool Search Tool 不會破壞提示快取，因為延遲工具完全被排除在初始提示之外。它們只有在 Claude 搜尋到之後才會加入上下文，所以你的系統提示和核心工具定義仍然可以被快取。」

**證據強度：已確認**（官方文件）

### 證據三：原始碼 — 延遲工具不觸發快取策略降級

`skipGlobalCacheForSystemPrompt` 旗標（控制系統提示快取是否降級）的計算方式：

```js
let G = globalCacheEnabled && activeTools.some(tool => tool.isMcp === true && !isDeferred(tool));
```

延遲工具（`isDeferred = true`）產生 `!isDeferred = false`，所以它們被排除在這個檢查之外。即使延遲工具被發現並加入工具陣列，它依然是延遲的（`isDeferredTool()` 對所有 MCP 工具無條件返回 true）。系統提示的快取策略從頭到尾不受影響。

**證據強度：已確認**（原始碼，CLI v2.1.85）

### 證據四：實測

在 283k token 的上下文中，我們使用 ToolSearch 發現了一個 MCP 工具並繼續對話。/cost 沒有任何變化（維持在 5 小時額度的 27%）。

如果真的發生了完整的快取重建，在這個上下文大小下的估計成本：
- 快取寫入：~283k × 1.25 = ~354k token 等價成本
- 以 Opus 4 費率（$15/MTok 輸入）計算：每次約 $5.31
- 佔 5 小時 ~1M token 預算的百分比：約 3-7%

/cost 完全沒有變動，與快取維持完整的假設一致。

**證據強度：支持**（與假設一致，但 /cost 精度可能遮蔽小幅變化）

### 證據五：Bug 歷史確認約束有在執行

CLI v2.1.69 有一個 bug，不小心在 MCP 工具上同時設定了 `defer_loading` 和 `cache_control`。結果不是快取重建，而是**API 直接回傳錯誤**，導致所有 MCP 工具呼叫全部失敗（[Issue #30989](https://github.com/anthropics/claude-code/issues/30989)）。API 不會悄悄處理這種情況，而是直接拒絕請求。這證實了伺服器把延遲工具和快取參與視為根本不相容。

**證據強度：已確認**（可重現的 v2.1.69 regression）

### 證據六：設計意圖

整個延遲工具載入系統的存在就是為了降低 token 成本。Agent SDK repo 的 [Issue #124](https://github.com/anthropics/claude-agent-sdk-typescript/issues/124) 記錄了一個典型的多 server MCP 設定會消耗 15,000-20,000 token 在工具定義上。延遲載入可以減少 85% 以上。如果發現一個延遲工具就觸發完整的快取重建（整個上下文的 125%），省下的 token 在第一次使用時就全部賠掉了——那這機制根本沒有意義。

**證據強度：推論**（設計意圖，非直接證明）

### 結論：原始推理在哪裡斷裂

推理鏈在第 3 步斷裂了：

> ~~3. 加入一個工具就改變了工具陣列。既然工具在渲染順序的位置 0，它後面的所有內容都變成前綴不匹配。~~

**修正：** 加入一個**非延遲**工具會改變快取前綴。加入一個**延遲**工具（帶有 `defer_loading: true`）不會，因為伺服器把延遲工具排除在前綴計算之外。`defer_loading` 旗標就是區分這兩種情況的伺服器端訊號。

內嵌文件裡說的「新增工具會讓整個快取失效」，對一般情況是正確的——它描述的是加入一個普通工具定義的行為。它沒有考慮到 `defer_loading` 機制，而這個機制是後來作為 `advanced-tool-use-2025-11-20` beta 引入的。

---

## 7. 哪些操作真的會破壞快取——實用情境指南

提示快取是一疊三層結構：工具在最底層，系統提示在中間，訊息在最上層。當某一層改變了，它上面的所有層都要重寫。所以工具層變動是最慘的——整疊都得重來。系統提示變動次之——工具層還在，但後面的都得重寫。訊息層變動最輕微——只是新內容要寫進去。

以下按「傷害程度」分類，把每種常見操作都列出來。

### 最燒的：整個對話重寫

這類操作改動了工具層（快取的最底層），所以 request 裡的每一個 token——工具、系統提示、所有訊息——都被當成新內容，以較高的寫入費率重新寫入。

**什麼時候會發生？**

- **對話途中切換模型。** 快取的金鑰包含模型名稱。從 Sonnet 切到 Opus，伺服器就把整個 request 當成全新的。

- **MCP server 重啟，而且工具描述有變。** 每個工具的 schema 是逐位元組序列化的。如果你的 MCP server 在工具描述裡包含了時間戳、資料筆數、或任何會變動的東西，schema 每次都不一樣。差一個 byte 就夠了。

- **切換 `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` 設定。** 這會把工具 schema 裡的非標準欄位（像 `defer_loading`、`eager_input_streaming`）剝掉。序列化的位元組一變，前綴就失效。

- **CLI 從「standard」模式切到「tool-search」模式（或反過來）。** 這會重組整個工具陣列——ToolSearch 被加入、延遲工具被移除或改變排列方式。

**要花多少？** 在 200k 上下文、1 小時 TTL 的情況下：伺服器把 ~200k token 以 $2.00/MTok 的費率寫入（$0.40），而不是以 $0.10/MTok 讀取（$0.02）。每次多花大約 **~$0.38**。在 500k 上下文下：每次 **~$0.95**。

### 中等程度的：系統提示和訊息重寫，工具層不動

這類操作改動了系統提示（中間層），所以工具層的快取還在，但系統提示 + 所有訊息都要重寫。

**什麼時候會發生？**

- **跨午夜工作。** 系統提示裡包含 `currentDate`。過了午夜 12 點，這個字串就變了，系統提示的動態區就不再匹配。跨日工作會吃一次重建。

- **對話途中編輯 CLAUDE.md。** CLAUDE.md 的內容是系統提示的一部分。每次存檔都會觸發重建。如果你的編輯器有自動儲存，這個成本會累積。

- **兩輪之間有 git 操作。** 系統提示的動態區包含 repo 的 git status 快照。在兩次 Claude 回覆之間跑了 `git commit`，status 字串就變了。

- **第一次出現非延遲的 MCP 工具。** 這會觸發系統提示的快取策略從 `"global"` scope 降級為 `"org"` scope。scope 一變，舊的快取條目就不匹配了，要寫新的。

**要花多少？** 比全面重建便宜一點，因為工具層還在。以 200k 上下文、工具佔約 15k token 來算：比完整重建省了 ~15k token 的寫入成本。實際大約 **每次 ~$0.35**。

### 最便宜的：只有新訊息要寫入

這是正常操作。每次你發訊息、Claude 回覆，新內容就寫入快取。滑動視窗的斷點往前移，斷點之前的內容都從快取讀取。

- **正常的對話輪次** — 每一輪增加新的訊息內容。只有新的部分是寫入，之前的都是讀取。這就是對話的基本成本。

- **工具輸出（Read、Bash 等）** — 輸出落入訊息層。大量輸出（例如讀一個 5000 行的檔案）意味著那一輪的寫入 token 較多，但不會讓之前的快取失效。

**要花多少？** 跟新內容大小成正比。一個典型的輪次——幾百 token 的使用者輸入 + 幾千 token 的 Claude 輸出——成本很低。

### 最重的：整個上下文從零開始

這些情況比較少見，但發生時是最貴的。

- **上下文壓縮（auto-compact）。** 對話超過上下文上限時，Claude Code 會把舊訊息摘要壓縮。壓縮後的內容取代原本的訊息，整個訊息層都變了。更糟的是：如果壓縮改動到了原本帶有快取斷點的訊息，可能觸發連鎖反應——系統提示的斷點也需要重建。

- **Session resume（關閉後重開）。** 整個 request 從持久化的狀態重新組裝。沒有暖快取可以命中——第一輪的所有內容都是寫入。

- **閒置超時（快取 TTL 過期）。** 如果你超過 5 分鐘（標準）或 1 小時（延長 TTL）沒有發訊息，伺服器會清掉你的快取條目。下一則訊息就得付完整的寫入成本。

**要花多少？** 跟完整重建一樣——整個上下文以較高費率寫入。200k 上下文、1 小時 TTL 下：**~$0.38**。但壓縮真正危險的地方在於，如果對話一直徘徊在上下文上限附近，壓縮可能反覆觸發，成本持續累加。

### 完全免費的：對快取零影響

以下操作是安全的，隨便用。

- **透過 ToolSearch 發現 MCP 工具。** 這就是本報告的核心發現。延遲工具被排除在伺服器的前綴計算之外。連續發現 10 個 MCP 工具——快取影響為零。

- **使用 Skill tool（/斜線指令）。** Skill 內容附加到訊息層的當前位置。它不會改動工具或系統提示。之前的快取條目完全不受影響。

- **讀檔案、跑指令、寫程式碼。** 所有工具輸出都進入訊息層，由滑動視窗正常處理。

- **連續呼叫多次 ToolSearch。** 每次都是加一個帶 `defer_loading` 的工具到 client 端的陣列裡，但伺服器在前綴計算時全部忽略。

### 快速查表

| 你在做什麼 | 快取影響 | 每次額外成本（200k 上下文，1h TTL） |
|-----------|---------|----------------------------------|
| 正常對話 | 無（基準線） | — |
| 用 ToolSearch 載入 MCP 工具 | 無 | $0 |
| 用 Skill（/斜線指令） | 無 | $0 |
| 讀檔案、跑 Bash | 無（只有新內容） | — |
| 跨午夜（日期翻日） | 系統提示 + 訊息重寫 | ~$0.35 |
| 編輯 CLAUDE.md | 系統提示 + 訊息重寫 | ~$0.35 |
| 兩輪之間有 git 操作 | 系統提示 + 訊息重寫 | ~$0.35 |
| 切換模型 | 全面重建 | ~$0.38 |
| MCP server 重啟（描述有變） | 全面重建 | ~$0.38 |
| 閒置超過 5 分鐘（或 1 小時） | 下一輪全面重建 | ~$0.38 |
| 關閉 session 後重開 | 全面重建 | ~$0.38 |
| 觸發 auto-compact | 全面重建 + 連鎖風險 | ~$0.38+ |

對 API 計費用戶來說，這些就是直接的費用。對 Claude Max 訂閱用戶來說，體現為 5 小時滾動額度消耗得更快——百分比影響取決於你的總預算，但各操作的相對比例是一樣的。

---

## 8. 研究方法

### 使用的工具

- **CLI v2.1.85**：透過 `npm install @anthropic-ai/claude-code@2.1.85` 安裝到 `/tmp/cc-research/`
- **grep/read**：在 12.9MB 的 minified cli.js 上做模式搜尋
- **GitHub issue 搜尋**：涵蓋 anthropics/claude-code 和 anthropics/claude-agent-sdk-typescript
- **Anthropic API 文件**（docs.anthropic.com）
- **實測**：在活躍的 Claude Code CLI session 中進行

### 逆向工程方法

CLI v2.1.85 的 cli.js 是一個 12.9MB 的 minified JavaScript 檔案。函式名稱被壓縮了（例如 `XU`, `Z57`, `vm8`, `vuK`, `I0`, `wU`, `kVY`），但字串常數——遙測事件名稱、錯誤訊息、內嵌文件——都以明文保留。我們用這些字串作為定位錨點來追蹤相關的程式路徑。

主要的錨點：
- `"cache_control"` → 斷點放置邏輯
- `"tengu_sysprompt_using_tool_based_cache"` → tool-based cache 策略
- `"skipGlobalCacheForSystemPrompt"` → 策略切換條件
- `"defer_loading"` → 延遲工具處理
- `"tool_reference"` → 發現掃描器
- `"Render order is: tools"` → 內嵌文件

### 驗證標準

本報告中的每一個論述都歸入以下三類之一：

- **已確認（原始碼）：** 在 cli.js v2.1.85 中直接驗證。附上 minified 函式名稱供重現。
- **已確認（外部來源）：** 透過 Anthropic 官方文件或可重現的 GitHub issue 驗證。
- **推論：** 從已確認的事實做邏輯推導。使用時明確標註。

---

## 9. 參考資料

### GitHub Issues

| Issue | 主題 | 相關性 |
|-------|------|--------|
| [anthropics/claude-code#30920](https://github.com/anthropics/claude-code/issues/30920) | defer_loading + cache_control 互斥錯誤 | 證明 API 拒絕兩者共存 |
| [anthropics/claude-code#30989](https://github.com/anthropics/claude-code/issues/30989) | v2.1.69 regression：所有 MCP 呼叫失敗 | 確認約束在執行期被強制執行 |
| [anthropics/claude-code#31002](https://github.com/anthropics/claude-code/issues/31002) | 內建工具被延遲到 ToolSearch 之後 | 記錄了 93% 的 token 減少 |
| [anthropics/claude-code#14963](https://github.com/anthropics/claude-code/issues/14963) | 動態變數排在靜態工具前面 | 提示排列順序造成的快取效率問題 |
| [anthropics/claude-code#29230](https://github.com/anthropics/claude-code/issues/29230) | 壓縮後的過期快取 | 上下文壓縮時的快取失效漏洞 |
| [anthropics/claude-code#27048](https://github.com/anthropics/claude-code/issues/27048) | Session resume 時的快取失效 | 工具輸出內容在 resume 後無法有效快取 |
| [anthropics/claude-code#12836](https://github.com/anthropics/claude-code/issues/12836) | Tool Search 的 token 節省 | 確認全域快取與 ToolSearch 相容 |
| [anthropics/claude-agent-sdk-typescript#124](https://github.com/anthropics/claude-agent-sdk-typescript/issues/124) | SDK defer_loading 支援請求 | 記錄了使用延遲載入可減少 85% token |
| [anthropics/claude-agent-sdk-typescript#89](https://github.com/anthropics/claude-agent-sdk-typescript/issues/89) | SDK 快取控制 | 快取效率從 49.7% 提升到 91-98% |
| [anthropics/claude-agent-sdk-typescript#188](https://github.com/anthropics/claude-agent-sdk-typescript/issues/188) | SDK 預設 TTL 改為 1 小時 | 未記載的 60% 快取寫入成本增加 |

### 官方文件

- Anthropic Prompt Caching Guide — 快取前綴計算規則
- Anthropic Tool Search Tool Documentation — 「延遲工具完全被排除在初始提示之外」
- Anthropic Advanced Tool Use Blog — Tool Search、defer_loading、programmatic tool calling

### 原始碼參考（CLI v2.1.85）

| 功能 | Minified 名稱 | 用途 |
|------|--------------|------|
| 快取控制工廠 | `XU()` | 產生 `{type: "ephemeral", ttl?, scope?}` |
| 系統提示策略 | `Z57()` | 三分支快取策略選擇 |
| 系統提示格式化 | `yVY()` | 在系統區塊上套用 cache_control |
| 工具 schema 建構器 | `vm8()` | 把工具轉成 API 格式，加上 defer_loading |
| 訊息斷點處理器 | `kVY()` | 訊息上的滑動視窗快取斷點 |
| 主查詢函式 | `vuK()` | 協調整個 API request |
| 延遲檢查 | `I0()` | 對所有 MCP 工具返回 true |
| 發現掃描器 | `wU()` | 掃描訊息歷史中的 tool_reference 區塊 |
| Tool search 模式檢查 | `Ir6()` | 判斷 tst/tst-auto/standard 模式 |
