# 07 — 工具執行與編排邏輯分析

> 來源：`src/services/tools/toolExecution.ts`（1745 行）+ `src/services/tools/toolOrchestration.ts`（189 行）

---

## 概覽

工具執行分為兩層：

| 層次 | 檔案 | 職責 |
|---|---|---|
| **編排層** | `toolOrchestration.ts` | 決定工具批次如何並行/串行執行 |
| **執行層** | `toolExecution.ts` | 單一工具的完整生命週期（驗證 → 授權 → 執行 → hook → 結果）|

---

## 一、工具編排（toolOrchestration.ts）

### 核心函數：`runTools()`

```typescript
export async function* runTools(
  toolUseMessages: ToolUseBlock[],
  assistantMessages: AssistantMessage[],
  canUseTool: CanUseToolFn,
  toolUseContext: ToolUseContext,
): AsyncGenerator<MessageUpdate, void>
```

**流程：**
1. 對傳入的所有 `toolUseMessages` 呼叫 `partitionToolCalls()` 進行分批
2. 每批次依 `isConcurrencySafe` 決定並行或串行執行
3. 回傳的 `contextModifier` 在批次結束後統一套用

### 分批邏輯：`partitionToolCalls()`

```typescript
// 規則：
// - 若工具的 isConcurrencySafe() 為 true → 可合入前一批並行批次
// - 否則 → 單獨一批（串行）
```

**分批結果結構：**
```typescript
type Batch = { isConcurrencySafe: boolean; blocks: ToolUseBlock[] }
// 範例：[Read, Read, Read] → 一批（並行）
// 範例：[Read, Write, Read] → [批1: Read], [批2: Write], [批3: Read]
```

### 並行執行：`runToolsConcurrently()`

```typescript
async function* runToolsConcurrently(...)
// 使用 `all(generators, maxConcurrency)` 實作
// 並發上限：CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY 環境變數，預設 10
```

### 串行執行：`runToolsSerially()`

```typescript
async function* runToolsSerially(...)
// 依序執行，每個工具的 contextModifier 立即套用
// 每個工具完成後呼叫 markToolUseAsComplete()
```

### 設計亮點

| 特點 | 說明 |
|---|---|
| 讀寫分離 | read-only 工具（`isConcurrencySafe=true`）合批並行，避免寫入競爭 |
| contextModifier 延遲套用 | 並行批次的 context 修改排隊，等批次完成後統一套用 |
| in-progress tracking | 每個 toolUseID 進入/退出時更新 `setInProgressToolUseIDs` |
| 最大並發上限 | 預設 10，可透過環境變數調整 |

---

## 二、工具執行（toolExecution.ts）

### 核心函數：`runToolUse()`

**完整流程：**

```
runToolUse()
  ├── 1. 查找工具（findToolByName）
  │     └── 若不存在 → 嘗試別名（deprecated 工具向前相容）
  │     └── 若仍不存在 → yield 錯誤訊息，return
  │
  ├── 2. 中止檢查（abortController.signal.aborted）
  │     └── 若已中止 → yield CANCEL_MESSAGE，return
  │
  └── 3. streamedCheckPermissionsAndCallTool()
        └── checkPermissionsAndCallTool()（async）
```

### 核心函數：`checkPermissionsAndCallTool()`

**詳細流程（11 個階段）：**

```
1. Zod 輸入驗證（tool.inputSchema.safeParse）
   ├── 失敗 → InputValidationError，含 deferred tool 提示
   └── 成功 → 繼續

2. 自定義輸入驗證（tool.validateInput）
   ├── result=false → 自訂錯誤訊息
   └── 成功 → 繼續

3. 投機性分類器啟動（Bash 工具專屬）
   └── startSpeculativeClassifierCheck()（並行，不阻塞）

4. 輸入前處理
   ├── 剝除 _simulatedSedEdit（defence-in-depth）
   └── backfillObservableInput（擴展路徑等）

5. PreToolUse hooks 執行
   ├── runPreToolUseHooks()
   ├── 可回傳：message / hookPermissionResult / hookUpdatedInput /
   │          preventContinuation / stopReason / additionalContext / stop
   └── 計時：>500ms 顯示 hook 摘要；>2000ms log warning

6. 開始 OTel tracing span（startToolSpan / startToolBlockedOnUserSpan）

7. 權限決策（resolveHookPermissionDecision）
   ├── hook 結果 → 優先
   ├── canUseTool → 次之（含互動式 permission dialog）
   └── 計時：auto 模式 >2000ms log warning

8. 權限拒絕處理
   ├── PermissionDenied hooks（TRANSCRIPT_CLASSIFIER feature）
   ├── 含圖片 content blocks 支援
   └── retry 信號處理

9. 工具執行（tool.call()）
   ├── 傳入 callInput（原始 model 輸入，非 backfilled）
   ├── 回傳 result.data, result.contextModifier, result.mcpMeta,
   │   result.structured_output, result.newMessages
   └── 記錄 durationMs → addToToolDuration()

10. PostToolUse hooks 執行
    ├── runPostToolUseHooks()
    ├── MCP 工具：hook 可 updatedMCPToolOutput
    ├── 非 MCP 工具：先 addToolResult，再跑 hooks
    └── 計時：>500ms 顯示 hook 摘要；>2000ms log warning

11. 結果打包
    ├── processToolResultBlock / processPreMappedToolResultBlock
    │   └── 超過 DEFAULT_MAX_RESULT_SIZE_CHARS → 存檔，回傳 preview
    ├── acceptFeedback（用戶 approve 時的回饋文字）
    ├── contentBlocks（圖片等附加內容）
    └── structured_output attachment message
```

### 錯誤處理流程

```
catch(error)
  ├── AbortError → 不 log，標記 isInterrupt=true
  ├── ShellError → 不 logError（已有其他處理）
  ├── McpAuthError → 更新 MCP client 狀態為 'needs-auth'
  ├── 其他 → logError + tengu_tool_use_error 事件
  └── 執行 PostToolUseFailure hooks
      └── 回傳 tool_result (is_error: true)
```

### `classifyToolError()` — 錯誤分類

```typescript
// 目的：minified build 中 error.constructor.name 被壓縮成 "nJT"，無法識別
// 解決方案：
// - TelemetrySafeError → 用 telemetryMessage
// - Node.js fs 錯誤 → 用 code（ENOENT, EACCES）
// - 有穩定 .name 屬性的 Error → 用 name
// - fallback → "Error"
```

---

## 三、工具執行的 Telemetry 事件

| 事件名稱 | 觸發時機 | 關鍵欄位 |
|---|---|---|
| `tengu_tool_use_error` | 找不到工具、輸入驗證失敗、執行錯誤 | toolName, error, isMcp |
| `tengu_tool_use_cancelled` | abortController 觸發 | toolName |
| `tengu_tool_use_can_use_tool_rejected` | 權限拒絕 | toolName, queryDepth |
| `tengu_tool_use_can_use_tool_allowed` | 權限通過 | toolName, queryDepth |
| `tengu_tool_use_success` | 執行成功 | toolName, durationMs, toolResultSizeBytes, fileExtension |
| `tengu_tool_use_progress` | 工具發送 progress 事件 | toolName |
| `tengu_deferred_tool_schema_not_sent` | deferred 工具未 ToolSearch 就呼叫 | toolName |

**OTel 事件（OTLP）：**
- `tool_decision`：權限決策（accept/reject + source）
- `tool_result`：工具完成（success/fail + duration + 參數）

---

## 四、權限決策鏈

```
hookPermissionResult（PreToolUse hook）
  │
  ▼（若 hook 未決定）
canUseTool（互動/自動模式）
  │
  ├── allow → 繼續執行
  ├── deny → 回傳錯誤 message
  └── ask → 互動式 permission dialog
        ├── user approves → allow（含 acceptFeedback）
        └── user denies → deny（含 contentBlocks 圖片）
```

**`decisionReasonToOTelSource()` — 決策來源分類：**
```typescript
// OTel 詞彙：config, hook, user_permanent, user_temporary, user_reject
permissionPromptTool → decisionClassification（若有）或 user_temporary/user_reject
rule.source === 'session' → allow: user_temporary / deny: user_reject
rule.source === 'localSettings'/'userSettings' → allow: user_permanent / deny: user_reject
其他（mode, classifier, asyncAgent 等）→ config
```

---

## 五、特殊執行路徑

### Bash 工具的 _simulatedSedEdit 防護

```typescript
// Defence-in-depth：模型不應自行設定此欄位
// 它只能由 permission 系統（SedEditPermissionRequest）在用戶同意後注入
if ('_simulatedSedEdit' in processedInput) {
  // 強制剝除
}
```

### backfillObservableInput

```typescript
// 目的：hooks 和 canUseTool 看到「觀察用」版本（例如展開後的絕對路徑）
// 但 tool.call() 收到「原始輸入」（模型產出的路徑）
// 這確保 tool result 中的路徑字串與模型看到的一致（VCR fixture hash 穩定）
```

### deferred 工具 Schema 未送提示

```typescript
// 若 Zod 驗證失敗 + 工具是 deferred + schema 未載入：
// 附加提示："Load the tool first: call ToolSearch with query 'select:{toolName}', then retry."
```

### MCP vs 非 MCP 工具的 Post-hook 差異

```
非 MCP 工具：
  tool.call() → addToolResult（pre-mapped block）→ PostToolUse hooks

MCP 工具：
  tool.call() → PostToolUse hooks（可 updatedMCPToolOutput）→ addToolResult（從修改後輸出重新 map）
```

---

## 六、工具結果大小管理

**處理流程（`processToolResultBlock`）：**

1. map tool result → `ToolResultBlockParam`
2. 計算 `toolResultSizeBytes`
3. 若超過 `DEFAULT_MAX_RESULT_SIZE_CHARS`（50,000）→ 寫檔，回傳 preview + 路徑
4. `processPreMappedToolResultBlock` 用於已有 pre-mapped block 的情況（避免重複 map）

**跨工具訊息 budget（per-message）：**
- `MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200,000`
- 並行工具各自可達 50K，但合計超過 200K 時最大的被存檔

---

## 七、工具整體架構圖

```
claude.ts（query loop）
    │
    ▼
toolOrchestration.runTools()
    │
    ├── partitionToolCalls() → Batch[]
    │     └── isConcurrencySafe → 讀寫分離
    │
    ├── [並行批] runToolsConcurrently()
    │     └── all(generators, maxConcurrency=10)
    │           └── runToolUse()
    │
    └── [串行批] runToolsSerially()
          └── runToolUse()

runToolUse()
    └── streamedCheckPermissionsAndCallTool()
          └── checkPermissionsAndCallTool()
                ├── Zod 驗證
                ├── validateInput
                ├── startSpeculativeClassifierCheck（Bash）
                ├── backfillObservableInput
                ├── runPreToolUseHooks
                ├── resolveHookPermissionDecision
                ├── tool.call()
                ├── runPostToolUseHooks
                └── processToolResultBlock → addToolResult
```
