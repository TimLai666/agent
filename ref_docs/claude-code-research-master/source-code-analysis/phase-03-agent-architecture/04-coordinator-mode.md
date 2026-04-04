# 04 — Coordinator Mode 完整逆向

## 概覽

Coordinator Mode 是 Claude Code 的「指揮官模式」，將主 agent 角色從「直接執行者」轉換為「調度協調者」。核心實作在 `src/coordinator/coordinatorMode.ts`（369 行）。

## 啟動條件

```typescript
export function isCoordinatorMode(): boolean {
  if (feature('COORDINATOR_MODE')) {
    return isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE)
  }
  return false
}
```

- 需要 `bun:bundle` feature flag `COORDINATOR_MODE` 開啟
- 且 `CLAUDE_CODE_COORDINATOR_MODE=1`

### Session 模式匹配

```typescript
export function matchSessionMode(
  sessionMode: 'coordinator' | 'normal' | undefined
): string | undefined
```

Resume session 時，若 session 記錄的 mode 與當前環境不符，自動翻轉 env var 保持一致，並回傳警告訊息。

## Coordinator System Prompt 完整分析

### 角色定義（Section 1: Your Role）
```
You are Claude Code, an AI assistant that orchestrates software engineering tasks across
multiple workers.

- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user
- Answer questions directly when possible — don't delegate work that you can handle without tools

Every message you send is to the user. Worker results and system notifications are internal
signals, not conversation partners — never thank or acknowledge them.
```

關鍵行為：
- **不回應 worker 通知**（never thank or acknowledge them）
- **不委派能自己回答的問題**
- 只有三個核心工具：Agent、SendMessage、TaskStop

### 工具說明（Section 2: Your Tools）
```
- AgentTool        - Spawn a new worker
- SendMessageTool  - Continue an existing worker
- TaskStopTool     - Stop a running worker
- subscribe_pr_activity / unsubscribe_pr_activity - GitHub PR 事件訂閱
```

注意事項：
- 不要用一個 worker 去查看另一個 worker
- Workers 完成後會自動通知
- 不設定 `model` 參數（workers 需要預設模型）
- 啟動後**立即結束回應**，不預測結果

### Worker Result 格式（task-notification）
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

識別方式：user-role 訊息以 `<task-notification>` 開頭。`<task-id>` 即為 SendMessage 的 `to` 欄位。

### Task Workflow（Section 4）

**工作流程四階段**：

| 階段 | 執行者 | 目的 |
|------|--------|------|
| Research | Workers（並行） | 探索 codebase、找檔案、理解問題 |
| Synthesis | **Coordinator** | 讀取發現、理解問題、撰寫實作規格 |
| Implementation | Workers | 依規格修改、commit |
| Verification | Workers | 測試變更 |

**並行策略**：
- Read-only 任務（research）→ 自由並行
- Write-heavy 任務（implementation）→ 同一組檔案一次一個
- Verification 可與不同檔案的 implementation 並行

**實際驗證定義**：
- 不只是「測試通過」
- 要以 feature 啟用的狀態執行測試
- 要調查 typecheck 錯誤，不輕易說「不相關」
- 獨立測試，不橡皮圖章

### Worker 失敗處理
- 優先用 SendMessageTool 繼續同一個 worker（有完整錯誤 context）
- 若第二次嘗試失敗，換方向或回報給使用者

### TaskStop 使用場景
```typescript
// 當方向錯誤時停止 worker
TaskStopTool({ task_id: "agent-x7q" })
// 再繼續（worker 有 context，可以接受修正指令）
SendMessageTool({ to: "agent-x7q", message: "Stop the JWT refactor. Instead, fix the null pointer..." })
```

### Synthesis（最重要的工作）（Section 5）

**核心原則**：Coordinator 必須自己理解 research 結果，再組裝精確規格。

禁止：
```typescript
// 不好 - 委派理解給 worker
Agent({ prompt: "Based on your findings, fix the auth bug" })
Agent({ prompt: "The worker found an issue in the auth module. Please fix it." })
```

要求：
```typescript
// 好 - 包含具體資訊（檔案路徑、行號、預期修改）
Agent({ prompt: "Fix the null pointer in src/auth/validate.ts:42. The user field on Session is undefined when sessions expire but the token remains cached. Add a null check before user.id access — if null, return 401 with 'Session expired'. Commit and report the hash." })
```

**繼續（Continue）vs 重新派生（Spawn Fresh）決策矩陣**：

| 情況 | 機制 | 原因 |
|------|------|------|
| Research 探索了需要編輯的檔案 | Continue（SendMessage） | Worker 已有那些檔案在 context |
| Research 寬泛但 implementation 窄 | Spawn Fresh | 避免帶入探索雜訊 |
| 修正失敗或繼續近期工作 | Continue | Worker 有錯誤 context |
| 驗證另一個 worker 剛寫的程式碼 | Spawn Fresh | Verifier 應有新鮮視角 |
| 第一次嘗試用了完全錯誤的方法 | Spawn Fresh | 錯誤 context 會污染重試 |
| 完全不相關的任務 | Spawn Fresh | 無可重用 context |

**Purpose statement 要求**：
```
"This research will inform a PR description — focus on user-facing changes."
"I need this to plan an implementation — report file paths, line numbers, and type signatures."
"This is a quick check before we merge — just verify the happy path."
```

### Worker Context 說明（getCoordinatorUserContext）

```typescript
export function getCoordinatorUserContext(
  mcpClients: ReadonlyArray<{ name: string }>,
  scratchpadDir?: string,
): { [k: string]: string }
```

回傳注入到使用者 context 的動態內容（`workerToolsContext`）：
1. Workers 可用的工具清單（依 `CLAUDE_CODE_SIMPLE` 決定精簡或完整工具集）
2. MCP tools from 連接的 MCP servers
3. Scratchpad 目錄說明（若 `tengu_scratch` feature gate 啟用）

**Scratchpad 機制**：
```
Scratchpad directory: {scratchpadDir}
Workers can read and write here without permission prompts. Use this for durable cross-worker
knowledge — structure files however fits the work.
```

### AgentTool Prompt 在 Coordinator 模式的差異

```typescript
if (isCoordinator) {
  return shared  // 只回傳精簡版（無 when-not-to-use, 無 usage notes, 無 examples）
}
```

Coordinator 只拿到 `shared` 核心部分，因為 system prompt 已包含完整用法說明，避免重複。

## 完整 Coordinator System Prompt 架構

```
Section 1: Your Role
  - 定義 coordinator 與 worker 的邊界
  - 禁止回應 worker notification

Section 2: Your Tools
  - AgentTool 使用規則
  - task-notification XML 格式說明
  - 範例 session

Section 3: Workers
  - worker subagent_type
  - worker 能力（工具集）

Section 4: Task Workflow
  - 四階段流程
  - 並行策略
  - 驗證定義
  - 失敗處理
  - TaskStop 使用

Section 5: Writing Worker Prompts
  - Synthesis 原則（最重要）
  - Continue vs Spawn Fresh 決策
  - Continue 機制
  - Prompt 技巧與範例

Section 6: Example Session（完整對話示範）
```

## Internal Worker Tools

```typescript
const INTERNAL_WORKER_TOOLS = new Set([
  TEAM_CREATE_TOOL_NAME,
  TEAM_DELETE_TOOL_NAME,
  SEND_MESSAGE_TOOL_NAME,
  SYNTHETIC_OUTPUT_TOOL_NAME,
])
```

這些工具從 `ASYNC_AGENT_ALLOWED_TOOLS` 中篩除，不暴露給 workers 的工具清單描述。
