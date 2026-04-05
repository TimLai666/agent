# 02 — Context Engineering 策略分析

## 概述

Context Engineering 決定「什麼資訊、以什麼順序、什麼形式進入 context window」。Claude Code 在這方面有極為精密的策略，包含 system prompt 組裝、messages 正規化、prompt cache 管理，以及 messages.ts 的多層處理管道。

---

## 1. System Prompt 組裝策略

System prompt 並非單一字串，而是有序的 block array，各 block 有不同 cache 標記：

```typescript
// src/services/api/claude.ts (line 1358)
systemPrompt = asSystemPrompt([
  getAttributionHeader(fingerprint),       // 1. 指紋/歸因標頭
  getCLISyspromptPrefix({...}),            // 2. CLI 前綴
  ...systemPrompt,                          // 3. 主要系統提示
  ...(advisorModel ? [ADVISOR_TOOL_INSTRUCTIONS] : []),  // 4. Advisor 指令
  ...(injectChromeHere ? [CHROME_TOOL_SEARCH_INSTRUCTIONS] : []),  // 5. Chrome 指令
].filter(Boolean))
```

**System Prompt 分層結構：**
```
┌─────────────────────────────────────────┐
│  Attribution Header (fingerprint)        │  ← 每次請求都變
├─────────────────────────────────────────┤
│  CLI Sysprompt Prefix                    │  ← session-stable, cache
├─────────────────────────────────────────┤
│  Main System Prompt                      │  ← project/user context
│  ├─ Base system prompt                   │
│  ├─ CLAUDE.md contents                   │
│  ├─ Memory files                         │
│  └─ Tool instructions                    │
├─────────────────────────────────────────┤
│  Advisor Tool Instructions (if enabled)  │  ← conditional
├─────────────────────────────────────────┤
│  Chrome Tool Search Instructions         │  ← conditional
└─────────────────────────────────────────┘
```

---

## 2. Messages 正規化管道 (normalizeMessagesForAPI)

`normalizeMessagesForAPI` 是 messages 送入 API 前的最後處理關卡，共有多個步驟：

```typescript
// src/utils/messages.ts (line 1989)
export function normalizeMessagesForAPI(
  messages: Message[],
  tools: Tools = [],
): (UserMessage | AssistantMessage)[]
```

**處理管道（按順序）：**

```
原始 messages
     │
     ▼
reorderAttachmentsForAPI()         → attachment 重排到正確位置
     │
     ▼
filter isVirtual                    → 移除僅顯示用的虛擬 message
     │
     ▼
buildStripTargets()                 → 掃描 API 錯誤，標記要移除的媒體
     │
     ▼
stripTargetedBlockTypes()           → 移除造成錯誤的 image/document
     │
     ▼
stripSyntheticApiErrors()           → 移除合成錯誤訊息（不送 API）
     │
     ▼
mergeUserMessages()                 → 合併相鄰 user messages
     │
     ▼
sanitizeThinkingBlocks()            → 處理 thinking block
     │
     ▼
normalizeToolInputForAPI()          → 修正 tool input 格式
     │
     ▼
appendMessageTagToUserMessage()     → 加入 [id:xxx] 標籤（snip 用）
     │
     ▼
relocateToolReferenceSiblings()     → 移動 tool_reference 旁的 text
     │
     ▼
smooshSystemReminderSiblings()      → 合併 <system-reminder> 到 tool_result
     │
     ▼
sanitizeErrorToolResultContent()    → 清理 is_error tool_result 的非文字內容
     │
     ▼
送往 API
```

---

## 3. Prompt Cache 設計

Claude Code 有極為複雜的 prompt cache 策略，核心目標是**最大化 cache hit rate**。

### 3.1 Cache TTL 選擇

```typescript
// src/services/api/claude.ts (line 358)
export function getCacheControl({ scope, querySource } = {}): {
  type: 'ephemeral'
  ttl?: '1h'
  scope?: CacheScope
} {
  return {
    type: 'ephemeral',
    ...(should1hCacheTTL(querySource) && { ttl: '1h' }),
    ...(scope === 'global' && { scope }),
  }
}
```

1h TTL 的條件：
- 使用者是 Anthropic 員工 OR Claude.ai 訂閱者（非 overage 狀態）
- query source 在 GrowthBook allowlist 中（支援 prefix wildcard）
- 這些條件在 bootstrap state 中 **latch 住**，session 期間不變化

### 3.2 Beta Header Sticky Latch 機制

為避免 mid-session header 變化破壞 server-side cache key，Claude Code 使用「sticky latch」模式：

```typescript
// 一旦開啟就不關，session 內保持穩定
let afkHeaderLatched = getAfkModeHeaderLatched() === true
if (!afkHeaderLatched && isAgenticQuery && autoModeActive) {
  afkHeaderLatched = true
  setAfkModeHeaderLatched(true)  // 寫入 bootstrap STATE
}
```

**四個 sticky latch：**
| Latch | 觸發條件 | 作用 |
|-------|----------|------|
| `afkModeHeaderLatched` | auto mode 首次啟動 | AFK_MODE_BETA_HEADER 保持發送 |
| `fastModeHeaderLatched` | fast mode 首次啟動 | FAST_MODE_BETA_HEADER 保持發送 |
| `cacheEditingHeaderLatched` | cached microcompact 首次啟用 | CACHE_EDITING_BETA_HEADER 保持發送 |
| `thinkingClearLatched` | 距上次 API 超過 1h | 清除 prior thinking，避免空占 cache |

### 3.3 Cache Breakpoints 策略

訊息的 `cache_control` 標記位置決定 server-side cache 的切割點：
- **System prompt**：加在最後一個 block
- **User messages**：加在最後一個 content block（非 thinking）
- **Assistant messages**：加在最後一個非 thinking block

---

## 4. 什麼進 Context Window — 完整清單

```
System Prompt:
├─ Attribution header (fingerprint from first user message)
├─ CLI prefix (version, entrypoint hints)
├─ Base capability prompts
├─ Tool usage instructions
├─ CLAUDE.md content (project + user + memory files)
├─ Coordinator system prompt (if coordinator mode)
├─ Dynamic tool context (MCP instructions, deferred tools list)
└─ Feature-specific additions (Advisor, Chrome, etc.)

Messages (per turn):
├─ Deferred tools list (<available-deferred-tools> prepend)
├─ User inputs (with [id:xxx] tags)
├─ Tool use blocks (from assistant)
├─ Tool result blocks (from tool execution)
├─ Thinking blocks (extended thinking)
├─ Hook attachments (as system-reminder sibling text)
└─ Progress messages (NOT sent to API — display only)

Per-Request:
├─ Tool schemas (full JSON schema for each tool)
├─ Metadata (user_id, device_id, session_id, account_uuid)
├─ Output config (effort, task_budget, output_format)
└─ Beta headers
```

---

## 5. Context 壓縮策略

當 context 快滿時（或使用者執行 `/compact`），系統觸發壓縮：

```typescript
// 觸發條件（在 query.ts/REPL.tsx 中）
// 1. Auto compact: token count 超過閾值
// 2. Manual: 使用者執行 /compact
// 3. Subagent: token budget 耗盡
```

壓縮後的 summary 以特殊 `UserMessage` 存回 messages：
```typescript
createUserMessage({
  content: summaryContent,
  isCompactSummary: true,
  summarizeMetadata: {
    messagesSummarized: N,
    userContext: ...,
    direction: 'partial' | 'full',
  }
})
```

**Compact Boundary Marker** 讓 REPL 知道哪些 messages 在壓縮後：
```typescript
// src/utils/messages.ts
export function isCompactBoundaryMessage(msg: Message): boolean
export function getMessagesAfterCompactBoundary(messages: Message[]): Message[]
```

---

## 6. Tool Search（延遲載入工具）

當工具數量超過閾值時，啟動動態工具載入：

```typescript
// 只有「已被發現」的工具才送完整 schema
filteredTools = tools.filter(tool => {
  if (!deferredToolNames.has(tool.name)) return true   // 非延遲工具總是包含
  if (toolMatchesName(tool, TOOL_SEARCH_TOOL_NAME)) return true  // ToolSearch 本身
  return discoveredToolNames.has(tool.name)  // 僅已發現的延遲工具
})
```

**好處**：工具數量多時不會全部塞入 context window，而是按需發現。

---

## 7. 訊息 ID 標籤系統

每個送往 API 的 user message 都附加短 ID：

```typescript
// src/utils/messages.ts (line 1620)
function appendMessageTagToUserMessage(message: UserMessage): UserMessage {
  const tag = `\n[id:${deriveShortMessageId(message.uuid)}]`
  // 只加在最後一個 text block
}

// ID 從 UUID 確定性衍生（避免隨機改變 cache key）
export function deriveShortMessageId(uuid: string): string {
  const hex = uuid.replace(/-/g, '').slice(0, 10)
  return parseInt(hex, 16).toString(36).slice(0, 6)
}
```

這讓模型可以透過 snip tool 精確引用特定訊息。

---

## 8. Context Engineering 設計原則摘要

| 原則 | 實作 |
|------|------|
| Cache 穩定性優先 | sticky latch、確定性 ID、session-stable 設定 |
| 漸進式清理 | 多層 normalize pipeline，各層職責單一 |
| 資訊分層 | system prompt 按 stable/dynamic 分層 cache |
| 防腐 guard | ensureToolResultPairing、stripExcessMedia |
| 延遲載入 | deferred tool schemas，按需解鎖 |
