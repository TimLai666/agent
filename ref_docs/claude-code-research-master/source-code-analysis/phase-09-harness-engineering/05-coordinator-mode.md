# 05 — Coordinator 模式運作機制

## 概述

Coordinator 模式是 Claude Code 的多 Agent 協調系統。在此模式下，主要的 Claude 實例扮演「協調者」角色，它不直接執行工具（如 Bash、FileEdit），而是透過 `Agent` 工具派遣「工作者（worker）」執行實際任務，然後綜合結果。

---

## 1. 啟動與偵測

```typescript
// src/coordinator/coordinatorMode.ts (line 36)
export function isCoordinatorMode(): boolean {
  if (feature('COORDINATOR_MODE')) {
    return isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE)
  }
  return false
}
```

**啟動方式：**
- 環境變數 `CLAUDE_CODE_COORDINATOR_MODE=1`
- 功能旗標 `COORDINATOR_MODE` 必須開啟（bun:bundle feature gate）

---

## 2. Session Resume 模式對齊

當 resume 一個舊的 session 時，系統會自動對齊 coordinator 狀態：

```typescript
// src/coordinator/coordinatorMode.ts (line 49)
export function matchSessionMode(
  sessionMode: 'coordinator' | 'normal' | undefined,
): string | undefined {
  const currentIsCoordinator = isCoordinatorMode()
  const sessionIsCoordinator = sessionMode === 'coordinator'

  if (currentIsCoordinator !== sessionIsCoordinator) {
    // 直接修改 env var（isCoordinatorMode() live 讀取，無快取）
    if (sessionIsCoordinator) {
      process.env.CLAUDE_CODE_COORDINATOR_MODE = '1'
    } else {
      delete process.env.CLAUDE_CODE_COORDINATOR_MODE
    }
    logEvent('tengu_coordinator_mode_switched', { to: sessionMode })
  }
}
```

---

## 3. Coordinator 的 System Prompt

這是最關鍵的部分。`getCoordinatorSystemPrompt()` 生成了一份完整的多 Agent 指揮手冊：

```typescript
// src/coordinator/coordinatorMode.ts (line 111)
export function getCoordinatorSystemPrompt(): string {
  return `You are Claude Code, an AI assistant that orchestrates software engineering tasks across multiple workers.

## 1. Your Role
You are a coordinator. Your job is to:
- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user
- Answer questions directly when possible — don't delegate work that you can handle without tools

## 2. Your Tools
- **Agent** - Spawn a new worker
- **SendMessage** - Continue an existing worker
- **TaskStop** - Stop a running worker
- subscribe_pr_activity / unsubscribe_pr_activity (if available)

## 4. Task Workflow

| Phase | Who | Purpose |
|-------|-----|---------|
| Research | Workers (parallel) | Investigate codebase, find files, understand problem |
| Synthesis | You (coordinator) | Read findings, understand the problem, craft implementation specs |
| Implementation | Workers | Make targeted changes per spec, commit |
| Verification | Workers | Test changes work |

## Concurrency
Parallelism is your superpower. Workers are async. Launch independent workers concurrently...`
}
```

**Coordinator System Prompt 的完整結構：**
1. 角色定義（coordinator vs. worker）
2. 工具清單（Agent, SendMessage, TaskStop, PR 訂閱）
3. Worker 結果格式（`<task-notification>` XML）
4. 任務工作流（Research → Synthesis → Implementation → Verification）
5. Worker prompt 撰寫指南
6. Continue vs. Spawn 決策矩陣
7. 完整範例對話

---

## 4. Worker 可用工具清單

```typescript
// src/coordinator/coordinatorMode.ts (line 29)
const INTERNAL_WORKER_TOOLS = new Set([
  TEAM_CREATE_TOOL_NAME,
  TEAM_DELETE_TOOL_NAME,
  SEND_MESSAGE_TOOL_NAME,
  SYNTHETIC_OUTPUT_TOOL_NAME,
])

// Worker 工具（排除 coordinator 內部工具）
const workerTools = Array.from(ASYNC_AGENT_ALLOWED_TOOLS)
  .filter(name => !INTERNAL_WORKER_TOOLS.has(name))
  .sort()
  .join(', ')

// Simple 模式（CLAUDE_CODE_SIMPLE=1）
const simpleWorkerTools = [BASH_TOOL_NAME, FILE_READ_TOOL_NAME, FILE_EDIT_TOOL_NAME].sort().join(', ')
```

---

## 5. User Context 注入

Coordinator 模式下，會向使用者 context 注入關於 worker 能力的說明：

```typescript
// src/coordinator/coordinatorMode.ts (line 80)
export function getCoordinatorUserContext(
  mcpClients: ReadonlyArray<{ name: string }>,
  scratchpadDir?: string,
): { [k: string]: string } {
  let content = `Workers spawned via the Agent tool have access to these tools: ${workerTools}`

  if (mcpClients.length > 0) {
    content += `\n\nWorkers also have access to MCP tools from connected MCP servers: ${serverNames}`
  }

  if (scratchpadDir && isScratchpadGateEnabled()) {
    content += `\n\nScratchpad directory: ${scratchpadDir}\nWorkers can read and write here without permission prompts.`
  }

  return { workerToolsContext: content }
}
```

---

## 6. Worker 結果傳遞格式

Worker 完成後，結果以 `<task-notification>` XML 格式作為 user 訊息傳回 coordinator：

```xml
<task-notification>
<task-id>{agentId}</task-id>
<status>completed|failed|killed</status>
<summary>{human-readable status summary}</summary>
<result>{agent's final text response}</result>
<usage>
  <total_tokens>N</total_tokens>
  <tool_uses>N</tool_uses>
  <duration_ms>N</duration_ms>
</usage>
</task-notification>
```

**重要設計**：Worker 結果作為 user-role message 傳入 coordinator 的 context，但 coordinator 被指示「這不是真正的使用者訊息」，需要透過 `<task-notification>` tag 識別。

---

## 7. 並行策略指引

Coordinator 的 system prompt 明確定義了並行策略：

```
並行度管理：
- Read-only 任務（research）→ 自由並行
- Write-heavy 任務（implementation）→ 每組檔案同一時間只有一個 worker
- Verification → 有時可與 implementation 並行（不同檔案區域）
```

**工具層面實作**：多個 Agent 工具呼叫可在同一個 message 中發出，由 toolOrchestration.ts 的並行執行引擎處理。

---

## 8. Continue vs. Spawn 決策矩陣

```
情境                              → 決策       理由
───────────────────────────────────────────────────────────────
Research 正好探索了要編輯的檔案    → Continue   Worker 已有檔案 context
Research 範圍廣但 impl 範圍窄     → Spawn      避免拖帶不相關 context
修正失敗或延伸近期工作             → Continue   Worker 有錯誤 context
驗證另一個 worker 寫的程式碼       → Spawn      驗證者應以新鮮視角看程式碼
整個錯誤做法                      → Spawn      錯誤 context 污染重試
完全無關的任務                    → Spawn      沒有可重用的 context
```

---

## 9. 反模式清單（來自 System Prompt）

Coordinator 被明確指示避免：

```
// 懶惰委派（bad）
Agent({ prompt: "Based on your findings, fix the auth bug" })

// 良好的合成規格（good）
Agent({ prompt: "Fix the null pointer in src/auth/validate.ts:42. The user field on Session (src/auth/types.ts:15) is undefined when sessions expire... Add a null check before user.id access — if null, return 401 with 'Session expired'. Commit and report the hash." })
```

---

## 10. Coordinator 模式架構圖

```
┌─────────────────────────────────────────────────────────────┐
│                    COORDINATOR MODE                         │
│                                                             │
│  User                                                       │
│   │                                                         │
│   ▼                                                         │
│  ┌────────────────────────────────────────┐                │
│  │  Coordinator (main Claude instance)    │                │
│  │  System Prompt: coordinator role       │                │
│  │  Tools: Agent, SendMessage, TaskStop   │                │
│  └──────────┬──────────────┬─────────────┘                │
│             │              │                                │
│     Agent() │              │ SendMessage()                  │
│             │              │                                │
│    ┌────────▼────────┐  ┌──▼──────────────┐               │
│    │  Worker A       │  │  Worker B        │               │
│    │  (Research)     │  │  (Research)      │               │
│    │  Tools: all     │  │  Tools: all      │               │
│    └────────┬────────┘  └──┬──────────────┘               │
│             │              │                                │
│    <task-notification>  <task-notification>                │
│             │              │                                │
│    ┌────────▼──────────────▼────────────┐                 │
│    │  Coordinator synthesizes findings  │                 │
│    │  → crafts implementation spec      │                 │
│    └────────────────┬───────────────────┘                 │
│                     │                                       │
│             SendMessage() ←→ continue worker               │
│                     │                                       │
│    ┌────────────────▼───────────────────┐                 │
│    │  Worker A (now: Implementation)    │                 │
│    │  Fix null pointer at validate.ts:42│                 │
│    └────────────────┬───────────────────┘                 │
│                     │                                       │
│    <task-notification> completed                           │
│                     │                                       │
│  ┌──────────────────▼───────────────────┐                │
│  │  Coordinator reports to user         │                │
│  └──────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

---

## 11. Scratchpad 整合

當 `tengu_scratch` feature gate 開啟且提供 scratchpadDir 時：

```
Workers 可以在 scratchpad 目錄中讀寫，無需權限確認。
用途：cross-worker 共享知識（如 research findings、中間結果）
結構：worker 自行決定檔案組織方式
```

這使得複雜的 multi-worker 任務可以透過檔案系統進行協調，而不只是透過 coordinator 的 context。
