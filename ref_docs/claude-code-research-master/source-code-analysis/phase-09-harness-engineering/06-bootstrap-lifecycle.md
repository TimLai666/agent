# 06 — 啟動流程與生命週期分析

## 概述

Claude Code 的啟動流程是高度優化的並行流水線，目標是最小化「time to first render」和「time to first API call ready」。bootstrap/state.ts 是整個 session 生命週期的中心狀態存儲。

---

## 1. 啟動計時器系統

```typescript
// src/main.tsx (line 9-12)
// 這些 side-effect 必須在所有其他 import 之前執行：
// 1. profileCheckpoint 在大量 module 評估前標記入口
// 2. startMdmRawRead 並行啟動 MDM 子進程
// 3. startKeychainPrefetch 並行啟動 macOS keychain 讀取

profileCheckpoint('main_tsx_entry')
startMdmRawRead()         // 並行：MDM 設定讀取（plutil/reg query）
startKeychainPrefetch()   // 並行：Keychain OAuth + API key 讀取（~65ms on macOS）
```

**目的**：這三個操作是昂貴的 I/O，透過在 module import 期間並行啟動，讓它們與 ~135ms 的 import 評估重疊執行。

---

## 2. 完整啟動流水線

```
main.tsx 頂層執行：
    profileCheckpoint('main_tsx_entry')
    startMdmRawRead()              ← 並行開始
    startKeychainPrefetch()        ← 並行開始
    ... 135ms 的 imports ...
    profileCheckpoint('main_tsx_imports_loaded')

setup() 函式（sync 部分）：
    eagerLoadSettings()            ← --settings 旗標的早期解析
    ensureMdmSettingsLoaded()      ← 等待 MDM 完成
    init()                         ← 認證、設定初始化
    runMigrations()                ← 設定版本遷移
    initializeEntrypoint()         ← 設定 CLAUDE_CODE_ENTRYPOINT
    loadTools()                    ← 建立工具清單
    setupMCP()                     ← 連接 MCP servers

startDeferredPrefetches()（第一次 render 後）：
    initUser()                     ← 使用者資料
    getUserContext()               ← 使用者 context（git info 等）
    prefetchSystemContextIfSafe()  ← 系統 context（若已信任）
    getRelevantTips()              ← 提示建議
    countFilesRoundedRg()          ← 專案檔案計數
    initializeAnalyticsGates()
    settingsChangeDetector.initialize()
    skillChangeDetector.initialize()
```

---

## 3. Bootstrap State 的核心結構

`STATE` 是全域單例，存放整個 session 的所有可變狀態：

```typescript
// src/bootstrap/state.ts (line 429)
const STATE: State = getInitialState()

// 初始值摘要
{
  originalCwd: realpathSync(cwd()).normalize('NFC'),  // 解析符號連結
  projectRoot: ...,                                    // 穩定專案根目錄
  totalCostUSD: 0,
  totalAPIDuration: 0,
  totalToolDuration: 0,
  sessionId: randomUUID(),                             // 每次啟動新 UUID
  isInteractive: false,
  clientType: 'cli',
  allowedSettingSources: ['userSettings', 'projectSettings', 'localSettings', 'flagSettings', 'policySettings'],
  // 所有遙測計數器: null（等待 OTel 初始化後設置）
  // 所有 latch 狀態: null（等待首次觸發）
}
```

---

## 4. Session 生命週期狀態機

```
┌──────────────────────────────────────────────────────────────┐
│                   SESSION LIFECYCLE                          │
│                                                              │
│  INIT                                                        │
│   ├─ authenticate (OAuth/API key)                            │
│   ├─ load settings (user/project/policy)                     │
│   ├─ load tools + MCP                                        │
│   └─ trust check → show setup screens if needed             │
│                                                              │
│  ACTIVE                                                      │
│   ├─ receive user input                                      │
│   ├─ run agent loop (query → tools → response)               │
│   ├─ update STATE (cost, duration, tokens)                   │
│   └─ persist session transcript (.jsonl)                     │
│                                                              │
│  COMPACTION (triggered by token count or /compact)          │
│   ├─ summarize conversation                                  │
│   ├─ reset microcompact state                                │
│   ├─ clear beta header latches                               │
│   └─ continue from compact summary                          │
│                                                              │
│  RESUME                                                      │
│   ├─ load transcript from .jsonl                             │
│   ├─ matchSessionMode() (coordinator/normal 對齊)             │
│   ├─ restoreSessionFilePointer()                             │
│   └─ reconstructContentReplacementState()                   │
│                                                              │
│  SHUTDOWN                                                    │
│   ├─ executeSessionEndHooks()                                │
│   ├─ saveCurrentSessionCosts()                               │
│   ├─ gracefulShutdown() / gracefulShutdownSync()             │
│   └─ SHOW_CURSOR (terminal 復原)                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 設定載入優先順序

設定來源有嚴格的優先順序（`allowedSettingSources`）：

```
policySettings  (最高優先，MDM/企業政策)
    ↓
flagSettings    (--settings CLI 旗標)
    ↓
localSettings   (.claude/settings.local.json)
    ↓
projectSettings (.claude/settings.json)
    ↓
userSettings    (~/.claude/settings.json，最低優先)
```

```typescript
// 遷移版本追蹤
const CURRENT_MIGRATION_VERSION = 11

function runMigrations(): void {
  if (getGlobalConfig().migrationVersion !== CURRENT_MIGRATION_VERSION) {
    migrateAutoUpdatesToSettings()
    migrateBypassPermissionsAcceptedToSettings()
    migrateSonnet1mToSonnet45()
    migrateSonnet45ToSonnet46()
    migrateOpusToOpus1m()
    // ... 共 11 個遷移
    saveGlobalConfig(prev => ({ ...prev, migrationVersion: CURRENT_MIGRATION_VERSION }))
  }
}
```

---

## 6. Session ID 管理

```typescript
// session ID 生命週期
export function getSessionId(): SessionId {
  return STATE.sessionId
}

// 新對話（/clear）
export function regenerateSessionId(options = {}): SessionId {
  if (options.setCurrentAsParent) {
    STATE.parentSessionId = STATE.sessionId
  }
  STATE.planSlugCache.delete(STATE.sessionId)  // 清理 plan slug 快取
  STATE.sessionId = randomUUID() as SessionId
  STATE.sessionProjectDir = null
  return STATE.sessionId
}

// Resume 另一個 session
export function switchSession(sessionId: SessionId, projectDir: string | null = null): void {
  STATE.planSlugCache.delete(STATE.sessionId)
  STATE.sessionId = sessionId
  STATE.sessionProjectDir = projectDir
  sessionSwitched.emit(sessionId)  // 通知訂閱者（如 concurrentSessions.ts）
}
```

---

## 7. 安全 CWD 解析

```typescript
// src/bootstrap/state.ts (line 260)
function getInitialState(): State {
  let resolvedCwd = ''
  const rawCwd = cwd()
  try {
    resolvedCwd = realpathSync(rawCwd).normalize('NFC')
    // realpathSync 解析所有符號連結
    // .normalize('NFC') 統一 Unicode 正規形式（macOS 相關）
  } catch {
    // File Provider EPERM on CloudStorage mounts (lstat per path component)
    resolvedCwd = rawCwd.normalize('NFC')
  }
}
```

---

## 8. 懶載入與循環依賴處理

```typescript
// src/main.tsx (line 69)
// 使用懶 require 避免循環依賴：
// teammate.ts → AppState.tsx → ... → main.tsx

const getTeammateUtils = () => require('./utils/teammate.js')
const getTeammatePromptAddendum = () => require('./utils/swarm/teammatePromptAddendum.js')
const getTeammateModeSnapshot = () => require('./utils/swarm/backends/teammateModeSnapshot.js')

// Dead code elimination: feature gates 讓條件模組在 build 時完全移除
const coordinatorModeModule = feature('COORDINATOR_MODE')
  ? require('./coordinator/coordinatorMode.js')
  : null

const assistantModule = feature('KAIROS')
  ? require('./assistant/index.js')
  : null
```

---

## 9. 前置快取（Deferred Prefetches）

`startDeferredPrefetches()` 在第一次 render 後啟動，用使用者輸入時間隱藏開銷：

```typescript
// src/main.tsx (line 388)
export function startDeferredPrefetches(): void {
  // 跳過條件：效能測試模式 或 bare mode
  if (isEnvTruthy(process.env.CLAUDE_CODE_EXIT_AFTER_FIRST_RENDER) || isBareMode()) return

  // 進程衍生的預取（在使用者打字時完成）
  void initUser()
  void getUserContext()
  prefetchSystemContextIfSafe()
  void getRelevantTips()

  // AWS/GCP 認證預取（若適用）
  if (isEnvTruthy(process.env.CLAUDE_CODE_USE_BEDROCK)) {
    void prefetchAwsCredentialsAndBedRockInfoIfSafe()
  }

  // 輕量異步任務
  void countFilesRoundedRg(getCwd(), AbortSignal.timeout(3000), [])
  void initializeAnalyticsGates()
  void prefetchOfficialMcpUrls()
  void refreshModelCapabilities()

  // 檔案變更偵測器（設定、skills）
  void settingsChangeDetector.initialize()
  void skillChangeDetector.initialize()
}
```

---

## 10. 啟動時間優化摘要

| 技術 | 節省時間 | 說明 |
|------|----------|------|
| MDM/Keychain 並行啟動 | ~65ms | import 期間重疊執行 |
| 延遲 Prefetch | 體感流暢 | 使用者打字時隱藏 |
| 設定快取 | 重複呼叫 | settingsCache 避免重複 I/O |
| Eager 設定解析 | 避免初始化錯誤 | --settings 在 init() 前解析 |
| Trust-gated 系統 context | 安全 | 未信任的目錄不執行 git hooks |
