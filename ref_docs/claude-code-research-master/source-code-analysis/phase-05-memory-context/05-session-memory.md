# Session Memory 系統

## 一、系統定位

Session Memory 是一個**當前 session 的即時快照筆記**系統，與 Auto Memory（跨 session 永久記憶）不同：

| 維度 | Session Memory | Auto Memory |
|---|---|---|
| 持久性 | 當前 session（可作為 compact 基礎） | 跨 session |
| 觸發 | context 達到 token 門檻 | 每輪 query 結束 |
| 內容 | 結構化 session 快照（標題/狀態/文件/工作流） | 四類型記憶（user/feedback/project/reference） |
| 主要用途 | 輔助 auto-compact，取代整段對話摘要 | 跨對話脈絡回憶 |
| 存放位置 | `~/.claude/session-memory/<session>.md` | `~/.claude/projects/<proj>/memory/` |

## 二、啟動條件

```typescript
export function initSessionMemory(): void {
  if (getIsRemoteMode()) return        // CCR 模式不啟動
  const autoCompactEnabled = isAutoCompactEnabled()
  if (!autoCompactEnabled) return      // 依賴 auto-compact
  registerPostSamplingHook(extractSessionMemory)
}
```

Session Memory 被設計為 auto-compact 的前置條件——它的存在讓 compact 有更好的摘要基礎（非從對話原文直接摘要，而是從已整理的 session 筆記摘要）。

## 三、觸發條件（shouldExtractMemory）

```typescript
export function shouldExtractMemory(messages: Message[]): boolean {
  const currentTokenCount = tokenCountWithEstimation(messages)

  // 1. 初始化閾值（預設 10,000 tokens）
  if (!isSessionMemoryInitialized()) {
    if (!hasMetInitializationThreshold(currentTokenCount)) return false
    markSessionMemoryInitialized()
  }

  // 2. 更新閾值（預設每增加 5,000 tokens）
  const hasMetTokenThreshold = hasMetUpdateThreshold(currentTokenCount)

  // 3. 工具呼叫閾值（預設 3 次工具呼叫）
  const toolCallsSinceLastUpdate = countToolCallsSince(messages, lastMemoryMessageUuid)
  const hasMetToolCallThreshold = toolCallsSinceLastUpdate >= getToolCallsBetweenUpdates()

  // 4. 自然對話暫停（最後一輪無工具呼叫）
  const hasToolCallsInLastTurn = hasToolCallsInLastAssistantTurn(messages)

  // 觸發條件（Token 閾值是必要條件）：
  // - 兩閾值都達到（token + tool calls）
  // - OR token 達到 + 對話自然暫停（確保在自然斷點提取）
  const shouldExtract =
    (hasMetTokenThreshold && hasMetToolCallThreshold) ||
    (hasMetTokenThreshold && !hasToolCallsInLastTurn)
}
```

**重要設計**：token 閾值是必要條件（即使工具呼叫閾值達到，沒有足夠 token 也不提取）；這防止對短互動的過度提取。

## 四、預設配置

```typescript
export const DEFAULT_SESSION_MEMORY_CONFIG: SessionMemoryConfig = {
  minimumMessageTokensToInit: 10000,    // 啟動門檻
  minimumTokensBetweenUpdate: 5000,     // 兩次更新間最少增長
  toolCallsBetweenUpdates: 3,           // 兩次更新間最少工具呼叫
}
```

這些值可透過 GrowthBook 動態配置（`tengu_sm_config`），允許 A/B 測試不同頻率。

## 五、Session Memory 文件格式（DEFAULT_SESSION_MEMORY_TEMPLATE）

```markdown
# Session Title
_A short and distinctive 5-10 word descriptive title for the session. Super info dense, no filler_

# Current State
_What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps._

# Task specification
_What did the user ask to build? Any design decisions or other explanatory context_

# Files and Functions
_What are the important files? In short, what do they contain and why are they relevant?_

# Workflow
_What bash commands are usually run and in what order? How to interpret their output if not obvious?_

# Errors & Corrections
_Errors encountered and how they were fixed. What did the user correct? What approaches failed..._

# Codebase and System Documentation
_What are the important system components? How do they work/fit together?_

# Learnings
_What has worked well? What has not? What to avoid? Do not duplicate items from other sections_

# Key results
_If the user asked a specific output such as an answer, table, or document, repeat the exact result here_

# Worklog
_Step by step, what was attempted, done? Very terse summary for each step_
```

用戶可在 `~/.claude/session-memory/config/template.md` 放置自訂模板。

## 六、更新 Prompt 機制（buildSessionMemoryUpdatePrompt）

```typescript
export async function buildSessionMemoryUpdatePrompt(
  currentNotes: string,
  notesPath: string,
): Promise<string>
```

核心 prompt 設計要點：
1. **明確排除 prompt 自身**：「這條訊息及指令 NOT 是實際用戶對話的一部分」
2. **區段結構保護**：只更新 `_italic descriptions_` 後的內容，headers 和 italic descriptions 不得修改
3. **並行 Edit**：「在單條訊息中並行發出所有 Edit 工具呼叫，然後停止」
4. **不留空位**：沒有新内容時不填充「No info yet」，直接跳過

### 區段大小管理

```typescript
const MAX_SECTION_LENGTH = 2000
const MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000
```

```typescript
function generateSectionReminders(sectionSizes, totalTokens): string {
  if (overBudget) {
    // CRITICAL: 文件超 12000 tokens，必須縮減
    // 優先保留 "Current State" 和 "Errors & Corrections"
  }
  if (oversizedSections.length > 0) {
    // 列出超過 2000 tokens 的區段，要求壓縮
  }
}
```

超限提醒被動態追加到 prompt 末尾。

### 自訂 Prompt 支援

可在 `~/.claude/session-memory/config/prompt.md` 放置自訂 prompt，使用 `{{variableName}}` 語法：
```
{{currentNotes}} — 當前筆記內容
{{notesPath}}    — 筆記文件路徑
```

## 七、工具限制（createMemoryFileCanUseTool）

```typescript
export function createMemoryFileCanUseTool(memoryPath: string): CanUseToolFn {
  return async (tool, input) => {
    if (tool.name === FILE_EDIT_TOOL_NAME && filePath === memoryPath) {
      return allow
    }
    return deny(`only ${FILE_EDIT_TOOL_NAME} on ${memoryPath} is allowed`)
  }
}
```

比 ExtractMemories 更嚴格：只允許 Edit 指定的一個文件。

## 八、Compact 整合（truncateSessionMemoryForCompact）

```typescript
export function truncateSessionMemoryForCompact(content: string): {
  truncatedContent: string
  wasTruncated: boolean
}
```

在 session memory 被注入到 compact 訊息之前，先截斷超過 `MAX_SECTION_LENGTH * 4 chars` 的區段。防止超大 session memory 耗盡壓縮後的 token 預算。

## 九、isSessionMemoryEmpty()

```typescript
export async function isSessionMemoryEmpty(content: string): Promise<boolean> {
  const template = await loadSessionMemoryTemplate()
  return content.trim() === template.trim()
}
```

用於 compact 時判斷：若 session memory 只是空模板（沒有任何提取內容），回退到傳統的對話直接摘要模式。

## 十、提取狀態管理（sessionMemoryUtils.ts）

所有狀態為模組層級變數（與 extractMemories 的閉包方式不同）：

```typescript
let sessionMemoryConfig: SessionMemoryConfig = { ...DEFAULT_SESSION_MEMORY_CONFIG }
let lastSummarizedMessageId: string | undefined
let extractionStartedAt: number | undefined      // 用於 waitForSessionMemoryExtraction()
let tokensAtLastExtraction = 0
let sessionMemoryInitialized = false
```

### waitForSessionMemoryExtraction()

```typescript
// 等待進行中的提取完成（最多 15s），超過 1 分鐘的提取視為過期
export async function waitForSessionMemoryExtraction(): Promise<void>
```

在 compact 前呼叫，確保最新的 session memory 已寫入再開始壓縮。

## 十一、手動提取（manuallyExtractSessionMemory）

```typescript
export async function manuallyExtractSessionMemory(
  messages: Message[],
  toolUseContext: ToolUseContext,
): Promise<ManualExtractionResult>
```

供 `/summary` 指令呼叫，繞過 token 閾值直接執行提取。使用不同的 `forkLabel: 'session_memory_manual'` 便於分析追蹤。
