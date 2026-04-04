# 06 — Task 系統分析

## 概覽

Task 系統是 Claude Code 追蹤所有非同步工作的核心機制，定義於 `src/tasks/`。每種 Task 類型實作 `Task` 介面（含 `kill` 方法），並在 AppState 中以 `TaskState` union 型別存儲。

## Task 類型 Union

```typescript
// src/tasks/types.ts
export type TaskState =
  | LocalShellTaskState
  | LocalAgentTaskState
  | RemoteAgentTaskState
  | InProcessTeammateTaskState
  | LocalWorkflowTaskState
  | MonitorMcpTaskState
  | DreamTaskState
```

背景任務指示器只顯示符合條件的 task：

```typescript
export function isBackgroundTask(task: TaskState): task is BackgroundTaskState {
  if (task.status !== 'running' && task.status !== 'pending') return false
  // Foreground tasks (isBackgrounded === false) 不顯示
  if ('isBackgrounded' in task && task.isBackgrounded === false) return false
  return true
}
```

## 1. LocalAgentTask（本地非同步 subagent）

**檔案**：`src/tasks/LocalAgentTask/LocalAgentTask.tsx`

### 狀態結構

```typescript
type LocalAgentTaskState = TaskStateBase & {
  type: 'local_agent'
  agentId: string
  prompt: string
  selectedAgent?: AgentDefinition
  agentType: string
  model?: string
  abortController?: AbortController
  error?: string
  result?: AgentToolResult
  progress?: AgentProgress
  retrieved: boolean
  messages?: Message[]           // UI 顯示用（非完整 transcript）
  lastReportedToolCount: number
  lastReportedTokenCount: number
  isBackgrounded: boolean
  pendingMessages: string[]      // SendMessage 注入的訊息佇列
  retain: boolean                // UI 正在查看，阻止 GC
  diskLoaded: boolean            // 從磁碟 bootstrap 完成
  evictAfter?: number            // GC 到期時間
}
```

### 關鍵函數

**ProgressTracker 設計**：
```typescript
// input_tokens 在 Claude API 是累計的（含 cache），取最新值
tracker.latestInputTokens = usage.input_tokens
  + (usage.cache_creation_input_tokens ?? 0)
  + (usage.cache_read_input_tokens ?? 0)
// output_tokens 是每 turn 的，累加
tracker.cumulativeOutputTokens += usage.output_tokens
// 最終 token count
getTokenCountFromTracker() = latestInputTokens + cumulativeOutputTokens
```

**ActivityDescriptionResolver**：
```typescript
type ActivityDescriptionResolver = (toolName: string, input: Record<string, unknown>) => string | undefined
// 例："Reading src/foo.ts"、"Searching for 'fetchUser'"
```

最多保留 5 個最近活動（`MAX_RECENT_ACTIVITIES = 5`）。

**pendingMessages 機制**：
```typescript
// SendMessage 工具 → queuePendingMessage()
queuePendingMessage(taskId, msg, setAppState)
// 執行迴圈 → drainPendingMessages()（每個 tool round 邊界）
drainPendingMessages(taskId, getAppState, setAppState)
```

**通知組裝**：
```typescript
enqueueAgentNotification({
  taskId, description, status, error,
  setAppState, finalMessage, usage,
  toolUseId, worktreePath, worktreeBranch
})
```

### Coordinator Task Panel 判定

```typescript
// 只有 agentType !== 'main-session' 的 local_agent 才進 CoordinatorTaskPanel
export function isPanelAgentTask(t: unknown): t is LocalAgentTaskState {
  return isLocalAgentTask(t) && t.agentType !== 'main-session'
}
```

---

## 2. RemoteAgentTask（CCR 遠端 subagent）

**檔案**：`src/tasks/RemoteAgentTask/RemoteAgentTask.tsx`

### 狀態結構

```typescript
type RemoteAgentTaskState = TaskStateBase & {
  type: 'remote_agent'
  remoteTaskType: RemoteTaskType   // 'remote-agent'|'ultraplan'|'ultrareview'|'autofix-pr'|'background-pr'
  remoteTaskMetadata?: RemoteTaskMetadata  // PR number, repo, owner 等
  sessionId: string               // CCR 遠端 session ID
  command: string
  title: string
  todoList: TodoList
  log: SDKMessage[]
  isLongRunning?: boolean         // true = 第一次 result 後不標為完成
  pollStartedAt: number           // 開始 poll 的時間（restore 時重置）
  isRemoteReview?: boolean
  reviewProgress?: {
    stage?: 'finding' | 'verifying' | 'synthesizing'
    bugsFound: number
    bugsVerified: number
    bugsRefuted: number
  }
  isUltraplan?: boolean
  ultraplanPhase?: Exclude<UltraplanPhase, 'running'>
}
```

### RemoteTaskType 種類

| 類型 | 描述 |
|------|------|
| `remote-agent` | 一般遠端 agent（CCR） |
| `ultraplan` | 重量級規劃任務 |
| `ultrareview` | teleported /ultrareview 命令 |
| `autofix-pr` | 自動修復 PR |
| `background-pr` | 背景 PR 處理 |

### CompletionChecker 插件機制

```typescript
// 允許按 remoteTaskType 注冊完成條件檢查器
export function registerCompletionChecker(
  remoteTaskType: RemoteTaskType,
  checker: RemoteTaskCompletionChecker
): void

// checker 在每次 poll 被呼叫，回傳 string = 完成，null = 繼續 poll
type RemoteTaskCompletionChecker = (
  remoteTaskMetadata: RemoteTaskMetadata | undefined
) => Promise<string | null>
```

### 持久化（Metadata Sidecar）

Remote agent metadata 持久化到 session sidecar，確保 `--resume` 後能恢復：
```typescript
writeRemoteAgentMetadata(taskId, meta)
deleteRemoteAgentMetadata(taskId)       // 完成/kill 時清除
listRemoteAgentMetadata()               // restore 時重建
```

Poll 機制：`pollRemoteSessionEvents()`（via teleport API）

---

## 3. InProcessTeammateTask（同進程 teammate）

**檔案**：`src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`、`types.ts`

### 狀態結構

```typescript
type InProcessTeammateTaskState = TaskStateBase & {
  type: 'in_process_teammate'
  identity: TeammateIdentity      // agentId, agentName, teamName, color, planModeRequired
  prompt: string
  model?: string
  selectedAgent?: AgentDefinition
  abortController?: AbortController     // 整個 teammate
  currentWorkAbortController?: AbortController  // 只中止當前 turn
  unregisterCleanup?: () => void
  awaitingPlanApproval: boolean
  permissionMode: PermissionMode        // 可獨立切換（Shift+Tab）
  error?: string
  result?: AgentToolResult
  progress?: AgentProgress
  messages?: Message[]                  // UI 鏡像，有上限
  inProgressToolUseIDs?: Set<string>
  pendingUserMessages: string[]         // 使用者直接輸入的訊息佇列
  spinnerVerb?: string                  // 動畫顯示文字（穩定跨 re-render）
  pastTenseVerb?: string
  isIdle: boolean
  shutdownRequested: boolean
  onIdleCallbacks?: Array<() => void>   // leader 等待 idle 的 callback
  lastReportedToolCount: number
  lastReportedTokenCount: number
}
```

### 記憶體上限設計

```typescript
// 重要：AppState 中的 messages 只存 50 條（UI 顯示用）
// 完整 conversation 在 inProcessRunner 的 allMessages 和磁碟 transcript 中
export const TEAMMATE_MESSAGES_UI_CAP = 50
```

設計原因（程式碼 comment 中有詳細說明）：
> BQ analysis (round 9, 2026-03-20) showed ~20MB RSS per agent at 500+ turn sessions and ~125MB per concurrent agent in swarm bursts. Whale session 9a990de8 launched 292 agents in 2 minutes and reached 36.8GB.

`appendCappedMessage()` 確保陣列不超過 50 條，超過時從最舊的刪除。

### 生命週期事件

```typescript
// 使用者查看 teammate transcript 時注入訊息
injectUserMessageToTeammate(taskId, message, setAppState)
// → 加入 pendingUserMessages（agent 下個 turn 會讀取）
// → 同時加到 messages（立即顯示在 UI）

// Teammate 完成工作，等待新任務
isIdle: true  // 設置後通知 onIdleCallbacks

// 請求優雅關閉
requestTeammateShutdown(taskId, setAppState)
// → shutdownRequested: true（agent 下個 turn 結束時發現並停止）
```

### 雙 AbortController 設計原因

| Controller | 作用 | 觸發時機 |
|------------|------|----------|
| `abortController` | 整個 teammate 的生命週期 | kill()、session 關閉 |
| `currentWorkAbortController` | 只中止當前 turn | 使用者在 transcript view 中要求停止當前工作 |

這允許「中止現在這個 turn，但 teammate 保持存活繼續接收新任務」。

---

## 4. DreamTask（記憶鞏固 agent）

**檔案**：`src/tasks/DreamTask/DreamTask.ts`

### 設計目的

Dream task 是將 auto-dream（記憶鞏固 subagent）的執行可見化的 UI 機制。Dream agent 本身未改變，只是添加了 task registration 讓它顯示在 footer pill 和 Shift+Down dialog 中。

### 狀態結構

```typescript
type DreamTaskState = TaskStateBase & {
  type: 'dream'
  phase: DreamPhase               // 'starting' | 'updating'
  sessionsReviewing: number
  filesTouched: string[]          // 不完整！只捕捉 Edit/Write tool_use，不含 bash 寫入
  turns: DreamTurn[]              // 最多保留 30 turns（MAX_TURNS）
  abortController?: AbortController
  priorMtime: number              // 用於 kill 時回滾 consolidation lock
}

type DreamTurn = {
  text: string
  toolUseCount: number
}

type DreamPhase = 'starting' | 'updating'
// 'updating' = 偵測到第一個 Edit/Write tool_use 後切換
```

### 四階段 Dream 結構（程式碼 comment）

Dream prompt 有 4 個內部階段（orient / gather / consolidate / prune），但 DreamTask 不解析這些 phase——只追蹤 'starting' → 'updating' 的轉換點。

### Kill 特殊邏輯

```typescript
async kill(taskId, setAppState) {
  // 1. 中止 dream agent
  task.abortController?.abort()
  // 2. 回滾 consolidation lock 的 mtime
  //    讓下次 session 可以重試（與 fork-failure 相同路徑）
  if (priorMtime !== undefined) {
    await rollbackConsolidationLock(priorMtime)
  }
}
```

### 完成通知策略

```typescript
completeDreamTask(taskId, setAppState)
// notified: true 立即設置（不走 XML notification 路徑）
// 因為 dream 是 UI-only，沒有 model-facing notification path
// 完成訊息透過 appendSystemMessage 顯示
```

---

## Task 系統通用基礎（TaskStateBase）

```typescript
type TaskStateBase = {
  id: string           // generateTaskId() 生成
  type: string
  status: TaskStatus   // 'pending' | 'running' | 'completed' | 'failed' | 'killed'
  description: string
  startTime: number
  endTime?: number
  notified: boolean    // 防止重複通知
  toolUseId?: string   // 關聯的 AgentTool tool_use ID（用於 agent result 對應）
}
```

## Task 狀態機

```
pending ──→ running ──→ completed
                    ──→ failed
                    ──→ killed
```

`isTerminalTaskStatus(status)` = `completed | failed | killed`

## GC 策略彙總

| Task 類型 | GC 觸發條件 |
|---------|------------|
| LocalAgentTask | `evictAfter` 到期 + `retain === false` |
| InProcessTeammateTask | `evictTerminalTask(STOPPED_DISPLAY_MS)` |
| DreamTask | `notified: true` + terminal status |
| RemoteAgentTask | `deleteRemoteAgentMetadata()` + terminal |
