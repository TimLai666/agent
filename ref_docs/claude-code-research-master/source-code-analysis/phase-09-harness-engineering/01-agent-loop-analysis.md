# 01 — Agent Loop 完整流程逆向分析

## 概述

Claude Code 的 Agent Loop 是整個系統的核心驅動機制。它以 `query.js`（由 REPL.tsx 調用）為入口，執行「模型呼叫 → 工具執行 → feedback 回注」的完整循環，直到 `stop_reason === 'end_turn'` 或使用者中斷。

---

## 1. 整體流程架構

```mermaid
graph TD
    A[使用者輸入] --> B[REPL.tsx handleSubmit]
    B --> C[query.js — Agent Loop 入口]
    C --> D[queryModel via claude.ts]
    D --> E{stop_reason?}
    E -->|tool_use| F[runTools — toolOrchestration.ts]
    E -->|end_turn| G[回傳 AssistantMessage]
    E -->|max_tokens| H[token budget handling]
    F --> I[runToolUse — toolExecution.ts]
    I --> J{permission check}
    J -->|allow| K[tool.call()]
    J -->|deny| L[createUserMessage error]
    K --> M[tool result → UserMessage]
    M --> N[append to messages array]
    N --> C
    G --> O[更新 REPL state]
    H --> O
```

---

## 2. 關鍵入口：REPL.tsx → query()

`REPL.tsx` 在使用者送出 prompt 後觸發 `query()` 函式：

```typescript
// src/screens/REPL.tsx (line 146)
import { query } from '../query.js'
```

REPL 透過 React hook `useQueueProcessor` 處理訊息佇列，確保每次只有一個 query 在執行中。

---

## 3. Claude API 呼叫層 (claude.ts)

核心 `queryModel` 函式是 async generator，負責與 Anthropic API 互動：

```typescript
// src/services/api/claude.ts (line 1017)
async function* queryModel(
  messages: Message[],
  systemPrompt: SystemPrompt,
  thinkingConfig: ThinkingConfig,
  tools: Tools,
  signal: AbortSignal,
  options: Options,
): AsyncGenerator<StreamEvent | AssistantMessage | SystemAPIErrorMessage, void>
```

**關鍵步驟：**
1. 先執行 off-switch 檢查（GrowthBook flag `tengu-off-switch`）
2. 計算 beta headers（thinking、fast mode、AFK mode 等的 sticky latch）
3. `normalizeMessagesForAPI()` — 清理 messages 送 API
4. `ensureToolResultPairing()` — 修復孤兒 tool_use/result
5. `stripExcessMediaItems()` — 最多 100 個媒體項
6. 建立 system prompt blocks（含 cache_control）
7. 呼叫 `anthropic.beta.messages.stream()`
8. stream 中的事件以 yield 送出，包含 `AssistantMessage` 和 `StreamEvent`

---

## 4. 工具執行循環 (toolOrchestration.ts → toolExecution.ts)

當 API 回應包含 `tool_use` blocks：

```typescript
// src/services/tools/toolOrchestration.ts (line 19)
export async function* runTools(
  toolUseMessages: ToolUseBlock[],
  assistantMessages: AssistantMessage[],
  canUseTool: CanUseToolFn,
  toolUseContext: ToolUseContext,
): AsyncGenerator<MessageUpdate, void>
```

**並行/串行策略：**
```typescript
// 分批策略：read-only tool 可並行，write tool 必須串行
for (const { isConcurrencySafe, blocks } of partitionToolCalls(...)) {
  if (isConcurrencySafe) {
    yield* runToolsConcurrently(...)  // 並行，最多 10 個
  } else {
    yield* runToolsSerially(...)      // 串行，一個接一個
  }
}
```

最大並行數由環境變數控制：
```typescript
function getMaxToolUseConcurrency(): number {
  return parseInt(process.env.CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY || '', 10) || 10
}
```

---

## 5. 單一工具執行流程

`checkPermissionsAndCallTool()` 是工具執行的核心邏輯：

```
1. Zod schema 驗證 input
2. validateInput() — 工具自訂驗證
3. startSpeculativeClassifierCheck() — Bash tool 預先啟動分類器
4. runPreToolUseHooks() — 執行 PreToolUse hooks
5. resolveHookPermissionDecision() — 決定 allow/deny
6. 若 deny → createUserMessage(is_error: true)
7. 若 allow → tool.call(parsedInput, toolUseContext)
8. runPostToolUseHooks() — 執行 PostToolUse hooks
9. 回傳 MessageUpdateLazy[]
```

---

## 6. Feedback Loop：tool result 回注

工具執行完畢後，結果被包裝成 `UserMessage`（role: 'user'，type: 'tool_result'），追加到 messages array，然後再次呼叫 `queryModel`：

```typescript
// 工具結果格式
{
  type: 'user',
  message: {
    role: 'user',
    content: [{
      type: 'tool_result',
      tool_use_id: toolUse.id,
      content: '<tool output>',
      is_error: boolean
    }]
  },
  sourceToolAssistantUUID: assistantMessage.uuid,
  toolUseResult: ...
}
```

---

## 7. 中斷機制

所有非同步工具執行都綁定 `AbortController.signal`。使用者按 Escape 時：
1. `abortController.abort()` 被呼叫
2. 正在執行的工具收到 abort signal
3. 未開始的工具呼叫立即回傳 `CANCEL_MESSAGE` 而非執行

```typescript
// src/services/tools/toolExecution.ts
if (toolUseContext.abortController.signal.aborted) {
  yield { message: createUserMessage({
    content: [createToolResultStopMessage(toolUse.id)],
    toolUseResult: CANCEL_MESSAGE,
  })}
  return
}
```

---

## 8. 完整 Agent Loop ASCII 圖

```
┌─────────────────────────────────────────────────────────────┐
│                      AGENT LOOP                             │
│                                                             │
│  User Input                                                 │
│      │                                                      │
│      ▼                                                      │
│  ┌─────────────────┐                                        │
│  │  normalizeMsg   │ ← strip virtual, repair pairing        │
│  └────────┬────────┘                                        │
│           │                                                 │
│      ▼                                                      │
│  ┌─────────────────────────────┐                            │
│  │    Claude API (streaming)   │                            │
│  │  model + system + tools     │                            │
│  └────────┬────────────────────┘                            │
│           │                                                 │
│      ┌────┴─────┐                                           │
│      │          │                                           │
│  end_turn   tool_use                                        │
│      │          │                                           │
│      │    ┌─────▼──────────────────────────────────┐       │
│      │    │  partition: read-only? write?           │       │
│      │    │  ├─ concurrent (max 10)                 │       │
│      │    │  └─ serial                              │       │
│      │    └─────────────┬──────────────────────────┘       │
│      │                  │                                   │
│      │    ┌─────────────▼──────────────────────────┐       │
│      │    │  per tool:                              │       │
│      │    │  1. Zod validate                        │       │
│      │    │  2. PreToolUse hooks                    │       │
│      │    │  3. permission check (allow/deny/ask)   │       │
│      │    │  4. tool.call()                         │       │
│      │    │  5. PostToolUse hooks                   │       │
│      │    └─────────────┬──────────────────────────┘       │
│      │                  │                                   │
│      │    tool_result UserMessage (appended)                │
│      │                  │                                   │
│      │    ┌─────────────▼───┐                               │
│      │    │  loop back to   │──────────────────────────┐   │
│      │    │  Claude API     │                          │   │
│      │    └─────────────────┘                          │   │
│      │                                                  │   │
│      └──────────► Response to user                      │   │
│                                                         │   │
│  AbortController ─────────────────────────────────────►│   │
│  (user Esc)                                             │   │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 關鍵設計觀察

| 特性 | 設計決策 | 位置 |
|------|----------|------|
| Streaming | 所有 API 呼叫都是 streaming，非 streaming 只作 fallback | claude.ts |
| Generator 模式 | 整個 loop 用 async generator 串接，避免 callback hell | 整體架構 |
| 工具並行安全 | `isConcurrencySafe` 由各工具自行聲明 | toolOrchestration.ts |
| 錯誤回注 | 工具錯誤以 `is_error: true` 的 tool_result 送回模型 | toolExecution.ts |
| 取消傳播 | AbortController signal 傳遞至每個工具調用 | toolExecution.ts |
