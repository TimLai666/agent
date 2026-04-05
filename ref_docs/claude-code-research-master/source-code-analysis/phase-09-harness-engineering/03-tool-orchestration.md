# 03 — Tool Orchestration 設計模式深度分析

## 概述

Claude Code 的 Tool Orchestration 層是 harness 中最精密的部分之一。它分為兩個互補的模組：`toolOrchestration.ts`（決定「如何」執行工具集合）與 `toolExecution.ts`（決定「如何執行單一工具」），兩者共同構成一個多階段、多重防護的工具調度系統。

---

## 1. 整體架構

```
toolOrchestration.ts              toolExecution.ts
─────────────────────             ──────────────────────────────
runTools()                        runToolUse()
  │                                 │
  ├─ partitionToolCalls()            ├─ findToolByName()
  │   (read-only batch?)             ├─ abort check
  │                                  ├─ streamedCheckPermissionsAndCallTool()
  ├─ runToolsConcurrently()              │
  │   (async, max 10)                    ├─ checkPermissionsAndCallTool()
  │                                          │
  └─ runToolsSerially()                       ├─ 1. Zod validate
      (one by one)                            ├─ 2. validateInput()
                                              ├─ 3. startSpeculativeClassifier
                                              ├─ 4. backfillObservableInput()
                                              ├─ 5. runPreToolUseHooks()
                                              ├─ 6. resolveHookPermissionDecision()
                                              ├─ 7. canUseTool() / permission dialog
                                              ├─ 8. tool.call()
                                              ├─ 9. runPostToolUseHooks()
                                              └─ 10. return MessageUpdateLazy[]
```

---

## 2. 並行/串行分批策略 (toolOrchestration.ts)

### 2.1 批次分類演算法

```typescript
// src/services/tools/toolOrchestration.ts (line 91)
function partitionToolCalls(
  toolUseMessages: ToolUseBlock[],
  toolUseContext: ToolUseContext,
): Batch[] {
  return toolUseMessages.reduce((acc: Batch[], toolUse) => {
    const tool = findToolByName(toolUseContext.options.tools, toolUse.name)
    const parsedInput = tool?.inputSchema.safeParse(toolUse.input)
    const isConcurrencySafe = parsedInput?.success
      ? Boolean(tool?.isConcurrencySafe(parsedInput.data))
      : false

    // 相鄰的 read-only tool 合併成同一批
    if (isConcurrencySafe && acc[acc.length - 1]?.isConcurrencySafe) {
      acc[acc.length - 1]!.blocks.push(toolUse)
    } else {
      acc.push({ isConcurrencySafe, blocks: [toolUse] })
    }
    return acc
  }, [])
}
```

**批次規則：**
- `isConcurrencySafe = true`：相鄰 read-only 工具合併並行執行
- `isConcurrencySafe = false`：獨立串行，必須等前一個完成
- 安全性優先：若 `isConcurrencySafe()` 拋出例外，預設為 `false`

### 2.2 並行執行流（runToolsConcurrently）

```typescript
// src/services/tools/toolOrchestration.ts (line 152)
async function* runToolsConcurrently(
  toolUseMessages: ToolUseBlock[],
  ...
): AsyncGenerator<MessageUpdateLazy, void> {
  yield* all(
    toolUseMessages.map(async function* (toolUse) {
      yield* runToolUse(toolUse, ...)
      markToolUseAsComplete(toolUseContext, toolUse.id)
    }),
    getMaxToolUseConcurrency(),  // 預設 10，可由環境變數覆蓋
  )
}
```

**關鍵細節**：並行執行時 context modifiers 需要佇列化，不能立即應用（避免 race condition）：
```typescript
const queuedContextModifiers: Record<string, ((context: ToolUseContext) => ToolUseContext)[]> = {}
// 等批次結束後才套用所有 modifiers
for (const block of blocks) {
  const modifiers = queuedContextModifiers[block.id]
  for (const modifier of modifiers) {
    currentContext = modifier(currentContext)
  }
}
```

---

## 3. 工具執行單元 (toolExecution.ts)

### 3.1 工具查找機制

```typescript
// src/services/tools/toolExecution.ts (line 344)
let tool = findToolByName(toolUseContext.options.tools, toolName)

// fallback: 向下相容廢棄名稱（alias 機制）
if (!tool) {
  const fallbackTool = findToolByName(getAllBaseTools(), toolName)
  if (fallbackTool && fallbackTool.aliases?.includes(toolName)) {
    tool = fallbackTool  // e.g., 'KillShell' → 'TaskStop'
  }
}
```

### 3.2 Stream-based Progress 架構

`streamedCheckPermissionsAndCallTool` 使用自製 `Stream` 類別將 callback 式 API 轉為 async iterable：

```typescript
// 核心技巧：Bridge pattern — callback → async iterable
const stream = new Stream<MessageUpdateLazy>()
checkPermissionsAndCallTool(
  ...,
  progress => {
    stream.enqueue({ message: createProgressMessage({...}) })
  }
).then(results => {
  for (const result of results) stream.enqueue(result)
}).finally(() => stream.done())
return stream
```

這讓進度事件（progress）和最終結果（results）共享同一個 async iterable，呼叫端不需要區分。

---

## 4. 工具執行的多層防護

### 4.1 Layer 1 — Schema 驗證（Zod）

```typescript
const parsedInput = tool.inputSchema.safeParse(input)
if (!parsedInput.success) {
  // 特殊 hint：若是 deferred tool schema 未送出導致的錯誤
  const schemaHint = buildSchemaNotSentHint(tool, messages, tools)
  // → 告知模型需要先呼叫 ToolSearch 載入 schema
  return [createUserMessage({ content: errorContent + schemaHint, is_error: true })]
}
```

### 4.2 Layer 2 — 工具自訂驗證

```typescript
const isValidCall = await tool.validateInput?.(parsedInput.data, toolUseContext)
if (isValidCall?.result === false) {
  return [createUserMessage({ content: isValidCall.message, is_error: true })]
}
```

### 4.3 Layer 3 — Input 清理

```typescript
// 防禦性移除內部欄位，即使 schema strict 已拒絕
if (tool.name === BASH_TOOL_NAME && '_simulatedSedEdit' in processedInput) {
  const { _simulatedSedEdit: _, ...rest } = processedInput
  processedInput = rest
}

// backfillObservableInput: 為 hooks 補充可觀察欄位（不影響 call() 的 input）
const backfilledClone = tool.backfillObservableInput && {...processedInput}
if (backfilledClone) tool.backfillObservableInput!(backfilledClone)
```

### 4.4 Layer 4 — PreToolUse Hooks

```typescript
for await (const result of runPreToolUseHooks(...)) {
  switch (result.type) {
    case 'message':           // hook 發出訊息
    case 'hookPermissionResult':   // hook 做出 allow/deny 決定
    case 'hookUpdatedInput':  // hook 修改 input（pass-through）
    case 'preventContinuation':    // hook 要求停止
    case 'stopReason':        // hook 提供停止原因
    case 'additionalContext': // hook 附加 context
    case 'stop':              // hook 停止執行
  }
}
```

### 4.5 Layer 5 — 權限決策

```typescript
const resolved = await resolveHookPermissionDecision(
  hookPermissionResult,  // hooks 的決定（若有）
  tool, processedInput,
  toolUseContext,
  canUseTool,            // REPL 提供的互動式 canUseTool
  ...
)
// → 'allow' | 'deny' | 'ask'
```

### 4.6 Layer 6 — PostToolUse Hooks

執行完畢後，runPostToolUseHooks 可以修改結果、附加 context，或觸發進一步行動。

---

## 5. 工具執行的 OTel 追蹤

工具執行有完整的 OpenTelemetry span 包圍：

```typescript
startToolSpan(tool.name, toolAttributes, jsonStringify(processedInput))
  startToolBlockedOnUserSpan()       // 等待使用者決定
  // → permission dialog
  endToolBlockedOnUserSpan('accept'/'reject', source)

  startToolExecutionSpan()           // 實際執行
  // → tool.call()
  endToolExecutionSpan()

  addToolContentEvent(...)           // 記錄 tool 輸出
endToolSpan()
```

---

## 6. 錯誤分類系統

```typescript
// src/services/tools/toolExecution.ts (line 150)
export function classifyToolError(error: unknown): string {
  if (error instanceof TelemetrySafeError) return error.telemetryMessage
  if (error instanceof Error) {
    const errnoCode = getErrnoCode(error)
    if (errnoCode) return `Error:${errnoCode}`   // ENOENT, EACCES 等
    if (error.name && error.name !== 'Error' && error.name.length > 3)
      return error.name.slice(0, 60)             // ShellError, ImageSizeError 等
    return 'Error'
  }
  return 'UnknownError'
}
```

**設計背景**：生產 build 中 constructor.name 被 minify 成無意義字串（如 `nJT`），這個函式確保 telemetry 始終有語意性錯誤標籤。

---

## 7. 並行工具執行範例

```
模型輸出包含三個工具調用：
  [Read file A]  ← isConcurrencySafe: true
  [Read file B]  ← isConcurrencySafe: true
  [Edit file C]  ← isConcurrencySafe: false

partitionToolCalls 分批結果：
  Batch 1: { isConcurrencySafe: true,  blocks: [Read A, Read B] }
  Batch 2: { isConcurrencySafe: false, blocks: [Edit C] }

執行順序：
  t=0:  Read A 和 Read B 並行啟動
  t=N:  兩者完成，套用 context modifiers
  t=N+: Edit C 串行執行
  t=M:  Edit C 完成
```

---

## 8. 設計模式總結

| 模式 | 說明 |
|------|------|
| Pipeline Pattern | toolExecution 的多層防護依序執行 |
| Strategy Pattern | isConcurrencySafe 讓工具自己決定是否可並行 |
| Bridge Pattern | Stream 橋接 callback 式 API 和 async iterable |
| Guard Clause Pattern | 每層防護失敗立即 return，不繼續執行 |
| Observer Pattern | hooks 系統讓外部程式可以觀察和介入工具執行 |
| Latch Pattern | 工具進行中 ID 集合（setInProgressToolUseIDs）追蹤狀態 |
