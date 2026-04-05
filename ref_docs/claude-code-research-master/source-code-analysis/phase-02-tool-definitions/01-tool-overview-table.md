# 01 — 36 個工具總覽表

> 來源：src/tools/*/prompt.ts、src/constants/tools.ts

---

## 工具分類說明

| 分類代碼 | 說明 |
|---|---|
| SHELL | Shell 執行工具 |
| FILE | 檔案讀寫操作 |
| SEARCH | 搜尋工具 |
| AGENT | Agent 管理與通訊 |
| TASK | 任務追蹤管理 |
| PLAN | 規劃模式工具 |
| TEAM | 多 Agent 團隊管理 |
| WEB | 網路存取 |
| MCP | MCP 協議整合 |
| CONFIG | 設定管理 |
| SYSTEM | 系統級工具 |
| NB | Notebook |

---

## 36 個工具完整清單

| # | 工具名稱（常數名） | prompt.ts 行數 | 用途分類 | 安全限制摘要 |
|---|---|---|---|---|
| 1 | `Bash` (BashTool) | 369 | SHELL | 沙箱模式控制（filesystem read/write 限制、network allowlist）；Git Safety Protocol；禁止 `find/grep/cat` 等命令改用專用工具；`dangerouslyDisableSandbox` 需明確授權 |
| 2 | `Agent` (AgentTool) | 287 | AGENT | 非 ant 使用者預設禁用 AgentTool 遞迴（防止無限嵌套）；coordinator 模式只允許 AGENT/TASK_STOP/SEND_MESSAGE/SYNTHETIC_OUTPUT 四工具 |
| 3 | `Skill` (SkillTool) | 241 | SYSTEM | 已執行中的 Skill 不可重複呼叫；非 built-in CLI 命令才可用；budget 預算限制（context window 1%） |
| 4 | `TodoWrite` (TodoWriteTool) | 184 | TASK | 最多一個任務同時 in_progress；未完成任務不得標為 completed；無測試/部分實作時禁止 completed |
| 5 | `EnterPlanMode` (EnterPlanModeTool) | 170 | PLAN | 需要使用者明確同意才可進入計畫模式；簡單任務禁止使用 |
| 6 | `PowerShell` (PowerShellTool) | 145 | SHELL | 禁止互動命令（Read-Host/Out-GridView）；版本相關語法差異（PS 5.1 vs 7+）；同 Bash 一樣禁止用 PS 做檔案操作 |
| 7 | `CronCreate/CronDelete/CronList` (ScheduleCronTool) | 135 | SYSTEM | 預設 session-only（非持久化）；durable 模式需使用者明確要求；任務最長 `DEFAULT_MAX_AGE_DAYS` 天自動過期；GrowthBook kill switch |
| 8 | `ToolSearch` (ToolSearchTool) | 121 | SYSTEM | ToolSearch 自身永不 defer；MCP 工具皆為 defer；FORK_SUBAGENT 模式下 Agent 不 defer |
| 9 | `TeamCreate` (TeamCreateTool) | 113 | TEAM | 僅讀取 agent 不可執行寫入任務；工作流程嚴格依 team/task 架構 |
| 10 | `Config` (ConfigTool) | 93 | CONFIG | 只能修改 SUPPORTED_SETTINGS 中列出的設定；全域設定存 `~/.claude.json`，專案設定存 `settings.json` |
| 11 | `TaskUpdate` (TaskUpdateTool) | 77 | TASK | 只能更新 pending→in_progress→completed；標記 completed 前需 TaskGet 確認最新狀態；測試失敗禁止 completed |
| 12 | `TaskCreate` (TaskCreateTool) | 56 | TASK | 任務初始為 pending 無 owner；多人環境需提供足夠 description 讓其他 agent 理解 |
| 13 | `SendMessage` (SendMessageTool) | 49 | AGENT | 廣播（`"*"`）代價高昂；plain text 輸出對其他 agent 不可見，必須用此工具；不可發送 JSON 結構狀態訊息 |
| 14 | `Read` (FileReadTool) | 49 | FILE | 只讀不改；路徑需為絕對路徑；空目錄不可讀；大 PDF 需分頁（最多 20 頁/次） |
| 15 | `TaskList` (TaskListTool) | 49 | TASK | 無安全限制；只讀取任務清單 |
| 16 | `WebFetch` (WebFetchTool) | 46 | WEB | HTTP 自動升 HTTPS；有 15 分鐘快取；GitHub URL 改用 gh CLI；有 pre-approved domain 判斷引用長度限制 |
| 17 | `AskUserQuestion` (AskUserQuestionTool) | 44 | PLAN | 計畫模式下不可詢問「計畫是否可以」改用 ExitPlanMode；不可在 UI 顯示計畫前 reference「the plan」 |
| 18 | `WebSearch` (WebSearchTool) | 34 | WEB | 僅限 US；每次回應必須附 Sources section；使用當前年份搜尋 |
| 19 | `ExitWorktree` (ExitWorktreeTool) | 32 | SYSTEM | 只作用於本 session EnterWorktree 建立的 worktree；若有未提交變更且 action=remove 需 `discard_changes: true` |
| 20 | `EnterWorktree` (EnterWorktreeTool) | 30 | SYSTEM | 只在使用者明確說 "worktree" 時使用；需 git repo 或 WorktreeCreate hook；已在 worktree 中不可再次呼叫 |
| 21 | `ExitPlanMode` (ExitPlanModeTool) | 29 | PLAN | v2 版需先寫 plan file，此工具只是信號；研究類任務不應使用 |
| 22 | `Edit` (FileEditTool) | 28 | FILE | 必須在本對話中先 Read 過才能 Edit；old_string 需唯一；行號前綴不可含入字串 |
| 23 | `TaskGet` (TaskGetTool) | 24 | TASK | 開始工作前必須驗證 blockedBy 為空 |
| 24 | `SendUserMessage/Brief` (BriefTool) | 22 | AGENT | 使用者實際讀取的唯一管道；每次回應都必須透過此工具；`status` 需如實設定 |
| 25 | `LSP` (LSPTool) | 21 | SEARCH | 需 LSP server 已設定；操作需 filePath/line/character（1-based）|
| 26 | `ListMcpResources` (ListMcpResourcesTool) | 20 | MCP | 無安全限制；可按 server 篩選 |
| 27 | `Grep` (GrepTool) | 18 | SEARCH | 永遠優先於 bash grep/rg；開放式多輪搜尋改用 Agent tool |
| 28 | `Write` (FileWriteTool) | 18 | FILE | 覆蓋前必須先 Read；優先 Edit 而非 Write；禁止建立 *.md / README 除非明確要求 |
| 29 | `Sleep` (SleepTool) | 17 | SYSTEM | 每次喚醒消耗一次 API call；優先於 `Bash(sleep ...)`；可與其他工具並發 |
| 30 | `TeamDelete` (TeamDeleteTool) | 16 | TEAM | 必須先關閉所有 teammate 才可刪除；自動清理 team/task 目錄 |
| 31 | `ReadMcpResource` (ReadMcpResourceTool) | 16 | MCP | 需指定 server 名稱與資源 URI |
| 32 | `RemoteTrigger` (RemoteTriggerTool) | 15 | SYSTEM | OAuth token 自動注入不暴露；CRUD 操作對 claude.ai CCR API |
| 33 | `TaskStop` (TaskStopTool) | 8 | TASK | 按 task_id 停止後台任務；coordinator 模式可用 |
| 34 | `Glob` (GlobTool) | 7 | SEARCH | 按修改時間排序；開放式搜尋改用 Agent tool |
| 35 | `NotebookEdit` (NotebookEditTool) | 3 | NB | notebook_path 需絕對路徑；cell_number 從 0 開始 |
| 36 | `MCPTool` (MCPTool) | 3 | MCP | prompt/description 由 mcpClient.ts 動態覆蓋；本 prompt.ts 為空殼 |

---

## 工具允許集（依 constants/tools.ts）

### ALL_AGENT_DISALLOWED_TOOLS（子 Agent 禁用）
- TaskOutputTool
- ExitPlanModeTool
- EnterPlanModeTool
- AgentTool（非 ant 使用者）
- AskUserQuestionTool
- TaskStopTool
- WorkflowTool（WORKFLOW_SCRIPTS feature）

### ASYNC_AGENT_ALLOWED_TOOLS（非同步 Agent 可用）
Read, WebSearch, TodoWrite, Grep, WebFetch, Glob, Shell Tools, Edit, Write, NotebookEdit, Skill, SyntheticOutput, ToolSearch, EnterWorktree, ExitWorktree

### IN_PROCESS_TEAMMATE_ALLOWED_TOOLS（in-process 隊友額外工具）
TaskCreate, TaskGet, TaskList, TaskUpdate, SendMessage, CronCreate/Delete/List（AGENT_TRIGGERS feature）

### COORDINATOR_MODE_ALLOWED_TOOLS（協調者模式）
Agent, TaskStop, SendMessage, SyntheticOutput

---

## 工具結果大小限制（constants/toolLimits.ts）

| 常數 | 值 | 說明 |
|---|---|---|
| `DEFAULT_MAX_RESULT_SIZE_CHARS` | 50,000 chars | 超過則存檔，回傳 preview + 路徑 |
| `MAX_TOOL_RESULT_TOKENS` | 100,000 tokens | 系統上限（約 400KB） |
| `MAX_TOOL_RESULTS_PER_MESSAGE_CHARS` | 200,000 chars | 單次 user message 的所有 tool_result 合計上限 |
| `TOOL_SUMMARY_MAX_LENGTH` | 50 chars | compact view 截斷長度 |
