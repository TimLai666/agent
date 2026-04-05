# 06 — 入口點分析

來源：`src/entrypoints/cli.tsx`、`init.ts`、`mcp.ts`、`sdk/controlSchemas.ts`、`sdk/coreTypes.ts`

---

## 1. 入口點清單

| 檔案 | 用途 |
|---|---|
| `cli.tsx` | 主要 CLI 入口，處理所有命令列路徑 |
| `init.ts` | 共用初始化邏輯（memoized，所有入口共用） |
| `mcp.ts` | 以 MCP Server 模式啟動（對外暴露 Claude Code 工具） |
| `sdk/controlSchemas.ts` | SDK 控制協定的 Zod schema 定義 |
| `sdk/coreTypes.ts` | SDK 公開型別（generated） |
| `agentSdkTypes.ts` | Agent SDK 相關型別 |
| `sandboxTypes.ts` | 沙盒配置型別 |

---

## 2. `cli.tsx` — CLI 入口快速路徑設計

採用「Fast-path 優先」架構，每個特殊路徑在載入主要 React UI 前提前返回，最小化模組載入量：

### Fast-path 優先順序

```
1. --version / -v / -V           → 零模組載入，直接 console.log(MACRO.VERSION)
2. --dump-system-prompt          → ant-only，輸出 system prompt 後退出
3. --claude-in-chrome-mcp        → Chrome 原生 MCP server
4. --chrome-native-host          → Chrome 原生 host
5. --computer-use-mcp            → feature('CHICAGO_MCP')，電腦操控 MCP
6. --daemon-worker=<kind>        → feature('DAEMON')，worker process
7. remote-control / rc / bridge  → feature('BRIDGE_MODE')，遠端控制橋接
8. daemon                        → feature('DAEMON') 子命令
9. …（其他子命令）
10. 完整 REPL UI 載入             → 最後才 import React
```

### 特殊環境設定

```typescript
// 在任何 import 前設定（build-time dead code elimination 用）
process.env.COREPACK_ENABLE_AUTO_PIN = '0'

// CLAUDE_CODE_REMOTE=true 時擴大 V8 heap
if (process.env.CLAUDE_CODE_REMOTE === 'true') {
  process.env.NODE_OPTIONS = '--max-old-space-size=8192'
}

// ABLATION_BASELINE：harness-science L0 對照組
if (feature('ABLATION_BASELINE') && process.env.CLAUDE_CODE_ABLATION_BASELINE) {
  // 停用 thinking、compact、background tasks 等
}
```

---

## 3. `mcp.ts` — MCP Server 模式

Claude Code 可作為 MCP server 被其他工具呼叫：

```typescript
const server = new Server(
  { name: 'claude/tengu', version: MACRO.VERSION },
  { capabilities: { tools: {} } }
)
```

### 暴露的工具

MCP server 暴露所有 Claude Code 工具（透過 `getTools()`），加上 MCP_COMMANDS = `[review]`。

### 工具處理流程

```
ListTools → getTools() → zodToJsonSchema(inputSchema) + optional outputSchema
CallTool  → findToolByName → hasPermissionsToUseTool → tool.call() → stream → JSON
```

Output schema 限制：僅支援 `type: "object"` 根層級（不支援 anyOf/oneOf，避免 MCP SDK 相容性問題）。

### 快取大小限制

```typescript
// 避免無限記憶體增長
const READ_FILE_STATE_CACHE_SIZE = 100  // 100 個檔案，25MB 上限
```

---

## 4. SDK 控制協定

SDK 模式下（`clientType = 'sdk'`），CLI process 透過 stdin/stdout 的 JSON-Lines 協定與 SDK 通訊。

### 訊息方向

```
stdin  → CLI：SDKUserMessageSchema | SDKControlRequestSchema | SDKControlResponseSchema | keep_alive | update_environment_variables
stdout → SDK：SDKMessageSchema | SDKStreamlinedTextMessage | SDKPostTurnSummary | SDKControlResponse | SDKControlRequest | keep_alive
```

### 控制請求類型（SDKControlRequestInnerSchema）

| subtype | 說明 |
|---|---|
| `initialize` | 初始化 session（hooks、MCP servers、systemPrompt、agents） |
| `interrupt` | 中斷目前對話輪次 |
| `can_use_tool` | 請求工具使用許可 |
| `set_permission_mode` | 設定許可模式（default / plan / bypassPermissions） |
| `set_model` | 變更模型 |
| `set_max_thinking_tokens` | 設定 thinking 上限（nullable = 使用預設） |
| `mcp_status` | 查詢 MCP server 連線狀態 |
| `get_context_usage` | 查詢 context window 使用明細 |
| `hook_callback` | 傳遞 hook callback 結果 |
| `mcp_message` | 傳送 JSON-RPC 訊息給特定 MCP server |
| `rewind_files` | 回溯特定 user message 後的檔案變更 |
| `cancel_async_message` | 取消尚未執行的非同步訊息 |
| `seed_read_state` | 為快取 seed 一個已讀檔案狀態（用於 snip 後的 Edit 驗證） |
| `mcp_set_servers` | 替換動態管理的 MCP server 集合 |
| `reload_plugins` | 重新載入插件 |
| `mcp_reconnect` | 重連失敗的 MCP server |
| `mcp_toggle` | 啟用/停用 MCP server |
| `stop_task` | 停止執行中的 task |
| `apply_flag_settings` | 合併 flag settings 層的設定 |
| `get_settings` | 取得有效設定與各層原始設定 |
| `elicitation` | MCP elicitation（用戶輸入請求） |

### get_context_usage 回應結構

```typescript
{
  categories: [...],     // 各類別的 token 數與顏色
  totalTokens, maxTokens, percentage,
  gridRows: [...],       // 視覺化格子陣列
  model,
  memoryFiles: [...],    // CLAUDE.md 等記憶體檔案
  mcpTools: [...],       // MCP 工具 token 用量
  deferredBuiltinTools: [...],
  systemPromptSections: [...],
  agents: [...],
  slashCommands: {...},
  skills: {...},
  autoCompactThreshold?, isAutoCompactEnabled,
  messageBreakdown: { toolCallTokens, toolResultTokens, ... },
  apiUsage: { input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens }
}
```

---

## 5. Hook 事件系統

SDK 可在初始化時訂閱 Hook 事件：

```typescript
// HOOK_EVENTS（coreTypes.ts）
const HOOK_EVENTS = [
  'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
  'Notification', 'UserPromptSubmit',
  'SessionStart', 'SessionEnd', 'Stop', 'StopFailure',
  'SubagentStart', 'SubagentStop',
  'PreCompact', 'PostCompact',
  'PermissionRequest', 'PermissionDenied',
  'Setup', 'TeammateIdle',
  'TaskCreated', 'TaskCompleted',
  'Elicitation', 'ElicitationResult',
  'ConfigChange', 'WorktreeCreate', 'WorktreeRemove',
  'InstructionsLoaded', 'CwdChanged', 'FileChanged',
]
```

---

## 6. Exit Reasons

```typescript
const EXIT_REASONS = [
  'clear', 'resume', 'logout',
  'prompt_input_exit', 'other',
  'bypass_permissions_disabled',
]
```

---

## 7. `agentSdkTypes.ts`

定義 `HookEvent`、`ModelUsage` 等 Agent SDK 對外型別，被 `bootstrap/state.ts` 引用（作為 `modelUsage` 欄位型別），因此必須是 bootstrap 的葉節點（不得循環引用）。
