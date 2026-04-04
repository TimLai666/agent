# 03 — Agent 生命週期分析

## 生命週期全圖

```
Spawn 階段
┌────────────────────────────────────────────────────────┐
│ 1. AgentTool 被呼叫（含 subagent_type / prompt）        │
│ 2. loadAgentsDir → 解析 AgentDefinition                │
│ 3. 決定執行策略：                                       │
│    - local（預設）→ LocalAgentTask                      │
│    - isolation: worktree → 建立 git worktree            │
│    - isolation: remote → RemoteAgentTask (CCR)         │
│    - run_in_background: true → 背景執行                 │
│ 4. generateTaskId → registerTask(setAppState)           │
│ 5. createAbortController（獨立，不繼承父 abort）         │
│ 6. 啟動 AgentSummary 定時器（每 30s）                   │
└────────────────────────────────────────────────────────┘
                           │
Execute 階段
┌────────────────────────────────────────────────────────┐
│ runAgent() 核心迴圈                                     │
│ ┌──────────────────────────────────────────────────┐  │
│ │ 1. 組裝 system prompt（getSystemPrompt + 環境資訊） │  │
│ │ 2. 呼叫 Claude API（含工具定義）                    │  │
│ │ 3. 處理 assistant message：                        │  │
│ │    - text → 記錄 transcript                        │  │
│ │    - tool_use → 執行工具，canUseTool 檢查           │  │
│ │ 4. drainPendingMessages（SendMessage 注入的訊息）    │  │
│ │ 5. 更新 ProgressTracker（token count, tool count） │  │
│ │ 6. updateAgentSummary（每 30s fork）               │  │
│ │ 7. 重複直到 stop_reason = end_turn 或 abort        │  │
│ └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
                           │
Return 階段
┌────────────────────────────────────────────────────────┐
│ 1. agent 回傳最後一條文字訊息作為 result                │
│ 2. enqueueAgentNotification → 組裝 <task-notification> │
│ 3. enqueuePendingNotification → 注入主 session 訊息佇列 │
│ 4. updateTaskState → status: 'completed'               │
│ 5. AgentSummary timer stop()                           │
│ 6. evictTaskOutput / evictTerminalTask（延遲 GC）       │
└────────────────────────────────────────────────────────┘
```

## Spawn 詳解

### AgentTool 參數
```typescript
{
  subagent_type?: string      // 指定 built-in 或自訂 agent，省略 = fork/general
  prompt: string              // 任務描述（完整自包含）
  description?: string        // 3-5 字簡述（UI 顯示用）
  name?: string               // 識別名稱（fork 模式用）
  model?: string              // 模型覆蓋（coordinator 不建議設定）
  isolation?: 'worktree' | 'remote'
  run_in_background?: boolean
  team_name?: string          // teammate 模式
  mode?: string               // 權限模式
}
```

### Task ID 生成
```typescript
generateTaskId('local_agent')   // → "local_agent-{timestamp}-{random}"
generateTaskId('dream')         // → "dream-{timestamp}-{random}"
generateTaskId('in_process_teammate') // → "in_process_teammate-{timestamp}-{random}"
```

### AbortController 策略
- LocalAgentTask：每個 agent 獨立 AbortController，不繼承父 session 的 abort
- InProcessTeammateTask：有兩個 controller：
  - `abortController`：整個 teammate 的 abort（kill 整個 teammate）
  - `currentWorkAbortController`：只中止當前 turn（不殺死 teammate）

## Execute 詳解

### ProgressTracker（進度追蹤）
定義於 `LocalAgentTask.tsx`：
```typescript
type ProgressTracker = {
  toolUseCount: number
  latestInputTokens: number      // Claude API input 是累計的，取最新值
  cumulativeOutputTokens: number // output 是每 turn 的，累加
  recentActivities: ToolActivity[] // 最近 5 個工具活動
}
```

`getTokenCountFromTracker()` = `latestInputTokens + cumulativeOutputTokens`

### AgentProgress（UI 顯示狀態）
```typescript
type AgentProgress = {
  toolUseCount: number
  tokenCount: number
  lastActivity?: ToolActivity
  recentActivities?: ToolActivity[]
  summary?: string  // 由 AgentSummary 服務填充
}
```

### 訊息接收（drainPendingMessages）
執行迴圈每個 tool round 邊界呼叫 `drainPendingMessages()`：
- 拉出 `task.pendingMessages` 陣列
- 清空 state 中的佇列
- 注入為 user 訊息繼續 API 呼叫

這是 SendMessageTool 的底層機制：SendMessage → `queuePendingMessage()` → 下個 round 由 `drainPendingMessages()` 消費。

### LocalAgentTask 狀態欄位
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
  messages?: Message[]           // 最新訊息（UI 顯示用）
  lastReportedToolCount: number
  lastReportedTokenCount: number
  isBackgrounded: boolean        // false=前景, true=背景
  pendingMessages: string[]      // SendMessage 注入的訊息佇列
  retain: boolean                // UI 是否正在查看此 task（阻止 GC）
  diskLoaded: boolean            // 是否已從磁碟載入 transcript
  evictAfter?: number            // 到期時間（terminal 後）
}
```

## Return 詳解

### task-notification XML 格式
```xml
<task-notification>
  <task-id>{agentId}</task-id>
  <status>completed|failed|killed</status>
  <summary>{human-readable status}</summary>
  <result>{agent's final text response}</result>
  <output_file>{disk output path}</output_file>
  <worktree>{worktree info if applicable}</worktree>
  <worktree-branch>{branch name}</worktree-branch>
  <usage>
    <total_tokens>N</total_tokens>
    <tool_uses>N</tool_uses>
    <duration_ms>N</duration_ms>
  </usage>
  <tool-use-id>{toolUseId}</tool-use-id>
</task-notification>
```

### 通知去重機制
`enqueueAgentNotification()` 使用原子性 `notified` flag：
```typescript
// 在 updateTaskState 回調中原子檢查並設置 notified
// 若已 notified（例如 TaskStopTool 搶先設置），則跳過通知
if (task.notified) return task
shouldEnqueue = true
return { ...task, notified: true }
```

### 生命週期狀態機
```
pending → running → completed
                 → failed
                 → killed
```

`isTerminalTaskStatus()` 判斷是否為終止狀態。

### 記憶體回收（GC）策略
- `evictAfter`：terminal 狀態後設定到期時間
- `evictTerminalTask(taskId, setAppState, STOPPED_DISPLAY_MS)`：延遲後從 AppState 移除
- `evictTaskOutput(taskId)`：清理磁碟輸出檔案
- `retain: true`：UI 正在查看時阻止 GC（`enterTeammateView` 設置）
- `diskLoaded: true`：一次性 flag，transcript 已從磁碟 bootstrap 到記憶體

## 前景 vs 背景 生命週期差異

| 面向 | 前景（foreground） | 背景（background） |
|------|-------------------|-------------------|
| `isBackgrounded` | false | true |
| Coordinator 行為 | 等待結果再繼續 | 繼續其他工作 |
| 通知時機 | 同步回傳 | `<task-notification>` as user message |
| UI 顯示 | 主流程 | background tasks indicator pill |
| 何時切換 | N/A | `run_in_background: true` 或 `background: true` agent |
