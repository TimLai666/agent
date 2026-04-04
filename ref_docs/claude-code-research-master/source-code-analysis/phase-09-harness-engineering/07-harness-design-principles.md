# 07 — Harness Engineering 設計原則（可遷移知識庫）

## 概述

從 Claude Code 原始碼中提煉的可遷移 Harness Engineering 設計原則。這些原則是從真實生產系統中觀察到的模式，可直接應用於任何包裹 LLM 的生產基礎設施。

**Harness 公式**：`Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions`

---

## 原則一：Cache 穩定性即核心資產

**觀察**：Claude Code 花費大量工程精力在維護 prompt cache 穩定性。

### Sticky Latch 模式

```typescript
// 一旦觸發就不關，session 期間保持穩定
let fastModeHeaderLatched = getFastModeHeaderLatched() === true
if (!fastModeHeaderLatched && isFastMode) {
  fastModeHeaderLatched = true
  setFastModeHeaderLatched(true)  // 寫入 persistent state
}
// 之後即使 isFastMode 變為 false，header 依然發送
```

**原則**：對於影響 server-side cache key 的任何欄位（beta headers、feature flags、config），使用 latch 模式確保一旦啟用就不在 session 期間關閉。Cache miss 代價遠高於功能精確性。

### 確定性 ID 生成

```typescript
// 不用隨機 ID — 用確定性 hash
export function deriveShortMessageId(uuid: string): string {
  const hex = uuid.replace(/-/g, '').slice(0, 10)
  return parseInt(hex, 16).toString(36).slice(0, 6)
}
// 相同 UUID → 相同短 ID → 不會因 ID 改變破壞 cache
```

**原則**：任何會注入 context 的 ID 都應是確定性的（從穩定輸入衍生），而非每次隨機生成。

---

## 原則二：多層防護的工具執行管道

**觀察**：工具執行有 10 個步驟，每一層都有明確職責且失敗即停。

```
Input 到達
    │
    ▼
[Layer 1] Schema Validation (Zod)     — 型別安全
    │
    ▼
[Layer 2] Custom validateInput()      — 業務邏輯驗證
    │
    ▼
[Layer 3] Input Sanitization          — 安全清理
    │
    ▼
[Layer 4] PreToolUse Hooks            — 外部可介入點
    │
    ▼
[Layer 5] Permission Resolution       — 授權決策
    │
    ▼
[Layer 6] Actual Execution            — 最後才執行
    │
    ▼
[Layer 7] PostToolUse Hooks           — 執行後可觀察
```

**原則**：工具執行應是一個有序的管道，而非單一函式。每層的職責：「能否拒絕？應該拒絕嗎？修改 input？」與執行邏輯完全分離。

---

## 原則三：並行安全性由工具聲明，而非呼叫者判斷

```typescript
// 工具定義時聲明自己是否可並行
interface Tool {
  isConcurrencySafe: (input: ParsedInput) => boolean
}

// FileReadTool: return true（讀取是安全的）
// BashTool: 依指令分析決定
// FileEditTool: return false（寫入必須串行）
```

**原則**：工具自己最了解自己的並行安全性。呼叫端只需根據聲明決定調度策略，不應嘗試推斷。這保持了 Single Responsibility Principle 同時解決了 fan-out 效能問題。

---

## 原則四：Async Generator 是 Agent Loop 的自然表達

**觀察**：整個 agent loop 從 `queryModel` 到 `runTools` 都是 async generator。

```typescript
// 好：每個步驟的結果都是 yield，呼叫端按需消費
async function* queryModel(...): AsyncGenerator<StreamEvent | AssistantMessage> {
  // streaming events
  yield streamEvent
  // ... more events ...
  yield assistantMessage
}

// 好：工具執行的 progress 和結果共享同一個流
async function* runToolUse(...): AsyncGenerator<MessageUpdateLazy> {
  yield progressMessage
  yield toolResultMessage
}
```

**原則**：LLM 呼叫本質上是流式的，工具執行本質上有中間 progress。用 async generator 統一表達這兩種特性，避免 callback hell 和複雜的事件系統。

---

## 原則五：訊息不是字串，是帶語意的型別物件

**觀察**：Claude Code 有豐富的 Message 型別系統，每個 message 都帶有語意標記。

```typescript
interface UserMessage {
  type: 'user'
  isMeta?: true               // 不向使用者顯示的 meta 訊息
  isVirtual?: true            // 僅顯示，不送 API
  isCompactSummary?: true     // 壓縮摘要
  sourceToolAssistantUUID?    // 追蹤哪個 assistant message 觸發了此工具結果
  toolUseResult?: unknown     // 工具的結構化輸出（不送 API）
  origin?: MessageOrigin      // human/tool/system
}
```

**原則**：Message 應該是富型別物件，而非只是字串。metadata 讓系統可以：過濾什麼送 API、過濾什麼顯示給使用者、追蹤 message 間的因果關係。

---

## 原則六：Context Window 管理需要多層壓縮策略

**觀察**：Claude Code 有三層 context 壓縮：

```
Layer 1: normalizeMessagesForAPI() — 即時清理
  ├─ 移除 virtual messages
  ├─ 合併相鄰 user messages
  ├─ 修復 tool_result pairing
  └─ 移除造成錯誤的媒體

Layer 2: stripExcessMediaItems() — 媒體限制
  └─ 保留最新的，移除最舊的（最多 100 個）

Layer 3: compact() — 對話壓縮
  └─ 用 summary 替換早期 messages
```

**原則**：Context 管理應在多個時機點發生：每次 API 呼叫前的即時修復、達到硬性限制時的媒體刪除、以及用戶/自動觸發的完整壓縮。這三層各有不同的觸發條件和侵入性。

---

## 原則七：工具搜尋作為動態知識載入機制

**觀察**：當工具數量超過閾值，`ToolSearchTool` 允許模型按需發現工具。

```typescript
// 工具分兩類：
// - 非延遲工具：總是在 context（schema 完整送出）
// - 延遲工具：只送 name + 一行描述，需要先呼叫 ToolSearch 才能使用

const filteredTools = tools.filter(tool => {
  if (!deferredToolNames.has(tool.name)) return true  // 非延遲：始終包含
  if (toolMatchesName(tool, TOOL_SEARCH_TOOL_NAME)) return true  // ToolSearch 本身
  return discoveredToolNames.has(tool.name)  // 延遲：只有已發現才送 schema
})
```

**原則**：當工具集合龐大時，不要一次全部載入。讓模型透過搜尋按需發現，模擬人類工程師查文件的行為。這大幅降低每次請求的 token 使用量。

---

## 原則八：Hooks 是 Harness 的對外開口

**觀察**：Claude Code 在工具執行的每個關鍵節點都有 hook 點，允許外部程式：
- 觀察將要執行的工具（PreToolUse）
- 修改工具 input
- 做出 allow/deny 決定
- 觀察執行結果（PostToolUse）
- 在會話開始/結束時執行清理

```typescript
// hook 結果型別展示了 harness 對外開口的完整語意
type PreToolUseHookResult =
  | { type: 'message' }               // 發送訊息
  | { type: 'hookPermissionResult' }   // 做出決策
  | { type: 'hookUpdatedInput' }       // 修改 input
  | { type: 'preventContinuation' }    // 阻止繼續
  | { type: 'stopReason' }             // 提供停止原因
  | { type: 'additionalContext' }      // 附加 context
  | { type: 'stop' }                   // 完全停止
```

**原則**：Harness 的 hook 系統應定義清晰的 result 型別，而非讓 hooks 直接修改 shared state。每種 result 有明確語意，呼叫端根據型別分支處理。

---

## 原則九：Bootstrap State 是 Session 的生命期單例

**觀察**：`bootstrap/state.ts` 明確標注：`// DO NOT ADD MORE STATE HERE - BE JUDICIOUS WITH GLOBAL STATE`

```typescript
// 什麼應該在 STATE：
// ✓ session-wide 唯一識別（sessionId）
// ✓ 累計計數器（totalCostUSD, totalAPIDuration）
// ✓ 遙測設施（meter, counters）
// ✓ Session-stable 快取（beta header latch, allowlist）
// ✓ 目錄狀態（originalCwd, cwd）

// 什麼不應該在 STATE：
// ✗ 每次請求的暫時資料
// ✗ 可以從其他地方衍生的資料
// ✗ 業務邏輯狀態（放在 AppState）
```

**原則**：全域 state 應只存放真正 session-wide 的東西。一個好的測試：「這個值的生命週期是整個 CLI 進程嗎？還是只是一個對話轉？」

---

## 原則十：Permission 決策來源追蹤

**觀察**：每個 allow/deny 決策都記錄其來源。

```typescript
type PermissionDecisionReason =
  | { type: 'permissionPromptTool'; decisionClassification?: string }
  | { type: 'rule'; rule: { source: 'session' | 'localSettings' | 'userSettings' | ... } }
  | { type: 'hook' }
  | { type: 'mode' }
  | { type: 'classifier' }
  | { type: 'safetyCheck' }
  | { type: 'other' }

// 映射到 OTel 詞彙
function decisionReasonToOTelSource(reason, behavior): string {
  // 'session' → 'user_temporary'
  // 'localSettings' → 'user_permanent'
  // 'hook' → 'hook'
  // 其他 → 'config'
}
```

**原則**：授權決策必須記錄 why，不只是 allow/deny。這讓事後審計、除錯、和使用者教育（「為什麼這個被拒絕？」）都成為可能。

---

## 原則十一：PII 安全由型別系統強制

```typescript
// 任何想送往 analytics 的資料，必須用此型別標記
type AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS

// 使用時強制 cast，觸發 code review 關注
logEvent('tengu_tool_use_error', {
  error: 'InputValidationError' as AnalyticsMetadata_...,
  toolName: sanitizeToolNameForAnalytics(tool.name),  // 清理函式
})
```

**原則**：PII 安全不應依賴開發者記憶力。用型別系統讓每次「把使用者資料送往第三方」都成為明確的 code review 節點。

---

## 原則十二：錯誤訊息是 Context 的一部分

**觀察**：工具錯誤不只是「告訴使用者出錯了」，而是精心設計的 feedback 給模型。

```typescript
// 錯誤訊息告訴模型應該怎麼做
export const CANCEL_MESSAGE =
  "The user doesn't want to take this action right now. STOP what you are doing and wait for the user to tell you how to proceed."

export const DENY_WORKAROUND_GUIDANCE =
  `You *may* attempt to accomplish this action using other tools... ` +
  `But you *should not* attempt to work around this denial in malicious ways...`

// deferred tool schema hint
return (
  `\n\nThis tool's schema was not sent to the API — it was not in the discovered-tool set. ` +
  `Load the tool first: call ${TOOL_SEARCH_TOOL_NAME} with query "select:${tool.name}", then retry this call.`
)
```

**原則**：工具錯誤訊息是「給模型的指令」，而非只是「給人類的診斷資訊」。設計時要考慮模型如何理解和響應這些訊息。

---

## 設計原則總覽

```
┌────────────────────────────────────────────────────────────────┐
│              HARNESS ENGINEERING 12 PRINCIPLES                 │
│                                                                │
│  Context Engineering                                           │
│  ├─ P1: Cache 穩定性即核心資產（Sticky Latch）                   │
│  ├─ P6: 多層 context 壓縮策略                                   │
│  └─ P7: 動態工具知識載入（ToolSearch）                           │
│                                                                │
│  Tool Execution                                                │
│  ├─ P2: 多層防護的執行管道（fail-fast）                           │
│  ├─ P3: 並行安全性由工具自行聲明                                  │
│  └─ P4: Async Generator 是自然表達                              │
│                                                                │
│  State Management                                              │
│  ├─ P5: Messages 是帶語意的型別物件                               │
│  └─ P9: Bootstrap State 是 Session 生命期單例                   │
│                                                                │
│  Extensibility                                                 │
│  └─ P8: Hooks 是 Harness 的對外開口                             │
│                                                                │
│  Observability & Safety                                        │
│  ├─ P10: Permission 決策來源追蹤                                 │
│  ├─ P11: PII 安全由型別系統強制                                  │
│  └─ P12: 錯誤訊息是 Context 的一部分                             │
└────────────────────────────────────────────────────────────────┘
```
