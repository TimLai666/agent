# 01. 實作目標

實作一個 agent orchestration runtime，支援：

1. 使用者送進任務
2. main agent 判斷是否自己回答，或派 worker
3. worker 執行研究、實作、修正、測試
4. worker 結束後回傳 `<task-notification>`
5. 若任務屬於 non-trivial implementation，必須再派 verification agent
6. verifier 回傳 `PASS / FAIL / PARTIAL`
7. 只有在 completion gate 通過後，main session 才能回使用者

---

# 02. 第一版範圍

第一版只做這些，不要超做：

* normal mode
* coordinator mode
* worker agent
* verification agent
* task state machine
* task-notification protocol
* completion gate
* SendMessage 給既有 worker
* background task 基礎支援
* tool 使用記錄
* final answer synthesis

先**不要做**：

* teammate swarm
* cross-session UDS inbox
* auto dream
* memdir
* full skill system
* UI 漂亮化
* tool 權限細緻沙盒
* PR 訂閱與外部整合

---

# 03. 系統總架構

```text
User
  ↓
Main Session Runtime
  ├─ Session Mode Resolver
  ├─ Prompt Assembler
  ├─ Coordinator Loop
  ├─ Task Store
  ├─ Agent Runner
  ├─ Verification Runner
  ├─ Notification Queue
  └─ Completion Gate
        ↓
   Final User Response
```

在 coordinator mode 下：

```text
User Request
  ↓
Coordinator
  ├─ spawn research worker(s)
  ├─ synthesize
  ├─ spawn implementation worker
  ├─ spawn verification worker
  └─ finalize to user
```

---

# 04. 檔案與模組切分

建議直接這樣切：

```text
src/
  core/
    session/
      sessionMode.ts
      sessionContext.ts
      promptAssembler.ts
    tasks/
      taskTypes.ts
      taskStore.ts
      taskStateMachine.ts
      notificationQueue.ts
      completionGate.ts
    agents/
      agentTypes.ts
      builtInAgents.ts
      agentRunner.ts
      workerRunner.ts
      verificationRunner.ts
      sendMessage.ts
    coordinator/
      coordinatorLoop.ts
      coordinatorPrompt.ts
      taskPlanner.ts
      resultSynthesizer.ts
    protocol/
      taskNotification.ts
      verdictParser.ts
    prompts/
      mainSystemPrompt.ts
      workerPrompt.ts
      verificationPrompt.ts
      coordinatorSystemPrompt.ts
    tools/
      toolRegistry.ts
      toolExecution.ts
      toolUsageTracker.ts
  app/
    handleUserTurn.ts
    bootstrap.ts
```

---

# 05. 關鍵資料結構

## 5.1 SessionMode

```ts
export type SessionMode = 'normal' | 'coordinator'
```

---

## 5.2 TaskStatus

照文件做這幾個：

```ts
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'killed'
```

---

## 5.3 AgentType

```ts
export type AgentType =
  | 'general-purpose'
  | 'research'
  | 'implementation'
  | 'verification'
```

---

## 5.4 TaskRecord

```ts
export interface TaskRecord {
  id: string
  parentTaskId?: string
  agentType: AgentType
  status: TaskStatus
  title: string
  originalUserRequest: string
  workerInstruction: string
  createdAt: number
  startedAt?: number
  finishedAt?: number
  runInBackground: boolean
  model?: string

  filesChanged: string[]
  commandsExecuted: string[]
  verificationNeeded: boolean

  finalTextResponse?: string
  summary?: string
  error?: string
  usage?: TaskUsage
}
```

---

## 5.5 TaskUsage

```ts
export interface TaskUsage {
  inputTokens?: number
  outputTokens?: number
  cacheCreationInputTokens?: number
  cacheReadInputTokens?: number
  durationMs?: number
}
```

---

## 5.6 WorkerResult

```ts
export interface WorkerResult {
  taskId: string
  status: 'completed' | 'failed' | 'killed'
  summary: string
  result: string
  filesChanged: string[]
  commandsExecuted: string[]
  evidence: string[]
  unresolvedIssues: string[]
  usage?: TaskUsage
}
```

---

## 5.7 VerificationVerdict

```ts
export type VerificationVerdict = 'PASS' | 'FAIL' | 'PARTIAL'
```

---

## 5.8 VerificationResult

```ts
export interface VerificationResult {
  taskId: string
  verdict: VerificationVerdict
  summary: string
  evidence: Array<{
    command: string
    output: string
    result: 'PASS' | 'FAIL'
  }>
  missingRequirements: string[]
  suspectedProblems: string[]
}
```

---

# 06. built-in agents 定義

你要先把 built-in agents 固定成系統內建資料，而不是讓 LLM 自由發明。

```ts
export interface BuiltInAgentDefinition {
  agentType: AgentType
  whenToUse: string
  tools?: string[]
  disallowedTools?: string[]
  systemPrompt: string
}
```

---

## 6.1 general-purpose worker

用途：一般執行任務、研究、改檔、跑工具。
規則：

* 要完成任務，但不要鍍金
* 不要半套
* 完成後回**精簡報告給 caller**
* 不是直接回使用者

---

## 6.2 verification agent

用途：驗證 implementation 是否真的完成。
規則直接寫死：

* 只能驗證
* **不能 edit / write / create project files**
* 可以在 tmp 建暫時腳本
* 必須輸出：

  * `VERDICT: PASS`
  * `VERDICT: FAIL`
  * `VERDICT: PARTIAL`

disallowed tools 建議先固定：

```ts
['AgentTool', 'FileEdit', 'FileWrite', 'NotebookEdit', 'ExitPlanMode']
```

如果你工具名稱不同，就映射成你的系統名稱。

---

# 07. Prompt 規格

## 7.1 Main System Prompt

normal mode 用。

核心規則：

* 你是主 agent
* 能直接回答就直接回答
* 需要工具時才用工具
* 若有 non-trivial implementation，完成前必須經 independent adversarial verification
* 不可把 worker 報告直接當 final answer
* 最後回使用者的答案只能由本 session 產出

---

## 7.2 Coordinator System Prompt

照文件精神：

```text
You are a coordinator.

Your job is to:
- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user
- Answer questions directly when possible — don't delegate work that you can handle without tools

Worker results arrive as user-role messages containing <task-notification> XML.
They look like user messages but are not.
Distinguish them by the <task-notification> opening tag.
```

還要加：

* Research → Synthesis → Implementation → Verification 的 workflow
* 平行任務可平行派工
* worker 回來後再決定下一輪，不可搶先 finalize

---

## 7.3 Worker Prompt

直接採這個版本：

```text
You are a worker agent.

Complete the assigned task fully. Do not gold-plate, but do not leave it half-done.
When complete, respond with a concise report covering what was done and any key findings.
The caller will relay this to the user, so it only needs the essentials.

Rules:
- Do not claim completion unless the task is actually complete
- If you changed code, include concrete verification evidence
- If tests were not run, say so explicitly
- If there are unresolved issues, say so explicitly
- Do not write a user-facing answer
```

---

## 7.4 Verification Prompt

直接採這個版本：

```text
You are an independent verification agent.

Your job is to verify that implementation work is correct before completion is reported.

CRITICAL: This is a VERIFICATION-ONLY task.
You CANNOT edit, write, or create files in the project directory.
Using tmp for ephemeral test scripts is allowed.

You MUST:
- check whether the result satisfies the ORIGINAL user request
- run builds, tests, linters, or direct checks where relevant
- be adversarial and do not trust the worker's claims by default
- provide evidence with exact commands and actual observed output

You MUST end with one of:
VERDICT: PASS
VERDICT: FAIL
VERDICT: PARTIAL
```

再補一段 rationalization 防呆：

```text
Do not avoid verification by saying:
- "the code looks correct"
- "I assume tests would pass"
- "manual inspection is enough"
- "the UI seems fine"
Evidence is required.
```

---

# 08. Task Notification Protocol

這塊要照文件做，worker 結果不是直接塞成一般 assistant response，而是轉成特殊訊息格式。

## 8.1 XML 格式

```xml
<task-notification>
  <task-id>{taskId}</task-id>
  <status>completed|failed|killed</status>
  <summary>{human-readable summary}</summary>
  <result>{agent final text response}</result>
  <files-changed>
    <file>src/a.ts</file>
    <file>src/b.ts</file>
  </files-changed>
  <commands-executed>
    <command>npm test</command>
    <command>npm run build</command>
  </commands-executed>
  <usage>
    <input_tokens>N</input_tokens>
    <output_tokens>N</output_tokens>
    <duration_ms>N</duration_ms>
  </usage>
  <tool-use-id>{toolUseId}</tool-use-id>
</task-notification>
```

---

## 8.2 規則

1. worker 最後一條文字回應只當作 `result`
2. runtime 負責包成 `<task-notification>`
3. 這個通知要以 **user-role message** 形式送進 coordinator context
4. coordinator prompt 必須知道這**看起來像 user message，但其實不是**

---

# 09. 狀態機

## 9.1 Task lifecycle

```text
pending -> running -> completed
                  -> failed
                  -> killed
```

---

## 9.2 狀態轉移規則

### createTask()

* 建立後 `pending`

### startTask()

* `pending -> running`

### completeTask()

* `running -> completed`
* 必須同時：

  * 存 `finalTextResponse`
  * 組裝 `task-notification`
  * enqueue notification
  * 記錄 usage
  * 設定 finishedAt

### failTask()

* `running -> failed`

### killTask()

* `pending|running -> killed`

---

# 10. Completion Gate

這是整套最重要的邏輯。

## 10.1 何時需要 verification

先做這個版本：

```ts
export function needsVerification(input: {
  filesChanged: string[]
  commandsExecuted: string[]
  taskKind: 'question' | 'research' | 'implementation' | 'bugfix' | 'infra'
}): boolean {
  if (input.taskKind === 'implementation') return true
  if (input.taskKind === 'bugfix') return true
  if (input.taskKind === 'infra') return true
  if (input.filesChanged.length >= 3) return true
  if (input.commandsExecuted.length > 0 && input.filesChanged.length > 0) return true
  return false
}
```

如果你要更接近文件，可把這些列入強制 verification：

* 3+ file edits
* backend/API changes
* infrastructure changes

---

## 10.2 完成判定

```ts
export interface CompletionDecision {
  done: boolean
  reason: string
  nextAction?: 'finalize' | 'retry-worker' | 'run-verification' | 'ask-user'
}
```

```ts
export function decideCompletion(
  worker: WorkerResult,
  verification?: VerificationResult
): CompletionDecision {
  if (worker.status !== 'completed') {
    return {
      done: false,
      reason: 'worker did not complete successfully',
      nextAction: 'retry-worker',
    }
  }

  if (worker.unresolvedIssues.length > 0) {
    return {
      done: false,
      reason: 'worker reported unresolved issues',
      nextAction: 'retry-worker',
    }
  }

  const verificationRequired = needsVerification({
    filesChanged: worker.filesChanged,
    commandsExecuted: worker.commandsExecuted,
    taskKind: worker.filesChanged.length > 0 ? 'implementation' : 'research',
  })

  if (verificationRequired && !verification) {
    return {
      done: false,
      reason: 'verification required before completion',
      nextAction: 'run-verification',
    }
  }

  if (verification) {
    if (verification.verdict === 'FAIL') {
      return {
        done: false,
        reason: 'verification failed',
        nextAction: 'retry-worker',
      }
    }

    if (verification.verdict === 'PARTIAL') {
      return {
        done: false,
        reason: 'verification only partially passed',
        nextAction: 'retry-worker',
      }
    }
  }

  return {
    done: true,
    reason: 'task completed and verification passed',
    nextAction: 'finalize',
  }
}
```

---

# 11. Coordinator Loop

這個就是核心 runtime。

```ts
export async function runCoordinatorTurn(ctx: CoordinatorTurnContext): Promise<string> {
  while (true) {
    const plan = await makeOrUpdatePlan(ctx)

    if (plan.type === 'answer-directly') {
      return plan.finalAnswer
    }

    if (plan.type === 'spawn-worker') {
      const task = await spawnWorker(plan.workerSpec)
      const workerResult = await waitForTaskNotification(task.id)

      const decision1 = decideCompletion(workerResult)

      if (decision1.nextAction === 'run-verification') {
        const verificationTask = await spawnVerificationWorker({
          originalUserRequest: ctx.userRequest,
          workerResult,
        })

        const verificationResult = await waitForVerificationResult(verificationTask.id)
        const decision2 = decideCompletion(workerResult, verificationResult)

        if (decision2.done) {
          return synthesizeFinalAnswer(ctx, workerResult, verificationResult)
        }

        ctx = augmentContextWithFailure(ctx, workerResult, verificationResult)
        continue
      }

      if (decision1.done) {
        return synthesizeFinalAnswer(ctx, workerResult)
      }

      ctx = augmentContextWithFailure(ctx, workerResult)
      continue
    }
  }
}
```

---

# 12. Worker Spawn API

```ts
export interface SpawnWorkerInput {
  agentType: AgentType
  title: string
  originalUserRequest: string
  instruction: string
  runInBackground?: boolean
  model?: string
}
```

```ts
export async function spawnWorker(input: SpawnWorkerInput): Promise<TaskRecord>
```

規則：

* 建 task record
* 設 `pending`
* 啟動 agent runner
* agent 結束後自動 enqueue task-notification

---

# 13. Verification Spawn API

```ts
export interface SpawnVerificationInput {
  originalUserRequest: string
  workerResult: WorkerResult
  filesChanged: string[]
  approachSummary?: string
}
```

verification agent 收到的內容要包含：

1. 原始 user request
2. worker summary
3. files changed
4. commands already run
5. 需要驗證的 claim
6. 目前已知限制

---

# 14. Verification 輸出解析器

verifier 最後必須有 `VERDICT:`，所以做一個 parser。

```ts
export function parseVerificationVerdict(text: string): VerificationResult {
  const verdict =
    text.includes('VERDICT: PASS') ? 'PASS' :
    text.includes('VERDICT: FAIL') ? 'FAIL' :
    text.includes('VERDICT: PARTIAL') ? 'PARTIAL' :
    null

  if (!verdict) {
    throw new Error('Verification output missing VERDICT')
  }

  return {
    taskId: '',
    verdict,
    summary: extractSummary(text),
    evidence: extractEvidence(text),
    missingRequirements: extractMissingRequirements(text),
    suspectedProblems: extractSuspectedProblems(text),
  }
}
```

---

# 15. SendMessage 機制

你需要允許 coordinator 對既有 worker 繼續發指令，而不是每次都重開新 worker。

```ts
export interface SendMessageInput {
  toTaskId: string
  message: string
}
```

用途：

* verification FAIL 後叫 implementation worker 修
* research worker 補查特定檔案
* coordinator 分階段推進同一個 worker

---

# 16. 背景任務

第一版只做基礎功能：

* `runInBackground = true` 時，coordinator 可先繼續其他事
* worker 完成後照樣丟 `<task-notification>`
* task store 要能查詢未完成背景任務

不需要做太複雜 UI，只要 runtime 有這能力即可。

---

# 17. Tool 使用紀錄

因為 verification 很依賴證據，所以 worker / verifier 都要記：

```ts
export interface ToolExecutionRecord {
  toolName: string
  startedAt: number
  finishedAt: number
  inputSummary: string
  outputSummary: string
  success: boolean
}
```

commands / file changes 最低限度要能抽出來。

---

# 18. User-facing final answer 規則

只能由 main session / coordinator 產生。
不能直接把 worker 的原文丟出去。

final synthesis 原則：

* 總結完成了什麼
* 若有 verification，帶一句：

  * 已驗證通過
  * 驗證顯示仍有問題
* 若部分完成，要老實說哪裡沒完成
* 不要原封轉貼 `<task-notification>`

---

# 19. 實作順序

這順序可以直接照做。

## Phase A：最小骨架

1. `TaskStatus`
2. `TaskRecord`
3. `taskStore`
4. `agentRunner`
5. `taskNotification serializer/parser`

完成標準：

* 能 spawn 一個 worker
* worker 結束後能產生 `<task-notification>`

---

## Phase B：normal mode 完成鏈

1. `workerPrompt`
2. `verificationPrompt`
3. `needsVerification`
4. `decideCompletion`
5. `verificationRunner`

完成標準：

* implementation worker 完成後，會自動進 verification
* verifier FAIL 時不會直接回使用者

---

## Phase C：coordinator mode

1. `coordinatorSystemPrompt`
2. `runCoordinatorTurn`
3. `sendMessage`
4. `resultSynthesizer`

完成標準：

* coordinator 可派 worker
* 收到 `<task-notification>` 後能繼續決策
* 只由 coordinator 回使用者

---

## Phase D：背景任務

1. `runInBackground`
2. `notificationQueue`
3. pending/completed 查詢

---

# 20. 驗收條件

這些測試都要過。

## Case 1：純問答

使用者問概念題
預期：

* 不派 worker 或可派 research worker
* 不進 verification
* 直接回使用者

---

## Case 2：小型 research

使用者要找哪幾個檔案可能有 bug
預期：

* 派 research worker
* worker 回簡潔報告
* coordinator 整理後回使用者
* 不強制 verification

---

## Case 3：non-trivial implementation

使用者要求改 4 個檔案修 API bug
預期：

* implementation worker 完成
* 自動啟動 verification agent
* verifier 跑測試 / build / check
* 只有 `PASS` 才能 finalize

---

## Case 4：verification fail

預期：

* coordinator 不可直接回「完成」
* 要把 verifier findings 回灌給 worker
* 再跑一輪修正

---

## Case 5：worker completed 但沒證據

預期：

* completion gate 擋下
* 進 verification 或要求補充 evidence

---

## Case 6：background task

預期：

* coordinator 可同時派兩個 research workers
* 任一 worker 完成後可收到 `<task-notification>`

---

# 21. 你現在可以直接交給 agent 的開工指令

下面這段你可以直接貼給 coding agent：

```text
請實作一個 agent orchestration runtime，需求如下：

1. 支援 session mode:
   - normal
   - coordinator

2. 實作 task state machine:
   - pending
   - running
   - completed
   - failed
   - killed

3. 實作 built-in agents:
   - general-purpose worker
   - verification

4. worker 完成後不可直接當作 user-facing answer。
   runtime 必須把 worker 最後輸出包成 <task-notification> XML，格式至少包含：
   - task-id
   - status
   - summary
   - result
   - files-changed
   - commands-executed
   - usage

5. coordinator 必須把 <task-notification> 視為特殊的 user-role message，但不能把它當真正使用者輸入。

6. 實作 completion gate：
   - non-trivial implementation 必須先經過 independent verification
   - verification agent 必須輸出：
     VERDICT: PASS / FAIL / PARTIAL
   - 若 FAIL 或 PARTIAL，不可 finalize，必須回到 worker 修正

7. verification agent 是 verification-only：
   - 不可 edit/write/create project files
   - 可在 tmp 建暫時測試檔
   - 必須提供命令與實際輸出證據

8. 實作 sendMessage 機制，允許 coordinator 對既有 worker 繼續發指令。

9. 目錄結構請至少包含：
   - session
   - tasks
   - agents
   - coordinator
   - protocol
   - prompts
   - tools

10. 先完成最小可用版本，不要做 swarm、memory、skills、外部整合。

請先建立完整型別、task store、notification protocol、worker runner、verification runner、completion gate、coordinator loop，並附上最小可跑的整合測試。
```

---

# 22. 第一批你應該先產出的檔案

直接指定給 agent：

```text
src/core/tasks/taskTypes.ts
src/core/tasks/taskStore.ts
src/core/tasks/taskStateMachine.ts
src/core/tasks/completionGate.ts
src/core/protocol/taskNotification.ts
src/core/protocol/verdictParser.ts
src/core/agents/agentTypes.ts
src/core/agents/builtInAgents.ts
src/core/agents/agentRunner.ts
src/core/agents/workerRunner.ts
src/core/agents/verificationRunner.ts
src/core/agents/sendMessage.ts
src/core/coordinator/coordinatorLoop.ts
src/core/prompts/workerPrompt.ts
src/core/prompts/verificationPrompt.ts
src/core/prompts/coordinatorSystemPrompt.ts
src/app/handleUserTurn.ts
```

---

# 23. 最後定義：什麼叫「照文件做對」

你這套做完，必須符合這 5 條才算真的抄到核心：

1. **worker 不能直接對 user finalize**
2. **worker 回來必須走 `<task-notification>`**
3. **non-trivial implementation 必須 verification**
4. **verifier 不能改專案檔**
5. **最後只能由 main session / coordinator 回使用者**
