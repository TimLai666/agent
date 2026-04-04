# 04 — Agent 通訊工具 Prompt 集

> 涵蓋：AgentTool、SendMessageTool、ToolSearchTool、EnterWorktreeTool、ExitWorktreeTool

---

## 1. AgentTool（Agent）

**檔案**：`src/tools/AgentTool/prompt.ts`（287 行）
> 完整 prompt 原文已在 02-core-tool-prompts.md 中詳述，此處補充通訊相關邏輯。

### 與其他 Agent 通訊的關鍵設計

**AgentTool 呼叫 agent 後如何繼續通訊：**

```
- To continue a previously spawned agent, use SendMessage with the agent's ID or name as the `to`
  field. The agent resumes with its full context preserved.
- Each Agent invocation starts fresh — provide a complete task description.
```

**Fork 模式下的通訊規則：**

```
Don't peek. The tool result includes an `output_file` path — do not Read or tail it unless the
user explicitly asks for a progress check. You get a completion notification; trust it.

Don't race. After launching, you know nothing about what the fork found. Never fabricate or predict
fork results in any format.
```

**Coordinator 模式精簡 prompt：**
coordinator 只收到 `shared` 基礎段（agent 列表 + 基本說明），所有 whenNotToUse/examples/writing 指引都省略。這表明 coordinator 已有自己的 system prompt。

---

## 2. SendMessageTool（SendMessage）

**檔案**：`src/tools/SendMessageTool/prompt.ts`（49 行）

### Prompt 原文（`getPrompt()`）

```
# SendMessage

Send a message to another agent.

{"to": "researcher", "summary": "assign task 1", "message": "start on task #1"}

| `to`                      |                                                              |
|---------------------------|--------------------------------------------------------------|
| `"researcher"`            | Teammate by name                                            |
| `"*"`                     | Broadcast to all teammates — expensive (linear in team size),
                             use only when everyone genuinely needs it              |
| `"uds:/path/to.sock"`     | Local Claude session's socket (same machine; use ListPeers) |
  [UDS_INBOX feature only]
| `"bridge:session_01AbCd"` | Remote Control peer session (cross-machine; use ListPeers)  |
  [UDS_INBOX feature only]

Your plain text output is NOT visible to other agents — to communicate, you MUST call this tool.
Messages from teammates are delivered automatically; you don't check an inbox.
Refer to teammates by name, never by UUID.
When relaying, don't quote the original — it's already rendered to the user.

## Cross-session [UDS_INBOX feature only]

Use `ListPeers` to discover targets, then:
{"to": "uds:/tmp/cc-socks/1234.sock", "message": "check if tests pass over there"}
{"to": "bridge:session_01AbCd...", "message": "what branch are you on?"}

A listed peer is alive and will process your message — no "busy" state; messages enqueue and drain
at the receiver's next tool round. Your message arrives wrapped as `<cross-session-message from="...">`.
To reply to an incoming message, copy its `from` attribute as your `to`.

## Protocol responses (legacy)

If you receive a JSON message with `type: "shutdown_request"` or `type: "plan_approval_request"`,
respond with the matching `_response` type — echo the `request_id`, set `approve` true/false:

{"to": "team-lead", "message": {"type": "shutdown_response", "request_id": "...", "approve": true}}
{"to": "researcher", "message": {"type": "plan_approval_response", "request_id": "...",
  "approve": false, "feedback": "add error handling"}}

Approving shutdown terminates your process. Rejecting plan sends the teammate back to revise.
Don't originate `shutdown_request` unless asked. Don't send structured JSON status messages — use TaskUpdate.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 名稱優先 | 永遠用名字（如 "researcher"），從不用 UUID |
| 廣播警告 | `"*"` 的複雜度是 O(n)，限最必要時 |
| 三層通訊範圍 | 隊友名 → UDS socket（同機）→ bridge（跨機）|
| 自動送達 | 訊息由系統自動推送，不需 polling |
| 禁止 JSON 狀態訊息 | `{"type":"idle",...}` 這類訊息禁止——用 TaskUpdate |
| shutdown 協議 | shutdown_request/response 是最後的特殊 JSON 例外 |

---

## 3. ToolSearchTool（ToolSearch）

**檔案**：`src/tools/ToolSearchTool/prompt.ts`（121 行）

### Prompt 原文（`getPrompt()`）

```
Fetches full schema definitions for deferred tools so they can be called.

Deferred tools appear by name in <system-reminder> messages.
[OR: <available-deferred-tools> messages — pre-gate behavior]

Until fetched, only the name is known — there is no parameter schema, so the tool cannot be invoked.
This tool takes a query, matches it against the deferred tool list, and returns the matched tools'
complete JSONSchema definitions inside a <functions> block. Once a tool's schema appears in that
result, it is callable exactly like any tool defined at the top of the prompt.

Result format: each matched tool appears as one <function>{"description": "...", "name": "...",
"parameters": {...}}</function> line inside the <functions> block — the same encoding as the tool
list at the top of this prompt.

Query forms:
- "select:Read,Edit,Grep" — fetch these exact tools by name
- "notebook jupyter" — keyword search, up to max_results best matches
- "+slack send" — require "slack" in the name, rank by remaining terms
```

### defer 判斷邏輯（`isDeferredTool()` 函數）

```typescript
function isDeferredTool(tool: Tool): boolean {
  // 1. alwaysLoad=true → 永不 defer（MCP 工具可選擇此項）
  if (tool.alwaysLoad === true) return false

  // 2. MCP 工具 → 永遠 defer
  if (tool.isMcp === true) return true

  // 3. ToolSearch 自身 → 永不 defer（需要它來載入其他工具）
  if (tool.name === TOOL_SEARCH_TOOL_NAME) return false

  // 4. FORK_SUBAGENT 模式下 AgentTool → 不 defer
  if (feature('FORK_SUBAGENT') && tool.name === AGENT_TOOL_NAME) {
    if (m.isForkSubagentEnabled()) return false
  }

  // 5. BriefTool（KAIROS/KAIROS_BRIEF feature）→ 不 defer
  if (tool.name === BRIEF_TOOL_NAME) return false

  // 6. SendUserFileTool（KAIROS + ReplBridge active）→ 不 defer
  if (tool.name === SEND_USER_FILE_TOOL_NAME && isReplBridgeActive()) return false

  // 7. tool.shouldDefer === true → defer
  return tool.shouldDefer === true
}
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 延遲載入目的 | MCP 工具依工作流決定，不應全數放進初始 prompt（cache bust 問題）|
| 位置判斷切換 | `tengu_glacier_2xr` feature flag 切換 system-reminder vs available-deferred-tools |
| 自保護邏輯 | ToolSearch 自身永遠在初始 prompt，確保模型隨時能用它載入其他工具 |
| BriefTool 豁免 | BriefTool 是主要通訊管道，不能讓模型第一次才透過 ToolSearch 才能溝通 |
| 三種查詢格式 | select（精確）/ 關鍵字（模糊）/ +prefix（名稱必要）|

---

## 4. EnterWorktreeTool（EnterWorktree）

**檔案**：`src/tools/EnterWorktreeTool/prompt.ts`（30 行）

### Prompt 原文（`getEnterWorktreeToolPrompt()`）

```
Use this tool ONLY when the user explicitly asks to work in a worktree. This tool creates an isolated
git worktree and switches the current session into it.

## When to Use

- The user explicitly says "worktree" (e.g., "start a worktree", "work in a worktree",
  "create a worktree", "use a worktree")

## When NOT to Use

- The user asks to create a branch, switch branches, or work on a different branch — use git commands
  instead
- The user asks to fix a bug or work on a feature — use normal git workflow unless they specifically
  mention worktrees
- Never use this tool unless the user explicitly mentions "worktree"

## Requirements

- Must be in a git repository, OR have WorktreeCreate/WorktreeRemove hooks configured in settings.json
- Must not already be in a worktree

## Behavior

- In a git repository: creates a new git worktree inside `.claude/worktrees/` with a new branch based
  on HEAD
- Outside a git repository: delegates to WorktreeCreate/WorktreeRemove hooks for VCS-agnostic isolation
- Switches the session's working directory to the new worktree
- Use ExitWorktree to leave the worktree mid-session (keep or remove)
- On session exit, if still in the worktree, the user will be prompted to keep or remove it

## Parameters

- `name` (optional): A name for the worktree. If not provided, a random name is generated.
```

---

## 5. ExitWorktreeTool（ExitWorktree）

**檔案**：`src/tools/ExitWorktreeTool/prompt.ts`（32 行）

### Prompt 原文（`getExitWorktreeToolPrompt()`）

```
Exit a worktree session created by EnterWorktree and return the session to the original working
directory.

## Scope

This tool ONLY operates on worktrees created by EnterWorktree in this session. It will NOT touch:
- Worktrees you created manually with `git worktree add`
- Worktrees from a previous session (even if created by EnterWorktree then)
- The directory you're in if EnterWorktree was never called

If called outside an EnterWorktree session, the tool is a no-op: it reports that no worktree
session is active and takes no action. Filesystem state is unchanged.

## When to Use

- The user explicitly asks to "exit the worktree", "leave the worktree", "go back"
- Do NOT call this proactively — only when the user asks

## Parameters

- `action` (required): `"keep"` or `"remove"`
  - `"keep"` — leave the worktree directory and branch intact on disk.
    Use this if the user wants to come back to the work later, or if there are changes to preserve.
  - `"remove"` — delete the worktree directory and its branch.
    Use this for a clean exit when the work is done or abandoned.
- `discard_changes` (optional, default false): only meaningful with `action: "remove"`.
  If the worktree has uncommitted files or commits not on the original branch, the tool will REFUSE
  to remove it unless this is set to `true`. If the tool returns an error listing changes, confirm
  with the user before re-invoking with `discard_changes: true`.

## Behavior

- Restores the session's working directory to where it was before EnterWorktree
- Clears CWD-dependent caches (system prompt sections, memory files, plans directory)
- If a tmux session was attached to the worktree: killed on `remove`, left running on `keep`
- Once exited, EnterWorktree can be called again to create a fresh worktree
```

### Worktree 工具對比

| 維度 | EnterWorktree | ExitWorktree |
|---|---|---|
| 觸發條件 | 使用者明確說 "worktree" | 使用者明確說「離開 worktree」|
| 作用範圍 | 當前 session，git repo 或 hook | 本 session 建立的 worktree 才有效 |
| 安全保護 | 不可在 worktree 中再次呼叫 | 未提交變更 + action=remove → 需 `discard_changes: true` |
| 清理行為 | 建立 `.claude/worktrees/` 下的目錄 | 可 keep（保留）或 remove（刪除）|
| 快取更新 | 切換 cwd 觸發重新計算 | 恢復 cwd，清除 cwd 相關快取 |

---

## Agent 通訊完整流程圖

```
使用者對話
    │
    ▼
Agent 工具呼叫
├── subagent_type 指定 → 全新 context，需完整 briefing
└── omit (fork mode) → 繼承當前 context

agent 執行中
    │
    ├── SendMessage → 隊友（by name）
    │     ├── 廣播 "*"（expensive）
    │     ├── UDS socket（同機）[UDS_INBOX feature]
    │     └── bridge（跨機）[UDS_INBOX feature]
    │
    └── ToolSearch → 載入 deferred 工具的 schema
          ├── MCP tools（全部 defer）
          ├── shouldDefer=true tools
          └── 查詢方式：select / 關鍵字 / +prefix

agent 完成
    └── 自動通知 coordinator（用戶角色訊息）
         └── coordinator 不得預測/偽造結果
```
