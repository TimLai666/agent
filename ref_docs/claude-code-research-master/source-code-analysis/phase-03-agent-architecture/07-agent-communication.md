# 07 — Agent 間通訊

## 通訊機制全景

Claude Code 的 agent 間通訊包含三個層次：

```
┌─────────────────────────────────────────────────────────┐
│ 層次 1：Coordinator ↔ Subagent                          │
│   task-notification XML（user-role 訊息）                │
│   AgentTool + SendMessageTool（coordinator 視角）        │
├─────────────────────────────────────────────────────────┤
│ 層次 2：Teammate ↔ Teammate（Swarm）                     │
│   Mailbox 系統（file-based 或 in-process 記憶體）         │
│   SendMessageTool（to: "researcher" 等）                 │
├─────────────────────────────────────────────────────────┤
│ 層次 3：Background Summary                              │
│   AgentSummary（每 30s forked agent 生成進度摘要）        │
└─────────────────────────────────────────────────────────┘
```

---

## SendMessageTool

**檔案**：`src/tools/SendMessageTool/prompt.ts`

### 完整 Prompt

```
# SendMessage

Send a message to another agent.

{"to": "researcher", "summary": "assign task 1", "message": "start on task #1"}

| `to` | |
|---|---|
| `"researcher"` | Teammate by name |
| `"*"` | Broadcast to all teammates — expensive (linear in team size), use only when
          everyone genuinely needs it |
| `"uds:/path/to.sock"` | Local Claude session's socket (same machine; use `ListPeers`) |
| `"bridge:session_..."` | Remote Control peer session (cross-machine; use `ListPeers`) |

Your plain text output is NOT visible to other agents — to communicate, you MUST call this tool.
Messages from teammates are delivered automatically; you don't check an inbox. Refer to teammates
by name, never by UUID. When relaying, don't quote the original — it's already rendered to the user.

## Cross-session (UDS_INBOX feature)

Use `ListPeers` to discover targets, then:
{"to": "uds:/tmp/cc-socks/1234.sock", "message": "check if tests pass over there"}
{"to": "bridge:session_01AbCd...", "message": "what branch are you on?"}

A listed peer is alive and will process your message — no "busy" state; messages enqueue and
drain at the receiver's next tool round. Your message arrives wrapped as
<cross-session-message from="...">.  To reply to an incoming message, copy its `from` attribute
as your `to`.

## Protocol responses (legacy)

If you receive a JSON message with `type: "shutdown_request"` or `type: "plan_approval_request"`,
respond with the matching `_response` type — echo the `request_id`, set `approve` true/false:

{"to": "team-lead", "message": {"type": "shutdown_response", "request_id": "...", "approve": true}}
{"to": "researcher", "message": {"type": "plan_approval_response", "request_id": "...", "approve": false, "feedback": "add error handling"}}

Approving shutdown terminates your process. Rejecting plan sends the teammate back to revise.
Don't originate `shutdown_request` unless asked. Don't send structured JSON status messages —
use TaskUpdate.
```

### SendMessage 的兩種用途

**用途 1：Coordinator 繼續 subagent**
```typescript
// Coordinator 用 task-notification 中的 task-id 繼續 worker
SendMessageTool({ to: "agent-a1b", message: "Fix the null pointer in validate.ts:42..." })
```
- `to` = agentId（來自 `<task-id>` tag）
- Worker 的 `pendingMessages` 佇列被填充
- 下個 tool round 邊界 `drainPendingMessages()` 消費

**用途 2：Teammate 間直接通訊（Swarm）**
```typescript
// Teammate 發訊息給 leader 或其他 teammate
SendMessageTool({ to: "team-lead", message: "Research complete. Found 3 files." })
SendMessageTool({ to: "*", message: "Starting PR creation phase" })  // broadcast（謹慎使用）
```
- `to` = teammate name（非 UUID）
- 透過 mailbox 系統路由

### Protocol Messages（結構化 JSON）

```typescript
// Shutdown 流程
{ type: "shutdown_request", request_id: "xxx" }     // leader → teammate
{ type: "shutdown_response", request_id: "xxx", approve: true }  // teammate → leader

// Plan mode 審批流程
{ type: "plan_approval_request", request_id: "xxx", plan: "..." }  // teammate → leader
{ type: "plan_approval_response", request_id: "xxx", approve: false, feedback: "..." }  // leader → teammate
```

### Cross-session 通訊（UDS_INBOX feature flag）

當 `feature('UDS_INBOX')` 啟用：
- `ListPeers`：發現同機器或跨機器的 Claude session
- `uds:/path/to.sock`：同機器 Unix Domain Socket
- `bridge:session_xxx`：Remote Control peer（跨機器）
- 訊息以 `<cross-session-message from="...">` 包裝送到

---

## AgentSummary 服務

**檔案**：`src/services/AgentSummary/agentSummary.ts`

### 設計目標

為 Coordinator 模式的 subagent 提供定期（每 30 秒）的進度摘要，顯示在 UI 的 task panel 中，讓使用者了解 agent 目前在做什麼，而不需要深入查看完整 transcript。

### 核心架構

```typescript
export function startAgentSummarization(
  taskId: string,
  agentId: AgentId,
  cacheSafeParams: CacheSafeParams,
  setAppState: TaskContext['setAppState'],
): { stop: () => void }
```

**返回值**：`{ stop: () => void }` — 在 agent 完成時呼叫以停止定時器。

### 執行流程

```
scheduleNext() → setTimeout(runSummary, 30_000)
                    │
                    ▼ (每 30s)
                runSummary()
                    │
                    ├─ getAgentTranscript(agentId)  // 讀取 agent 的 transcript
                    ├─ filterIncompleteToolCalls()  // 清理未完成的 tool call
                    ├─ 構建 forkParams（含當前 messages）
                    ├─ runForkedAgent({
                    │    promptMessages: [buildSummaryPrompt(previousSummary)],
                    │    cacheSafeParams: forkParams,
                    │    canUseTool: async () => deny,  // fork 不能使用工具
                    │    querySource: 'agent_summary',
                    │    skipTranscript: true,
                    │  })
                    ├─ 提取 text block（3-5 個字的進度描述）
                    ├─ updateAgentSummary(taskId, summaryText, setAppState)
                    └─ scheduleNext()  // 完成後（不是開始後）再排下一個
```

### Summary Prompt

```
Describe your most recent action in 3-5 words using present tense (-ing). Name the file or
function, not the branch. Do not use tools.

{如果有 previousSummary}: Previous: "{previousSummary}" — say something NEW.

Good: "Reading runAgent.ts"
Good: "Fixing null check in validate.ts"
Good: "Running auth module tests"
Good: "Adding retry logic to fetchUser"

Bad (past tense): "Analyzed the branch diff"
Bad (too vague): "Investigating the issue"
Bad (too long): "Reviewing full branch diff and AgentTool.tsx integration"
Bad (branch name): "Analyzed adam/background-summary branch diff"
```

### Cache 最佳化設計

**關鍵設計**：Summary fork 刻意使用與主 agent 相同的 cache params，共享 prompt cache，降低成本。

```typescript
// 從 CacheSafeParams 中丟掉 forkContextMessages（closure 避免 pin 舊訊息）
const { forkContextMessages: _drop, ...baseParams } = cacheSafeParams

// 每次 tick 從 transcript 重建最新 messages
const forkParams: CacheSafeParams = {
  ...baseParams,
  forkContextMessages: cleanMessages,  // 當前 agent 的最新訊息
}
```

**不設定 maxOutputTokens**（關鍵 comment）：
> DO NOT set maxOutputTokens here. The fork piggybacks on the main thread's prompt cache by sending identical cache-key params (system, tools, model, messages prefix, thinking config). Setting maxOutputTokens would clamp budget_tokens, creating a thinking config mismatch that invalidates the cache.

**工具拒絕策略**：
```typescript
// 透過 canUseTool callback 拒絕工具，而不是設定 tools:[]
// 若設定 tools:[] 會改變 cache key（工具清單不同），bust cache
const canUseTool = async () => ({
  behavior: 'deny' as const,
  message: 'No tools needed for summary',
  decisionReason: { type: 'other', reason: 'summary only' },
})
```

### 防重疊機制

- timer 在 `runSummary()` **完成後**（finally block）才排下一個
- 若前一個 summary 還在執行，`stopped` flag 會阻止新的開始
- `AbortController` 確保 agent 完成時能立即取消進行中的 summary request

### 最小訊息數要求

```typescript
if (!transcript || transcript.messages.length < 3) {
  // Not enough context yet — skip this tick
  return
}
```

---

## task-notification 通訊協議

這是 Coordinator 模式的核心通訊協議，將 subagent 結果以 user-role 訊息的形式送達 coordinator。

### 完整 XML Schema

```xml
<task-notification>
  <task-id>{agentId}</task-id>
  <status>completed|failed|killed</status>
  <summary>{human-readable status summary}</summary>
  <result>{agent's final text response}</result>          <!-- optional -->
  <output_file>{disk output path}</output_file>           <!-- optional -->
  <worktree>{worktree info}</worktree>                   <!-- optional -->
  <worktree-branch>{branch name}</worktree-branch>        <!-- optional -->
  <usage>                                                 <!-- optional -->
    <total_tokens>N</total_tokens>
    <tool_uses>N</tool_uses>
    <duration_ms>N</duration_ms>
  </usage>
  <tool-use-id>{toolUseId}</tool-use-id>                  <!-- optional -->
</task-notification>
```

### 識別機制

Coordinator system prompt 明確說明：
> Worker results arrive as **user-role messages** containing `<task-notification>` XML. They look like user messages but are not. Distinguish them by the `<task-notification>` opening tag.

### 通知組裝（enqueueAgentNotification）

```typescript
// 原子 notified check（防止 TaskStopTool 與 completion 雙重通知）
updateTaskState<LocalAgentTaskState>(taskId, setAppState, task => {
  if (task.notified) return task   // 已通知，跳過
  shouldEnqueue = true
  return { ...task, notified: true }
})
if (!shouldEnqueue) return

// 組裝 XML 並放入主 session 訊息佇列
const notificationXml = buildTaskNotificationXml({ ... })
enqueuePendingNotification(notificationXml)
```

---

## 通訊方向彙總

| 方向 | 機制 | 格式 |
|------|------|------|
| Coordinator → Worker（新任務） | AgentTool | prompt 參數 |
| Worker → Coordinator（完成回報） | task-notification | XML user-role 訊息 |
| Coordinator → Worker（繼續） | SendMessageTool | text message → pendingMessages |
| Coordinator → Worker（停止） | TaskStopTool | task_id |
| Teammate → Teammate（協調） | SendMessageTool | text 或 JSON 協議訊息 |
| Worker → Leader（權限請求） | permissionSync | file/mailbox JSON |
| Leader → Worker（權限回應） | permissionSync | file/mailbox JSON |
| Agent（背景） → UI | AgentSummary | 3-5 字描述字串 |
| In-process → Leader（權限） | leaderPermissionBridge | 記憶體 function call |
