# 05 — Swarm/Teammate 多 Agent 協作機制

## 概覽

Swarm 系統是 Claude Code 的多 agent 協作框架，允許一個「Team Lead」（Leader）協調多個「Teammates」並行執行任務。核心在 `src/utils/swarm/` 目錄（14 個檔案）。

## Swarm 架構圖

```
Team Leader
(CLAUDE_CODE_AGENT_NAME 未設定 or = 'team-lead')
    │
    ├─── TeamCreateTool → 建立 team config.json
    │    ~/.claude/teams/{teamName}/config.json
    │
    ├─── SendMessageTool → 寫入 teammate mailbox
    │    ~/.claude/teams/{teamName}/mailbox/{name}/
    │
    └─── 每個 Teammate：
         ┌─────────────────────────────────────┐
         │ Pane-based (tmux/iTerm2)            │
         │ - 獨立 OS process                   │
         │ - CLAUDE_CODE_AGENT_NAME=name        │
         │ - CLAUDE_CODE_TEAM_NAME=team         │
         │ - 透過 mailbox 通訊                  │
         └─────────────────────────────────────┘
         ┌─────────────────────────────────────┐
         │ In-process (AsyncLocalStorage)      │
         │ - 同 Node.js process                │
         │ - runWithTeammateContext() 隔離      │
         │ - 直接記憶體 mailbox                 │
         └─────────────────────────────────────┘
```

## 核心資料結構

### TeamFile（`~/.claude/teams/{teamName}/config.json`）

```typescript
type TeamFile = {
  name: string
  description?: string
  createdAt: number
  leadAgentId: string
  leadSessionId?: string         // Leader 的 session UUID（用於 peer 發現）
  hiddenPaneIds?: string[]       // 當前被隱藏的 UI pane IDs
  teamAllowedPaths?: TeamAllowedPath[]  // 全 team 共用的允許路徑
  members: Array<{
    agentId: string              // 格式：{name}@{team}
    name: string
    agentType?: string
    model?: string
    prompt?: string
    color?: string
    planModeRequired?: boolean
    joinedAt: number
    tmuxPaneId: string
    cwd: string
    worktreePath?: string
    sessionId?: string           // Teammate 的 session UUID
    subscriptions: string[]
    backendType?: BackendType    // 'tmux' | 'iterm2' | 'in_process'
    isActive?: boolean           // false=idle, undefined/true=active
    mode?: PermissionMode        // 權限模式（可獨立循環切換）
  }>
}
```

### AgentId 格式

```typescript
// formatAgentId(name, teamName) → "researcher@my-team"
const agentId = `${sanitizeAgentName(name)}@${sanitizeName(teamName)}`
```

`sanitizeName()` 將所有非字母數字字元替換為 `-` 並小寫。
`sanitizeAgentName()` 只替換 `@` 為 `-`（防止 agentName@teamName 格式模糊）。

### TeammateIdentity（InProcessTeammateTask 內）

```typescript
type TeammateIdentity = {
  agentId: string         // "researcher@my-team"
  agentName: string       // "researcher"
  teamName: string
  color?: string
  planModeRequired: boolean
  parentSessionId: string // Leader 的 session ID（transcript 關聯）
}
```

## In-Process Teammate 啟動流程

### 1. spawnInProcessTeammate()

```typescript
async function spawnInProcessTeammate(
  config: InProcessSpawnConfig,
  context: SpawnContext
): Promise<InProcessSpawnOutput>
```

步驟：
1. `formatAgentId(name, teamName)` → 生成 deterministic agentId
2. `generateTaskId('in_process_teammate')` → 生成 taskId
3. `createAbortController()` → 獨立 controller（不繼承 leader abort）
4. `createTeammateContext(...)` → AsyncLocalStorage context
5. 可選：`registerPerfettoAgent()` → Perfetto 追蹤階層視覺化
6. 組裝 `InProcessTeammateTaskState`：
   - `permissionMode: planModeRequired ? 'plan' : 'default'`
   - `spinnerVerb: sample(getSpinnerVerbs())`
   - `pastTenseVerb: sample(TURN_COMPLETION_VERBS)`
7. `registerCleanup()` → graceful shutdown handler
8. `registerTask(taskState, setAppState)`

### 2. runWithTeammateContext()

AsyncLocalStorage 的包裝器，確保每個 in-process teammate 的執行 context 互相隔離，可以讀取 `getTeammateContext()` 取得自身的 identity 而不互相污染。

### 3. InProcessRunner 執行迴圈

`inProcessRunner.ts` 包裝 `runAgent()`，提供：
- AsyncLocalStorage context 隔離
- 進度追蹤與 AppState 更新
- Idle 通知給 leader（完成時）
- Plan mode 審批流程支援
- 自動 compact（達到 threshold 時壓縮 context）

## Pane-based Teammate 啟動流程

環境變數傳遞（spawn 時設定在子 process env）：
```
CLAUDE_CODE_AGENT_NAME=researcher
CLAUDE_CODE_TEAM_NAME=my-team
CLAUDE_CODE_AGENT_ID=researcher@my-team
CLAUDE_CODE_AGENT_COLOR=blue
CLAUDE_CODE_PLAN_MODE_REQUIRED=true
```

`teammateInit.ts` 在 pane-based teammate 啟動時：
1. 讀取 team file，取得 leader ID
2. 套用 `teamAllowedPaths`（team 共用允許路徑）
3. 向 setAppState 注入 permission rules
4. 注冊 Stop hook → 在 session 停止時通知 leader（idle notification）

## Mailbox 通訊系統

### 設計哲學

Mailbox 是 Swarm 的核心通訊機制，取代直接 IPC：
- **非同步**：寫入信箱後不阻塞，接收方下次 poll 時處理
- **持久化**：基於檔案系統（pane-based）或記憶體（in-process）
- **方向性**：每個 agent 有自己的信箱，以 name 定址

### 訊息類型

| 訊息類型 | 發送方 | 接收方 | 用途 |
|---------|--------|--------|------|
| idle notification | Teammate | Leader | 完成工作，等待新任務 |
| permission_request | Worker | Leader | 需要工具使用權限審批 |
| permission_response | Leader | Worker | 批准/拒絕工具使用 |
| sandbox_permission_request | Worker | Leader | 沙箱網路存取請求 |
| sandbox_permission_response | Leader | Worker | 沙箱網路決策 |
| shutdown_request | Leader | Teammate | 請求 teammate 關閉 |
| plan_approval_request | Teammate | Leader | Plan mode 審批請求 |
| 一般 DM | 任意 | 任意 | 業務訊息協調 |

### 權限同步（permissionSync.ts）

Worker 需要執行敏感工具時的完整流程：

```
Worker                    Leader
  │                         │
  ├─── writePermissionRequest() ──→ ~/.claude/teams/{team}/permissions/pending/{id}.json
  │    同時 sendPermissionRequestViaMailbox() → leader mailbox
  │                         │
  │                         ├─ leader poll mailbox，偵測到 permission_request
  │                         ├─ 顯示給使用者（ToolUseConfirm dialog）
  │                         ├─ 使用者批准/拒絕
  │                         ├─ resolvePermission() → resolved/{id}.json
  │                         └─ sendPermissionResponseViaMailbox() → worker mailbox
  │                         │
  ├─── pollForResponse(requestId) ← ~/.claude/teams/{team}/permissions/resolved/{id}.json
  ├─── 取得 decision: 'approved' | 'denied'
  └─── 繼續或放棄工具使用
```

檔案鎖定（lockfile）保障並發安全。

### Leader Permission Bridge（leaderPermissionBridge.ts）

In-process teammate 的權限請求直接走記憶體 bridge，不走檔案：

```typescript
// REPL 啟動時注冊
registerLeaderToolUseConfirmQueue(setter)
registerLeaderSetToolPermissionContext(setter)

// In-process runner 執行時取得
const queue = getLeaderToolUseConfirmQueue()
// 直接呼叫 setToolUseConfirmQueue → 觸發 leader 的 UI
```

## Teammate System Prompt Addendum

所有 teammate（pane-based 和 in-process）都會附加：

```typescript
export const TEAMMATE_SYSTEM_PROMPT_ADDENDUM = `
# Agent Teammate Communication

IMPORTANT: You are running as an agent in a team. To communicate with anyone on your team:
- Use the SendMessage tool with \`to: "<name>"\` to send messages to specific teammates
- Use the SendMessage tool with \`to: "*"\` sparingly for team-wide broadcasts

Just writing a response in text is not visible to others on your team - you MUST use the SendMessage tool.

The user interacts primarily with the team lead. Your work is coordinated through the task system
and teammate messaging.
`
```

## Session 清理機制

### cleanupSessionTeams()

Session 結束時（gracefulShutdown）自動清理：

```
1. 讀取 sessionCreatedTeams（bootstrap/state.ts 中的 Set）
2. killOrphanedTeammatePanes()：
   - 讀取 team config，找到所有 pane-based members
   - 動態 import backend registry（避免循環依賴）
   - 呼叫 backend.killPane()
3. cleanupTeamDirectories()：
   - 讀取 worktreePaths，呼叫 destroyWorktree()
   - rm -rf team directory（~/.claude/teams/{name}/）
   - rm -rf tasks directory（~/.claude/tasks/{name}/）
```

`destroyWorktree()` 先嘗試 `git worktree remove --force`，失敗則 `rm -rf`。

## 成員狀態追蹤

```typescript
// 標記 teammate 為 idle（在 Stop hook 中呼叫）
void setMemberActive(teamName, agentName, false)

// 標記 teammate 為 active（開始新 turn 時）
void setMemberActive(teamName, agentName, true)
```

Leader 可透過 team config 的 `isActive` 欄位即時監控所有 teammate 的忙閒狀態。

## 環境常量

```typescript
TEAM_LEAD_NAME = 'team-lead'    // Leader 角色名稱
SWARM_SESSION_NAME = 'claude-swarm'  // tmux session 名
TEAMMATE_COMMAND_ENV_VAR = 'CLAUDE_CODE_TEAMMATE_COMMAND'  // spawn 命令覆蓋
TEAMMATE_COLOR_ENV_VAR = 'CLAUDE_CODE_AGENT_COLOR'
PLAN_MODE_REQUIRED_ENV_VAR = 'CLAUDE_CODE_PLAN_MODE_REQUIRED'
```

`getSwarmSocketName()` = `claude-swarm-{PID}`（每個 Claude instance 獨立，防衝突）
