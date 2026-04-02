下面是可直接施工的 **Subagent 機制實作規格 v1**。我會用你前面提到的文件脈絡來整理成「主 agent + subagent + 通訊 + 任務系統」的落地設計，不講空話，直接給你可做的規格。

---

# Subagent 機制實作規格 v1

## 1. 目標

建立一套可讓主 agent 派生 subagent 的機制，支援：

1. 主 agent 派工給子 agent
2. 子 agent 背景執行
3. 主 agent 可繼續其他工作
4. 子 agent 完成後主動回報
5. 主 agent 可繼續對同一個子 agent 下指令
6. 主 agent 可停止子 agent
7. 支援兩種模式：

   * **spawn**：全新 context 的 subagent
   * **fork**：繼承父 agent context 的 subagent

---

## 2. 非目標

v1 先不做這些：

1. 真正分散式多機執行
2. 跨裝置 agent 同步
3. GUI 任務監控面板
4. 圖形化 team 編排器
5. 自動學習型 agent routing

---

## 3. 核心概念

### 3.1 角色

#### Main Agent / Coordinator

負責：

* 接收使用者需求
* 判斷是否要委派
* 建立 subagent 任務
* 綜整結果
* 回覆使用者

不負責：

* 長時間細部研究
* 大量獨立實作工作
* 自己假裝 subagent 的執行結果

#### Subagent / Worker

負責：

* 被派去執行單一任務
* 在自己的 context 內進行推理與工具操作
* 最後產生結論或修改結果
* 回報給 coordinator

---

## 4. 必要元件

整套系統至少要有這 7 個元件：

1. `AgentTool`
2. `SendMessageTool`
3. `TaskStopTool`
4. `Task Registry`
5. `Task Runner`
6. `Notification Queue`
7. `Context Builder`

---

## 5. 工具層規格

## 5.1 AgentTool

### 用途

建立新的 subagent 任務。

### 輸入參數

```ts
type AgentToolInput = {
  name?: string                // 任務簡短名稱，1~2字詞
  prompt: string               // 派工內容
  subagent_type?: string       // 若省略且允許 fork，代表 fork 自己
  run_in_background?: boolean  // 是否背景執行
  isolation?: "none" | "worktree" | "remote"
  model?: string               // v1 可選，fork 建議禁用
}
```

### 行為規格

#### A. spawn 模式

當 `subagent_type` 有值時：

* 建立新的乾淨 subagent context
* 只注入必要 briefing
* 不繼承完整父對話

#### B. fork 模式

當 `subagent_type` 省略且 fork 功能開啟時：

* 建立 fork subagent
* 繼承父 agent 的主要 context
* 共用 prompt cache
* 不可另外指定 model（避免 cache key 失配）

### 輸出

```ts
type AgentToolResult = {
  task_id: string
  status: "started" | "queued"
  name?: string
}
```

### 限制

1. 不得在同一任務中無限制遞迴呼叫 AgentTool
2. built-in subagent 預設可禁用再次派生
3. 不可在尚未完成的任務上重複 spawn 同性質 agent，除非明確允許並行

---

## 5.2 SendMessageTool

### 用途

對既有 subagent 繼續下指令。

### 輸入

```ts
type SendMessageToolInput = {
  to: string       // task_id 或 agent name
  message: string
}
```

### 行為

1. 找到對應 task
2. 將 message 放入該 task 的 `pendingMessages`
3. 若 task 正在等待新指令則喚醒
4. 若 task 已結束則回傳錯誤或拒絕

### 輸出

```ts
type SendMessageToolResult = {
  delivered: boolean
  task_id: string
}
```

---

## 5.3 TaskStopTool

### 用途

停止一個正在執行的 subagent。

### 輸入

```ts
type TaskStopToolInput = {
  task_id: string
}
```

### 行為

1. 將 task 狀態改為 `killing`
2. 發送取消訊號給 runner
3. 成功停止後狀態改為 `killed`
4. 若 task 已完成，不重複通知

### 輸出

```ts
type TaskStopToolResult = {
  stopped: boolean
  task_id: string
}
```

---

# 6. 任務系統規格

## 6.1 Task 型別

```ts
type TaskStatus =
  | "queued"
  | "running"
  | "waiting_message"
  | "completed"
  | "failed"
  | "killing"
  | "killed"

type TaskIsolation = "none" | "worktree" | "remote"

type TaskMode = "spawn" | "fork"

interface BaseTask {
  id: string
  name?: string
  createdAt: number
  updatedAt: number
  status: TaskStatus
  mode: TaskMode
  isolation: TaskIsolation
  parentTaskId?: string
  coordinatorSessionId: string
  runInBackground: boolean
  prompt: string
  pendingMessages: string[]
  result?: string
  summary?: string
  outputFile?: string
  error?: string
  notified: boolean
  toolUseCount: number
  totalTokens?: number
  durationMs?: number
}
```

---

## 6.2 LocalAgentTaskState

本地 subagent 任務：

```ts
interface LocalAgentTaskState extends BaseTask {
  type: "local_agent"
  subagentType?: string
  worktreePath?: string
  worktreeBranch?: string
}
```

---

## 6.3 RemoteAgentTaskState

遠端環境用：

```ts
interface RemoteAgentTaskState extends BaseTask {
  type: "remote_agent"
  remoteEnvId: string
}
```

---

## 6.4 InProcessTeammateTaskState

同進程 teammate：

```ts
interface InProcessTeammateTaskState extends BaseTask {
  type: "inprocess_teammate"
  teammateName: string
}
```

---

# 7. Task Registry 規格

## 7.1 職責

`TaskRegistry` 是整個 subagent 系統的狀態中心，負責：

1. 註冊 task
2. 查詢 task
3. 更新 task 狀態
4. 管理 task 與 coordinator 的對應
5. 防止重複通知

## 7.2 必要 API

```ts
interface TaskRegistry {
  createTask(task: BaseTask): void
  getTask(taskId: string): BaseTask | undefined
  listTasksBySession(sessionId: string): BaseTask[]
  updateTask(taskId: string, updater: (task: BaseTask) => BaseTask): void
  findTaskByName(sessionId: string, name: string): BaseTask | undefined
}
```

## 7.3 原子更新要求

所有狀態更新必須是原子的，避免：

1. TaskStop 與完成通知同時發生
2. 多次 enqueue 相同 notification
3. 多個 SendMessage 競態覆蓋

---

# 8. Context Builder 規格

## 8.1 目的

建立 subagent 啟動時的輸入 context。

---

## 8.2 Spawn Context 規則

spawn 時只注入：

1. 任務 prompt
2. 必要系統 prompt
3. 可用工具列表
4. 使用者目標摘要
5. scratchpad 路徑資訊（若有）

不要直接丟整份父對話。

### 組裝結果

```ts
type SpawnContext = {
  systemPrompt: string
  taskPrompt: string
  toolsContext: string
  userGoalSummary: string
  scratchpadDir?: string
}
```

---

## 8.3 Fork Context 規則

fork 時注入：

1. 父 agent 目前的 message prefix
2. 相同 system prompt
3. 相同工具 schema
4. 相同 model 設定
5. 相同 thinking config

目的是讓 prompt cache 可重用。

### 注意

fork 不要隨便改：

* model
* system prompt
* max output tokens
* tools schema 順序

不然 cache key 會炸掉。

---

# 9. Subagent 執行器規格

## 9.1 Task Runner 職責

`runAgentTask(taskId)` 要負責：

1. 讀取 task 狀態
2. 建立 agent 執行 context
3. 啟動 LLM loop
4. 收集工具使用資訊
5. 處理中斷
6. 任務完成後送通知

---

## 9.2 生命週期

```text
queued
  -> running
  -> waiting_message   (如果 agent 需要繼續)
  -> running           (收到 SendMessage)
  -> completed | failed | killed
```

---

## 9.3 背景執行要求

若 `run_in_background=true`：

1. `AgentTool` 回傳後，coordinator 立即可繼續工作
2. task 在背景 thread / subprocess / worker 中執行
3. 完成時把通知塞進 coordinator 的訊息佇列

---

## 9.4 前景執行要求

若 `run_in_background=false`：

1. coordinator 呼叫後等待完成
2. 任務結果直接作為工具結果回傳
3. v1 可先簡化成同步執行

---

# 10. 通訊協議規格

## 10.1 Worker → Coordinator 回報格式

採 XML 包裝，因為容易識別，也方便在 user-role message 中嵌入。

```xml
<task-notification>
  <task-id>{agentId}</task-id>
  <status>completed|failed|killed</status>
  <summary>{human-readable summary}</summary>
  <result>{final text response}</result>
  <output_file>{optional}</output_file>
  <worktree>{optional}</worktree>
  <worktree-branch>{optional}</worktree-branch>
  <usage>
    <total_tokens>N</total_tokens>
    <tool_uses>N</tool_uses>
    <duration_ms>N</duration_ms>
  </usage>
</task-notification>
```

---

## 10.2 識別規則

Coordinator 收到 user-role message 時：

1. 若訊息以 `<task-notification>` 開頭
2. 視為 internal notification
3. 不當成使用者真的在說話
4. 不回「收到」、「謝謝」之類

---

## 10.3 Notification Queue

需要一個 `enqueuePendingNotification(xml: string)`。

### 功能

1. 將 worker 完成通知塞入 coordinator session
2. 等下一輪主 agent loop 處理
3. 保持順序
4. 避免重複插入

---

## 10.4 防重複通知

在 enqueue 前必須先原子檢查：

```ts
if (task.notified) return
task.notified = true
enqueue(xml)
```

否則會出現：

* task 完成一次
* 被 stop 一次
* 最後收到兩份通知

---

# 11. Coordinator 行為規格

## 11.1 核心原則

Coordinator 只做：

1. 派工
2. 綜整
3. 決策
4. 對使用者輸出

不要做：

1. 假裝 worker 已完成
2. 預測 fork 結果
3. 把 worker notification 當聊天對象

---

## 11.2 Continue vs Spawn Fresh 決策規則

### 優先 Continue

適合：

1. 同一 worker 已讀過相關檔案
2. 該 worker 剛失敗，還保有錯誤 context
3. 要在原方向上修正

### 優先 Spawn Fresh

適合：

1. 前一個 worker 方向錯很大
2. 驗證別人改的程式碼
3. 新任務與原任務幾乎無關
4. 不想被舊 context 汙染

---

## 11.3 Synthesis 職責

Coordinator 不能只把 research 原封不動轉丟下一個 worker。

必須自己先整理出：

1. 問題在哪
2. 哪個檔案
3. 哪一段邏輯
4. 要怎麼改
5. 驗證方式

然後再給 implementation worker。

---

# 12. Prompt 契約規格

## 12.1 派工 prompt 必須包含

1. 任務目標
2. 為什麼要做
3. 已知資訊
4. 限制條件
5. 是否允許寫檔
6. 輸出格式要求

### 範例

```text
請修正 src/auth/validate.ts 中 session 過期時 user 為 undefined 導致的 null pointer。
已知問題發生在驗證 token 後存取 user.id 的地方。
請加入 null check；若 session 已過期則回傳 401 與 "Session expired"。
請修改程式並執行相關測試。
最後回報：
1. 修改了哪些檔案
2. 核心改動
3. 測試結果
4. commit hash（若有）
```

---

## 12.2 fork prompt 要求

fork 因為繼承父 context，prompt 可以短一些，但仍必須清楚說明：

1. 要處理哪一段
2. 需要什麼輸出
3. 是否只研究不修改

---

# 13. 隔離策略規格

## 13.1 none

直接在當前工作目錄執行。

適合：

* 唯讀研究
* 小型分析

---

## 13.2 worktree

為 subagent 建立獨立 git worktree。

適合：

* 寫碼
* 平行修改
* 避免互相覆蓋

### 額外欄位

```ts
worktreePath: string
worktreeBranch: string
```

---

## 13.3 remote

在遠端沙箱或容器執行。

適合：

* 高隔離需求
* 不可信執行環境
* 跨平台工具鏈

---

# 14. 內建 agent / subagent type 規格

v1 建議至少支援這些 `subagent_type`：

```ts
type BuiltInSubagentType =
  | "general-purpose"
  | "explore"
  | "plan"
  | "verification"
```

### general-purpose

可做研究、實作、測試。

### explore

唯讀，不可寫檔，不可再派生子 agent。

### plan

唯讀，產出規格與方案。

### verification

用於驗證，不負責主要修改。

---

# 15. 權限規格

每個 subagent 要有工具白名單 / 黑名單。

```ts
interface AgentDefinition {
  type: string
  description: string
  allowedTools: string[]
  disallowedTools?: string[]
  systemPrompt: string
}
```

### 建議限制

* `explore`：禁寫檔、禁 AgentTool
* `plan`：禁寫檔、禁 AgentTool
* `verification`：可測試，可讀檔，禁 AgentTool
* `general-purpose`：可依需求開放

---

# 16. 錯誤處理規格

## 16.1 Task 失敗

若 subagent 失敗，通知格式中：

```xml
<status>failed</status>
<summary>Type error in src/auth/validate.ts</summary>
<result>完整錯誤摘要...</result>
```

Coordinator 應優先：

1. 用 SendMessage 繼續原 worker
2. 若第二次還失敗，再換 fresh worker 或回報使用者

---

## 16.2 Task 被停止

通知中：

```xml
<status>killed</status>
```

Coordinator 可選擇：

1. 不再處理
2. 改派新 worker
3. 對使用者說明策略已調整

---

## 16.3 Task 不存在

`SendMessageTool` / `TaskStopTool` 若找不到 task：

* 回傳結構化錯誤
* 不要 silently ignore

---

# 17. 觀測與除錯規格

每個 task 至少記錄：

```ts
interface TaskMetrics {
  startedAt: number
  endedAt?: number
  durationMs?: number
  totalTokens?: number
  toolUses: number
  statusTransitions: Array<{
    from: string
    to: string
    at: number
  }>
}
```

建議另外記錄：

1. parent task
2. worker type
3. isolation mode
4. 最終摘要
5. 是否 background

---

# 18. 最小資料流

## 18.1 Spawn 流程

```text
使用者提出需求
-> Coordinator 判斷需委派
-> AgentTool(prompt, subagent_type, run_in_background)
-> TaskRegistry.createTask()
-> TaskRunner 啟動
-> Worker 執行
-> Worker 完成
-> buildTaskNotificationXml()
-> enqueuePendingNotification()
-> Coordinator 收到通知
-> 綜整結果回覆使用者
```

---

## 18.2 Continue 流程

```text
Coordinator 收到 worker failed/completed 或想追加工作
-> SendMessageTool(to=task_id, message=...)
-> Task.pendingMessages.push(message)
-> Worker 被喚醒
-> 繼續執行
-> 再次通知
```

---

## 18.3 Stop 流程

```text
Coordinator 發現方向錯誤
-> TaskStopTool(task_id)
-> Task.status = killing
-> Runner 收到取消訊號
-> Task.status = killed
-> enqueue kill notification
```

---

# 19. 參考介面草稿

## 19.1 建立 task

```ts
function spawnAgentTask(input: AgentToolInput, sessionId: string): AgentToolResult
```

## 19.2 執行 task

```ts
async function runAgentTask(taskId: string): Promise<void>
```

## 19.3 傳訊息

```ts
function sendMessageToTask(input: SendMessageToolInput): SendMessageToolResult
```

## 19.4 停止 task

```ts
function stopTask(input: TaskStopToolInput): TaskStopToolResult
```

## 19.5 建立通知 XML

```ts
function buildTaskNotificationXml(task: BaseTask): string
```

---

# 20. v1 實作順序

最實際的施工順序建議是：

## Phase 1：單機本地版

先做：

1. `TaskRegistry`
2. `AgentTool`
3. `TaskRunner`
4. `task-notification`
5. `SendMessageTool`
6. `TaskStopTool`

這階段只支援：

* local task
* spawn
* background
* XML 通知

---

## Phase 2：fork 與 cache 最佳化

再補：

1. fork mode
2. context inheritance
3. prompt cache key 穩定策略
4. continue/spawn fresh 決策邏輯

---

## Phase 3：worktree / remote

再做：

1. worktree isolation
2. remote sandbox
3. 更完整的錯誤恢復

---

## Phase 4：team / swarm

最後才做：

1. teammate mailbox
2. TeamCreateTool
3. leader / teammate permission bridge

---

# 21. v1 驗收標準

做到下面這些，就算 v1 完成：

1. 主 agent 可用 `AgentTool` 建立 subagent
2. subagent 可背景執行
3. subagent 完成會以 `<task-notification>` 回報
4. 主 agent 可用 `SendMessageTool` 繼續同一個 subagent
5. 主 agent 可用 `TaskStopTool` 停止 subagent
6. task state 不會重複通知
7. spawn 與 fork 有明確區分
8. agent type 有工具權限限制
9. coordinator 不會偽造 worker 結果
10. 可觀測每個 task 的狀態與耗時

