# 05 — 啟動流程分析

來源：`src/bootstrap/state.ts`（1758 行）、`src/entrypoints/init.ts`

---

## 1. 全域狀態（State）架構

`bootstrap/state.ts` 是整個應用程式的唯一全域狀態容器，遵循「DO NOT ADD MORE STATE HERE - BE JUDICIOUS」原則。

### 狀態型別分類

#### 會話身份與計費

```typescript
sessionId: SessionId           // UUID，每次 /clear 或 /compact 時不變，/resume 重新生成
parentSessionId?: SessionId   // plan mode → implementation 的親子 session 追蹤
originalCwd: string            // 啟動時的工作目錄（symlink 已解析）
projectRoot: string            // 穩定的專案根目錄（--worktree 設定，mid-session 不變）
```

#### 費用與效能追蹤

```typescript
totalCostUSD: number
totalAPIDuration: number
totalAPIDurationWithoutRetries: number
totalToolDuration: number
turnHookDurationMs: number
turnToolDurationMs: number
turnClassifierDurationMs: number
turnToolCount: number
turnHookCount: number
modelUsage: { [modelName: string]: ModelUsage }
```

#### 模型狀態

```typescript
mainLoopModelOverride: ModelSetting | undefined  // /model 指令設定
initialMainLoopModel: ModelSetting              // 啟動時的模型（用於選項顯示）
modelStrings: ModelStrings | null               // provider-specific ID 表，null = 尚未初始化
```

#### Beta Header Latch（Session-stable）

```typescript
afkModeHeaderLatched: boolean | null       // null = 尚未觸發
fastModeHeaderLatched: boolean | null      // sticky-on，/clear 重置
cacheEditingHeaderLatched: boolean | null  // cached microcompact 首次啟用後
thinkingClearLatched: boolean | null       // >1h 無 API 呼叫後
promptCache1hAllowlist: string[] | null    // GrowthBook 快取（session-stable）
promptCache1hEligible: boolean | null      // 用戶資格（session-stable）
```

#### 遙測基礎設施

```typescript
meter: Meter | null
sessionCounter: AttributedCounter | null
locCounter / prCounter / commitCounter / costCounter / tokenCounter / ...
loggerProvider: LoggerProvider | null
eventLogger: ReturnType<typeof logs.getLogger> | null
meterProvider: MeterProvider | null
tracerProvider: BasicTracerProvider | null
```

#### Session 配置

```typescript
isInteractive: boolean
clientType: string              // 'cli' | 'sdk' | 'vscode'
sessionSource: string | undefined
allowedSettingSources: SettingSource[]
sdkBetas: string[] | undefined  // SDK 傳入的額外 beta headers
mainThreadAgentType: string | undefined
isRemoteMode: boolean           // --remote flag
```

#### 其他追蹤

```typescript
lastAPIRequest         // 最後一次 API 請求（用於 bug report）
lastAPIRequestMessages // ant-only：實際傳到 API 的 messages
lastMainRequestId      // 主 session 最後一次 request ID（shutdown 時送快取 eviction hint）
lastApiCompletionTimestamp  // 用於計算 thinkingClearLatched
pendingPostCompaction: boolean  // 下一次 API 呼叫後標記為 post-compaction
invokedSkills: Map          // 已載入 skill 的快取（compaction 後保留）
inMemoryErrorLog            // 最近的錯誤（用於 /share）
```

---

## 2. State 初始化

```typescript
const STATE: State = getInitialState()  // 模組載入時執行一次

function getInitialState(): State {
  // 解析 cwd symlinks → resolvedCwd.normalize('NFC')
  // 初始化所有欄位為 null / false / 0 / undefined / []
  // sessionId = randomUUID()
}
```

State 是模組層級的常數，整個 process lifetime 不會被替換（只透過 setter 函式更新個別欄位）。

---

## 3. init.ts — 啟動程序

`init()` 被 `memoize()` 包裝，確保只執行一次：

```
enableConfigs()                          // 驗證並啟用配置系統
applySafeConfigEnvironmentVariables()    // 應用「安全」環境變數（信任對話前）
applyExtraCACertsFromConfig()            // 早期設定 TLS 憑證（Bun cache at boot）
setupGracefulShutdown()                  // 註冊 exit handlers

// 非同步（fire-and-forget）初始化
initialize1PEventLogging()               // OpenTelemetry 事件日誌
onGrowthBookRefresh()                    // GrowthBook 更新時重建 logger

populateOAuthAccountInfoIfNeeded()       // OAuth account info 快取
initJetBrainsDetection()                 // JetBrains IDE 偵測
detectCurrentRepository()               // GitHub repository 偵測（gitDiff PR linking）

initializeRemoteManagedSettingsLoadingPromise()   // 遠端設定（若 eligible）
initializePolicyLimitsLoadingPromise()            // Policy limits（若 eligible）

recordFirstStartTime()                   // 記錄首次啟動時間

configureGlobalMTLS()                    // mTLS 設定
configureGlobalAgents()                  // HTTP proxy 設定
setShellIfWindows()                      // Windows shell 路徑修正

// === 信任對話後 ===
applyConfigEnvironmentVariables()        // 應用完整環境變數（含 CLAUDE_CODE_USE_BEDROCK 等）
initializeTelemetry()                    // OpenTelemetry SDK 初始化（defer ~1MB 模組）
preconnectAnthropicApi()                 // TCP 預連線
ensureScratchpadDir()                    // scratchpad 目錄
```

---

## 4. Session 管理函式

### Session ID 操作

```typescript
getSessionId()     → STATE.sessionId
regenerateSessionId({ setCurrentAsParent?: boolean })
  // 清除 planSlugCache 舊條目
  // 重置 sessionProjectDir
  // 生成新 UUID

switchSession(sessionId, projectDir?)
  // 切換到另一個 session（/resume 使用）
  // 觸發 onSessionSwitch signal

onSessionSwitch    // 訂閱 session 切換事件（concurrentSessions.ts 使用）
```

### CWD 與路徑

```typescript
getOriginalCwd()           // 不隨 cd 改變（啟動時 cwd）
setOriginalCwd(cwd)        // NFC normalize
getProjectRoot()           // 最穩定的專案根（--worktree 設定，mid-session 不變）
setProjectRoot(cwd)        // 僅供 --worktree 啟動旗標使用
getCwdState()              // 目前 Shell.ts 追蹤的 cwd
setCwdState(cwd)
```

### 費用追蹤

```typescript
addToTotalDurationState(duration, durationWithoutRetries)
// STATE.totalAPIDuration += duration
// STATE.totalAPIDurationWithoutRetries += durationWithoutRetries
```

---

## 5. 重置機制（測試用）

`state.ts` 有一個 `resetStateForTests()` 函式，讓測試可以在每個 test case 之間重置全局狀態，包括 `sessionCronTasks`、`sessionCreatedTeams`、`invokedSkills` 等。

---

## 6. 啟動 checkpoint（ProfileCheckpoint）

`startupProfiler.ts` 追蹤啟動各階段耗時：

```
cli_entry → init_function_start → init_configs_enabled
→ init_safe_env_vars_applied → init_after_graceful_shutdown
→ init_after_1p_event_logging → init_after_oauth_populate
→ init_after_jetbrains_detection → init_after_remote_settings_check
```

這些 checkpoint 用於識別啟動效能瓶頸。
