# 04 — Observability 與遙測設計分析

## 概述

Claude Code 的 observability 架構分為三個層次：**Analytics/Events**（業務事件）、**OpenTelemetry**（分散式追蹤與指標）、**Diagnostic Tracking**（IDE 整合的即時診斷）。三者各司其職，共同覆蓋從 session 層到工具執行層的完整可觀測性。

---

## 1. Bootstrap State 中的遙測狀態

`bootstrap/state.ts` 是遙測基礎設施的單一真實來源：

```typescript
// src/bootstrap/state.ts — 遙測相關欄位
type State = {
  // OTel Metrics
  meter: Meter | null
  sessionCounter: AttributedCounter | null
  locCounter: AttributedCounter | null           // Lines of Code 計數
  prCounter: AttributedCounter | null            // PR 計數
  commitCounter: AttributedCounter | null        // commit 計數
  costCounter: AttributedCounter | null          // 費用計數
  tokenCounter: AttributedCounter | null         // token 計數
  codeEditToolDecisionCounter: AttributedCounter | null  // code edit 決策
  activeTimeCounter: AttributedCounter | null    // 活躍時間
  statsStore: { observe(name: string, value: number): void } | null

  // OTel 追蹤
  loggerProvider: LoggerProvider | null
  eventLogger: ReturnType<typeof logs.getLogger> | null
  meterProvider: MeterProvider | null
  tracerProvider: BasicTracerProvider | null

  // 請求追蹤
  lastAPIRequest: Omit<BetaMessageStreamParams, 'messages'> | null
  lastAPIRequestMessages: BetaMessageStreamParams['messages'] | null
  lastClassifierRequests: unknown[] | null
  lastMainRequestId: string | undefined
  lastApiCompletionTimestamp: number | null

  // 效能追蹤（per-turn）
  turnHookDurationMs: number
  turnToolDurationMs: number
  turnClassifierDurationMs: number
  turnToolCount: number
  turnHookCount: number
  turnClassifierCount: number
}
```

---

## 2. Analytics Events 系統

### 2.1 事件命名慣例

所有事件前綴為 `tengu_`（Claude Code 的內部代號），例如：

| 事件名稱 | 觸發時機 |
|----------|----------|
| `tengu_startup_telemetry` | 應用啟動 |
| `tengu_managed_settings_loaded` | MDM 設定載入 |
| `tengu_api_before_normalize` | 正規化前的 message 計數 |
| `tengu_api_after_normalize` | 正規化後的 message 計數 |
| `tengu_tool_use_error` | 工具執行錯誤 |
| `tengu_tool_use_cancelled` | 工具被取消 |
| `tengu_tool_use_progress` | 工具執行中進度 |
| `tengu_tool_use_can_use_tool_rejected` | 工具執行被拒絕 |
| `tengu_deferred_tool_schema_not_sent` | 延遲工具 schema 未送出 |
| `tengu_coordinator_mode_switched` | Coordinator 模式切換 |
| `tengu_off_switch_query` | off-switch 觸發 |
| `tengu_nonstreaming_fallback_error` | non-streaming fallback 錯誤 |

### 2.2 PII 安全型別保護

分析事件使用特殊型別標記確保 PII 合規：

```typescript
// 必須明確驗證才能用此型別
type AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS

// 使用範例（強制開發者在 code review 中確認）
logEvent('tengu_tool_use_error', {
  error: 'InputValidationError' as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
  toolName: sanitizeToolNameForAnalytics(tool.name),  // 工具名稱被清理
  queryChainId: chainId as AnalyticsMetadata_...,
})
```

### 2.3 啟動遙測

```typescript
// src/main.tsx (line 307)
async function logStartupTelemetry(): Promise<void> {
  const [isGit, worktreeCount, ghAuthStatus] = await Promise.all([
    getIsGit(), getWorktreeCount(), getGhAuthStatus()
  ])
  logEvent('tengu_startup_telemetry', {
    is_git: isGit,
    worktree_count: worktreeCount,
    gh_auth_status: ghAuthStatus,
    sandbox_enabled: SandboxManager.isSandboxingEnabled(),
    auto_updater_disabled: isAutoUpdaterDisabled(),
    prefers_reduced_motion: ...,
    has_node_extra_ca_certs: ...,
    has_client_cert: ...,
    has_use_system_ca: ...,
  })
}
```

---

## 3. OpenTelemetry 追蹤（sessionTracing）

### 3.1 追蹤層級

```
Session Span
├─ Interaction Span (per user turn)
│   ├─ LLM Request Span (per API call)
│   └─ Tool Span (per tool execution)
│       ├─ Tool Blocked On User Span (permission wait)
│       └─ Tool Execution Span (actual execution)
```

### 3.2 Tool Span 的關鍵追蹤

```typescript
// src/services/tools/toolExecution.ts (line 909)
startToolSpan(
  tool.name,
  toolAttributes,  // file_path, command 等
  isBetaTracingEnabled() ? jsonStringify(processedInput) : undefined,
)
startToolBlockedOnUserSpan()
  // ... permission dialog ...
endToolBlockedOnUserSpan('accept' | 'reject', source)

startToolExecutionSpan()
  // ... tool.call() ...
endToolExecutionSpan()

addToolContentEvent(...)  // 記錄工具輸出摘要
endToolSpan()
```

### 3.3 LLM Request Span

```typescript
// src/services/api/claude.ts (line 1498)
const llmSpan = startLLMRequestSpan(
  options.model,
  newContext,      // system prompt, querySource, tools (若 beta tracing 開啟)
  messagesForAPI,
  isFastMode,
)
```

### 3.4 OTel Event — tool_decision

```typescript
// 記錄每個工具的權限決策
void logOTelEvent('tool_decision', {
  decision: 'accept' | 'reject',
  source: 'user_temporary' | 'user_permanent' | 'user_reject' | 'config' | 'hook',
  tool_name: sanitizeToolNameForAnalytics(tool.name),
})
```

**source 映射邏輯：**
```typescript
function ruleSourceToOTelSource(ruleSource: string, behavior: 'allow' | 'deny'): string {
  switch (ruleSource) {
    case 'session':        return behavior === 'allow' ? 'user_temporary' : 'user_reject'
    case 'localSettings':
    case 'userSettings':   return behavior === 'allow' ? 'user_permanent' : 'user_reject'
    default:               return 'config'  // cliArg, policySettings 等
  }
}
```

---

## 4. Per-Turn 效能追蹤

每個 turn 結束時重置的計數器，用於分析每次互動的細粒度效能：

```typescript
// bootstrap/state.ts 的 per-turn 計數器
turnHookDurationMs: 0      // hook 總執行時間
turnToolDurationMs: 0      // 工具總執行時間
turnClassifierDurationMs: 0  // 分類器總執行時間
turnToolCount: 0           // 工具呼叫次數
turnHookCount: 0           // hook 呼叫次數
turnClassifierCount: 0     // 分類器呼叫次數
```

重置時機（REPL.tsx）：
```typescript
resetTurnHookDuration()
resetTurnToolDuration()
resetTurnClassifierDuration()
```

---

## 5. Diagnostic Tracking Service（IDE 整合）

`DiagnosticTrackingService` 是 IDE 整合層的可觀測性服務，追蹤 LSP 診斷變化：

```typescript
// src/services/diagnosticTracking.ts
export class DiagnosticTrackingService {
  private baseline: Map<string, Diagnostic[]>         // 編輯前的診斷基準
  private rightFileDiagnosticsState: Map<string, Diagnostic[]>  // diff view 右側
  private lastProcessedTimestamps: Map<string, number>

  // 工作流程：
  async beforeFileEdited(filePath: string): Promise<void>
  // → 呼叫 IDE RPC: getDiagnostics(uri: "file://...")
  // → 儲存為 baseline

  async getNewDiagnostics(): Promise<DiagnosticFile[]>
  // → 取得所有診斷
  // → 比對 baseline，回傳新增的診斷
  // → 處理 _claude_fs_right (diff view 右側) 優先邏輯
}
```

### 5.1 Diagnostic 差異算法

```typescript
// 找出新增的 diagnostics（非 baseline 中的）
const newDiagnostics = fileToUse.diagnostics.filter(
  d => !baselineDiagnostics.some(b => areDiagnosticsEqual(d, b))
)
```

比對維度：message + severity + source + code + range（精確到 line/character）

### 5.2 Diff View 特殊處理

IDE 的 diff view 包含兩個 URI：
- `file://path` — 原始檔案（left side）
- `_claude_fs_right:path` — 編輯後預覽（right side）

優先使用 right side 的診斷（更即時），但需追蹤其是否已變化：
```typescript
if (!previousRightDiagnostics ||
    !areDiagnosticArraysEqual(previousRightDiagnostics, claudeFsRightFile.diagnostics)) {
  fileToUse = claudeFsRightFile  // 使用最新的 right-side 診斷
}
```

### 5.3 格式化輸出

```typescript
static formatDiagnosticsSummary(files: DiagnosticFile[]): string
// 輸出格式：
// filename.ts:
//   ✖ [Line 42:8] Property 'foo' does not exist on type 'Bar' [ts(2339)] (typescript)
//   ⚠ [Line 15:1] Unused variable 'x' [no-unused-vars] (eslint)
// （最多 4000 字元，超出截斷）
```

---

## 6. Prompt Cache 監控

### 6.1 Cache Break 偵測

```typescript
// src/services/api/promptCacheBreakDetection.ts
recordPromptState({
  system, toolSchemas, querySource, model,
  fastMode, globalCacheStrategy, betas,
  autoModeActive, isUsingOverage,
  cachedMCEnabled, effortValue, extraBodyParams,
})
// 比對前一次請求，記錄哪個欄位改變觸發了 cache miss
```

### 6.2 Cache 使用量追蹤

bootstrap state 追蹤 cache metrics，透過 OTel 發送：
- `cache_creation_input_tokens`
- `cache_read_input_tokens`
- `ephemeral_1h_input_tokens`
- `ephemeral_5m_input_tokens`

---

## 7. 錯誤日誌

### 7.1 In-Memory Error Log

```typescript
// bootstrap/state.ts
inMemoryErrorLog: Array<{ error: string; timestamp: string }>
// 近期錯誤的環形緩衝，用於 /share 和 bug report
```

### 7.2 診斷日誌（不含 PII）

```typescript
logForDiagnosticsNoPII('info', 'prefetch_system_context_non_interactive')
// 格式化為事件名稱（無用戶資料）
// 用於 CLI 本地診斷 vs. Statsig analytics
```

---

## 8. Observability 架構總圖

```
┌─────────────────────────────────────────────────────────────┐
│                   Observability Stack                        │
│                                                             │
│  ┌─────────────────┐  ┌──────────────────┐                 │
│  │ Analytics Events│  │  OpenTelemetry    │                 │
│  │ (tengu_*)       │  │  Spans + Metrics  │                 │
│  │                 │  │                   │                 │
│  │ GrowthBook      │  │ sessionTracing.ts │                 │
│  │ Statsig sink    │  │  LLM Req Span     │                 │
│  └────────┬────────┘  │  Tool Span        │                 │
│           │           │  Interaction Span │                 │
│           │           └────────┬──────────┘                 │
│           │                    │                            │
│  ┌────────▼────────────────────▼──────────┐                │
│  │          Bootstrap STATE               │                │
│  │  (meters, counters, lastAPIRequest,    │                │
│  │   turn durations, error log)           │                │
│  └────────────────────────────────────────┘                │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │  DiagnosticTrackingService              │               │
│  │  (IDE LSP diagnostics, diff view)       │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. 可觀測性設計原則

| 原則 | 實作 |
|------|------|
| PII 安全型別 | 強制型別標記 + sanitize 函式 |
| 分層追蹤 | Analytics / OTel / Diagnostic 各自獨立 |
| 效能分離 | per-turn vs. session-total 計數器 |
| Cache 健康 | break detection + header latch 追蹤 |
| Minification 安全 | classifyToolError() 使用 stable 名稱 |
