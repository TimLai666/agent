# 自動記憶提取機制（ExtractMemories）

## 一、系統定位

ExtractMemories 是一個背景子系統，在每次 query loop 完整結束後（模型產生無工具呼叫的最終回應時），自動從對話歷史中提取值得保留的記憶。

**關鍵設計**：使用 forked agent 模式（`runForkedAgent`），完美複製主對話的 system prompt 和 prompt cache，讓記憶提取共享昂貴的 cache prefix。

## 二、初始化架構（閉包作用域狀態）

```typescript
export function initExtractMemories(): void {
  // 閉包作用域狀態（而非模組層級），確保測試隔離
  const inFlightExtractions = new Set<Promise<void>>()
  let lastMemoryMessageUuid: string | undefined  // 游標：上次處理到哪裡
  let hasLoggedGateFailure = false
  let inProgress = false
  let turnsSinceLastExtraction = 0
  let pendingContext: { context, appendSystemMessage } | undefined
  // ...
}
```

與 `confidenceRating.ts` 相同模式：每次 `initExtractMemories()` 呼叫建立新的閉包，tests 在 `beforeEach` 呼叫以取得乾淨狀態。

## 三、游標機制（cursor-based incremental processing）

```typescript
let lastMemoryMessageUuid: string | undefined
```

每次提取後，`lastMemoryMessageUuid` 更新為最後一條訊息的 UUID。下次提取只處理這個 UUID 之後的新訊息（`countModelVisibleMessagesSince()`）。

**故障容忍**：若游標 UUID 找不到（被 context compaction 移除），自動回退為計算全部訊息數量，防止永久停止提取。

## 四、互斥機制（主 agent 與 背景提取 agent）

```typescript
function hasMemoryWritesSince(messages, sinceUuid): boolean {
  // 掃描 assistant messages 的 tool_use blocks
  // 若任何 Write/Edit 工具呼叫指向 auto-memory 路徑 → 回傳 true
}
```

```typescript
if (hasMemoryWritesSince(messages, lastMemoryMessageUuid)) {
  // 主 agent 已自己寫記憶 → 跳過背景提取，只推進游標
  logEvent('tengu_extract_memories_skipped_direct_write', ...)
  return
}
```

**設計原理**：主 agent 的 prompt 本來就包含完整記憶保存指令。當主 agent 主動寫記憶，背景 agent 是多餘的；當主 agent 沒寫，背景 agent 補上。兩者互相排斥，每 turn 只發生一次記憶寫入。

## 五、重疊防護（overlap guard）

```typescript
if (inProgress) {
  // 正在進行中 → 暫存最新 context，留待 trailing run
  pendingContext = { context, appendSystemMessage }
  return
}
```

```typescript
// runExtraction 的 finally block
const trailing = pendingContext
pendingContext = undefined
if (trailing) {
  await runExtraction({
    context: trailing.context,
    appendSystemMessage: trailing.appendSystemMessage,
    isTrailingRun: true,
  })
}
```

trailing run 只追蹤「兩次呼叫間新增的訊息」（游標機制保證），不重複處理。

## 六、節流機制

```typescript
// tengu_bramble_lintel flag，預設 1（每 turn 都執行）
if (!isTrailingRun) {
  turnsSinceLastExtraction++
  if (turnsSinceLastExtraction < (getFeatureValue_CACHED_MAY_BE_STALE('tengu_bramble_lintel', null) ?? 1)) {
    return
  }
}
turnsSinceLastExtraction = 0
```

Trailing run 跳過節流（已承諾的工作不應被節流）。

## 七、工具權限控制（createAutoMemCanUseTool）

```typescript
export function createAutoMemCanUseTool(memoryDir: string): CanUseToolFn {
  return async (tool, input) => {
    // REPL tool → 允許（REPL 模式隱藏基本工具，操作透過 REPL 包裝）
    if (tool.name === REPL_TOOL_NAME) return allow

    // Read/Grep/Glob → 允許（天然唯讀）
    if ([FILE_READ_TOOL_NAME, GREP_TOOL_NAME, GLOB_TOOL_NAME].includes(tool.name)) return allow

    // Bash → 只允許唯讀命令（ls, find, grep, cat, stat, wc, head, tail）
    if (tool.name === BASH_TOOL_NAME) {
      if (tool.isReadOnly(parsed.data)) return allow
      return deny('Only read-only shell commands...')
    }

    // Edit/Write → 只允許指向 auto-memory 目錄的路徑
    if ((tool.name === FILE_EDIT_TOOL_NAME || tool.name === FILE_WRITE_TOOL_NAME) && isAutoMemPath(filePath)) {
      return allow
    }

    return deny(...)
  }
}
```

此函數同時被 `autoDream` 使用。

## 八、提取 prompt 結構

### buildExtractAutoOnlyPrompt（單目錄模式）

```
opener(newMessageCount, existingMemories)
├── 「你現在是記憶提取子代理，分析最近 ~N 條訊息」
├── 可用工具說明（讀/grep/唯讀 bash/寫限 memory 目錄）
├── 效率提示：第1輪並行所有 Read，第2輪並行所有 Write/Edit
├── 只處理最近 N 條訊息，不驗證或調查
└── 若有現有記憶 manifest → 「先查此清單，更新勿重複建立」
+ 四類記憶類型說明（TYPES_SECTION_INDIVIDUAL）
+ What NOT to save
+ How to save memories（兩步驟 or skipIndex 單步）
```

### buildExtractCombinedPrompt（team + auto 雙目錄）

結構相同，但使用 `TYPES_SECTION_COMBINED`（含 `<scope>` 標籤指引 private/team 選擇）。

## 九、記憶保存流程（2-turn 效率設計）

Prompt 明確要求最高效的操作策略：
```
turn 1 — 並行發出所有需更新文件的 Read 呼叫
turn 2 — 並行發出所有 Write/Edit 呼叫
```

Edit 工具要求先 Read 同一文件，因此不能跳過讀取步驟。Prompt 強調「不要交錯多個輪次的讀寫」——這是 2-turn 完成的關鍵。

## 十、執行限制與 telemetry

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: userPrompt })],
  cacheSafeParams,
  canUseTool,
  querySource: 'extract_memories',
  forkLabel: 'extract_memories',
  skipTranscript: true,    // 不記錄到 transcript（避免 race condition）
  maxTurns: 5,             // 硬上限，防止驗證兔子洞
})
```

完成後記錄 telemetry：
- `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`
- `message_count`, `turn_count`, `files_written`, `memories_saved`, `team_memories_saved`
- `duration_ms`

## 十一、記憶保存通知

```typescript
const memoryPaths = writtenPaths.filter(p => basename(p) !== ENTRYPOINT_NAME)
// MEMORY.md 的更新是機械性操作（只加指標）
// 真正的「記憶」是主題文件，只通知這部分

if (memoryPaths.length > 0) {
  const msg = createMemorySavedMessage(memoryPaths)
  appendSystemMessage?.(msg)  // 注入 system reminder 到主對話
}
```

## 十二、drainPendingExtraction()

```typescript
export async function drainPendingExtraction(timeoutMs?: number): Promise<void> {
  await drainer(timeoutMs)
}
```

在 `print.ts` 輸出回應後、`gracefulShutdownSync` 前呼叫，確保 forked agent 在 5 秒關機超時前完成。
