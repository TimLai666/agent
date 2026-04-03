# 01_Context Compaction 完整架構規格

## 一、目的

當主對話接近 context window 上限時，系統必須暫停主 agent 的正常工作流程，啟動一個**專職的 compaction subagent**，把舊對話壓縮為結構化摘要，再由系統重建上下文，最後讓主 agent 從壓縮後的上下文無縫接續工作。

本模組目標不是做一般摘要，而是把舊對話改寫成一份**可繼續執行工作的狀態文件**。

---

## 二、架構總覽

### 2.1 元件

```text
Main Agent
  └── 負責一般任務執行、工具調用、與使用者互動

Compact Coordinator
  └── 監控 token / 判斷是否需要壓縮 / 選擇 compact 模式 / 重建上下文

Compaction Subagent
  └── 專責做 context compaction，只輸出純文字，不可用工具

Conversation Store
  └── 保存完整訊息、最近訊息、壓縮摘要、transcript 路徑、compact metadata
```

### 2.2 責任分工

#### Main Agent

* 正常處理使用者任務
* 可使用工具
* 不負責執行壓縮摘要本身
* 在 compact 發生時被中斷，compact 完成後再恢復

#### Compact Coordinator

* 監控 context 使用量
* 決定何時觸發 compact
* 決定使用哪一種 compact prompt
* 建立 compaction subagent
* 接收 compaction 結果
* 清理 `<analysis>`
* 重建新上下文
* 恢復主 agent 執行

#### Compaction Subagent

* 專門處理摘要任務
* 嚴格禁止工具呼叫
* 輸入是既有對話內容與舊摘要
* 輸出是 `<analysis>` + `<summary>`
* 不參與原任務決策、不修改使用者意圖、不產生新任務

---

## 三、流程圖

```text
使用者 / 工具 / assistant 訊息持續累積
        ↓
Compact Coordinator 計算 token 使用量
        ↓
若未達門檻 → 主 agent 繼續工作
        ↓
若達門檻 → 暫停主 agent
        ↓
選擇 compact 模式（BASE / PARTIAL_FROM / PARTIAL_UP_TO）
        ↓
建立 Compaction Subagent
        ↓
送入舊摘要 + 待壓縮訊息
        ↓
Subagent 回傳 <analysis> + <summary>
        ↓
Coordinator 清除 <analysis>、抽出 <summary>
        ↓
重建上下文（summary + recent messages）
        ↓
恢復 Main Agent
```

---

## 四、資料模型

### 4.1 Message

```ts
type Role = "system" | "user" | "assistant" | "tool"

type Message = {
  id: string
  role: Role
  content: string
  tokenCount: number
  createdAt: string
}
```

### 4.2 CompactSummary

```ts
type CompactSummary = {
  version: number
  mode: "base" | "partial_from" | "partial_up_to"
  rawOutput: string          // subagent 原始輸出，含 <analysis> <summary>
  formattedSummary: string   // 清理後正式摘要
  createdAt: string
}
```

### 4.3 ConversationState

```ts
type ConversationState = {
  fullMessages: Message[]
  compressedSummary: string | null
  recentMessages: Message[]
  transcriptPath?: string
  totalTokens: number
  lastCompactedMessageId?: string
}
```

### 4.4 CompactJob

```ts
type CompactJob = {
  jobId: string
  mode: "base" | "partial_from" | "partial_up_to"
  oldSummary: string
  messagesToCompress: Message[]
  preservedRecentMessages: Message[]
  suppressFollowUpQuestions: boolean
}
```

---

## 五、觸發條件

### 5.1 Token 門檻

```ts
const MAX_CONTEXT_TOKENS = 128000
const COMPACT_TRIGGER_RATIO = 0.75
const RECENT_KEEP_COUNT = 8
```

### 5.2 判定邏輯

```ts
function shouldCompact(totalTokens: number): boolean {
  return totalTokens >= MAX_CONTEXT_TOKENS * COMPACT_TRIGGER_RATIO
}
```

### 5.3 觸發原則

* 不在每輪都 compact
* 接近 context 上限才 compact
* compact 時至少保留最近 `RECENT_KEEP_COUNT` 則訊息原文
* compact 可被重複執行，不是一次性流程

---

## 六、Compact 模式

文件對應三種模式，規格也必須保留。

### 6.1 BASE COMPACT

用途：

* 整段舊歷史都需要壓縮時使用

輸入：

* 舊摘要
* 目前要壓縮的全部舊訊息

輸出摘要第 8 區：

* `Current Work`

### 6.2 PARTIAL_COMPACT_FROM

用途：

* 前段上下文保留原文，只壓縮「後段近期內容」

適用：

* 有一部分舊上下文仍要保留 verbatim
* 只需要把後面新增的一段濃縮

輸出摘要第 8 區：

* `Current Work`

### 6.3 PARTIAL_COMPACT_UP_TO

用途：

* 把某個切點之前的內容壓縮，後面較新的訊息保留原文繼續接

適用：

* 需要讓壓縮摘要放在 session 開頭，再接後續原文

輸出摘要第 8 區改為：

* `Work Completed`

第 9 區改為：

* `Context for Continuing Work`

---

## 七、Subagent 設計

## 7.1 Agent 型別

```ts
type SubagentType = "compaction"
```

## 7.2 Compaction Subagent 定義

```ts
type CompactionSubagentDefinition = {
  agentType: "compaction"
  tools: []
  disallowedTools: ["*"]
  background: false
  omitProjectInstructions: true
  maxTurns: 1
}
```

## 7.3 行為限制

Compaction subagent 必須符合以下規則：

* 不可呼叫任何工具
* 不可發問
* 不可編輯檔案
* 不可產生新的執行計畫
* 不可主動延伸任務
* 只能根據提供的上下文輸出文字

## 7.4 為何必須用 subagent

這是架構規範，不是選配：

* 避免主 agent 的任務推理被摘要工作污染
* 避免主 agent 在 compact 時誤用工具
* 讓 compact prompt 可以獨立、乾淨、可控
* 便於未來針對 compact 使用不同模型或不同參數
* 可讓 compact 成為明確可監控、可測試的內部工作節點

---

## 八、Compact Coordinator 規格

### 8.1 功能

Compact Coordinator 負責：

* 檢查 token
* 判定 compact 模式
* 切分待壓縮與保留訊息
* 呼叫 compaction subagent
* 格式化輸出
* 重建上下文
* 恢復主 agent

### 8.2 Coordinator 介面

```ts
interface CompactCoordinator {
  maybeCompact(state: ConversationState): Promise<ConversationState>
  runCompact(job: CompactJob): Promise<CompactSummary>
  formatCompactSummary(rawOutput: string): string
  buildContinuationMessage(args: {
    summary: string
    transcriptPath?: string
    recentMessagesPreserved?: boolean
    suppressFollowUpQuestions?: boolean
    proactiveMode?: boolean
  }): string
}
```

---

## 九、切分策略

### 9.1 訊息切分

```ts
function splitMessagesForCompaction(messages: Message[]) {
  const preservedRecentMessages = messages.slice(-RECENT_KEEP_COUNT)
  const messagesToCompress = messages.slice(0, -RECENT_KEEP_COUNT)

  return {
    messagesToCompress,
    preservedRecentMessages,
  }
}
```

### 9.2 原則

* 最近訊息保留 verbatim
* 較舊訊息送進 subagent
* 壓縮完成後，舊訊息不再直接放進主上下文
* 若仍需追查精確細節，透過 transcript 路徑回讀

---

## 十、完整 Compaction Prompt 規格

以下是規格內建的正式 prompt。實作時可直接當模板。

---

## 10.1 NO_TOOLS_PREAMBLE

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
```

---

## 10.2 BASE 分析指令

```text
Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.
```

---

## 10.3 PARTIAL 分析指令

```text
Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Analyze the recent messages chronologically. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.
```

---

## 10.4 BASE_COMPACT_PROMPT

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
8. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
9. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's most recent explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests or really old requests that were already completed without confirming with the user first.
If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
```

---

## 10.5 PARTIAL_COMPACT_FROM_PROMPT

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

Your task is to create a detailed summary of the RECENT portion of the conversation — the messages that follow earlier retained context. The earlier messages are being kept intact and do NOT need to be summarized.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Analyze the recent messages chronologically. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Current Work
9. Optional Next Step

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
```

---

## 10.6 PARTIAL_COMPACT_UP_TO_PROMPT

```text
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

Your task is to summarize the EARLIER portion of the conversation up to the cutoff point. Newer messages will remain in the conversation verbatim after this summary, so your summary should focus on preserving the context needed for those later messages to make sense.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Analyze the messages chronologically up to the cutoff point.
2. Identify:
   - The user's explicit requests and intents
   - Key technical concepts, files, code patterns, and decisions
   - Errors encountered and how they were fixed
   - Important user feedback that changed direction
3. Double-check for technical accuracy and continuity with later messages.

Your summary should include the following sections:

1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Work Completed
9. Context for Continuing Work

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
```

---

## 十一、Prompt 組裝邏輯

```ts
type CompactMode = "base" | "partial_from" | "partial_up_to"

function getCompactionPrompt(
  mode: CompactMode,
  customInstructions?: string
): string {
  let prompt = ""

  if (mode === "base") prompt = BASE_COMPACT_PROMPT
  if (mode === "partial_from") prompt = PARTIAL_COMPACT_FROM_PROMPT
  if (mode === "partial_up_to") prompt = PARTIAL_COMPACT_UP_TO_PROMPT

  if (customInstructions?.trim()) {
    prompt += `\n\nAdditional Instructions:\n${customInstructions}`
  }

  return prompt
}
```

---

## 十二、Subagent 呼叫規格

```ts
async function runCompactionSubagent(job: CompactJob): Promise<string> {
  const prompt = getCompactionPrompt(job.mode)

  return await runSubagent({
    agentType: "compaction",
    systemPrompt: prompt,
    input: {
      previousCompressedSummary: job.oldSummary,
      messagesToCompress: job.messagesToCompress,
    },
    tools: [],
    maxTurns: 1,
  })
}
```

---

## 十三、輸出清理規格

### 13.1 formatCompactSummary

```ts
function formatCompactSummary(rawOutput: string): string {
  let formatted = rawOutput

  formatted = formatted.replace(/<analysis>[\s\S]*?<\/analysis>/, "")

  const match = formatted.match(/<summary>([\s\S]*?)<\/summary>/)
  if (match) {
    formatted = `Summary:\n${match[1].trim()}`
  }

  formatted = formatted.replace(/\n\n+/g, "\n\n")
  return formatted.trim()
}
```

### 13.2 清理原則

* `<analysis>` 必須完全刪除
* 只保留 `<summary>` 內容
* 移除多餘空白
* 若 `<summary>` 缺失，視為 compact 失敗

---

## 十四、Continuation Message 規格

壓縮後不直接把 summary 裸塞回去，而是包成延續訊息。

```ts
function getCompactUserSummaryMessage(args: {
  summary: string
  suppressFollowUpQuestions?: boolean
  transcriptPath?: string
  recentMessagesPreserved?: boolean
  proactiveMode?: boolean
}): string {
  let message =
`This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.

${args.summary}`

  if (args.transcriptPath) {
    message += `

If you need specific details from before compaction (like exact code snippets, error messages, or content you generated), read the full transcript at: ${args.transcriptPath}`
  }

  if (args.recentMessagesPreserved) {
    message += `

Recent messages are preserved verbatim.`
  }

  if (args.suppressFollowUpQuestions) {
    message += `

Continue the conversation from where it left off without asking the user any further questions. Resume directly — do not acknowledge the summary, do not recap what was happening, do not preface with "I'll continue" or similar. Pick up the last task as if the break never happened.`
  }

  if (args.proactiveMode) {
    message += `

You are running in autonomous/proactive mode. This is NOT a first wake-up — you were already working autonomously before compaction. Continue your work loop: pick up where you left off based on the summary above. Do not greet the user or ask what to work on.`
  }

  return message
}
```

---

## 十五、上下文重建規格

### 15.1 重建後上下文順序

```text
[原本系統提示]
[必要的開發規則 / 人格 / 專案指令]
[Compact continuation message]
[最近保留的原始 recent messages]
```

### 15.2 原則

* 舊歷史不再完整注入
* 近期訊息保留原文
* 需要精確細節時可回讀 transcript
* 主 agent 恢復後視為同一工作延續，不是新任務開始

---

## 十六、主流程整合

```ts
async function maybeCompactAndContinue(
  state: ConversationState
): Promise<ConversationState> {
  if (!shouldCompact(state.totalTokens)) return state

  const {
    messagesToCompress,
    preservedRecentMessages
  } = splitMessagesForCompaction(state.fullMessages)

  const job: CompactJob = {
    jobId: crypto.randomUUID(),
    mode: "base",
    oldSummary: state.compressedSummary ?? "",
    messagesToCompress,
    preservedRecentMessages,
    suppressFollowUpQuestions: true,
  }

  const rawOutput = await runCompactionSubagent(job)
  const formattedSummary = formatCompactSummary(rawOutput)

  if (!formattedSummary) {
    throw new Error("Compaction failed: empty formatted summary")
  }

  const continuationMessage = getCompactUserSummaryMessage({
    summary: formattedSummary,
    transcriptPath: state.transcriptPath,
    recentMessagesPreserved: true,
    suppressFollowUpQuestions: true,
  })

  return {
    ...state,
    compressedSummary: formattedSummary,
    fullMessages: [
      {
        id: crypto.randomUUID(),
        role: "user",
        content: continuationMessage,
        tokenCount: estimateTokens(continuationMessage),
        createdAt: new Date().toISOString(),
      },
      ...preservedRecentMessages,
    ],
    recentMessages: preservedRecentMessages,
    totalTokens: recalcTokens([continuationMessage, ...preservedRecentMessages.map(m => m.content)]),
    lastCompactedMessageId: messagesToCompress.at(-1)?.id,
  }
}
```

---

## 十七、失敗處理

### 17.1 compact 失敗條件

以下任一成立視為失敗：

* subagent 無回傳文字
* 只有工具呼叫企圖，沒有摘要文字
* 缺少 `<summary>`
* 清理後摘要為空字串

### 17.2 fallback 策略

MVP 可先做以下策略：

1. 重試一次同一 prompt
2. 若仍失敗，改用更簡化 prompt
3. 若仍失敗，拒絕繼續主流程並記錄錯誤

---

## 十八、測試案例

### 18.1 基本測試

* 長對話接近 token 上限時會觸發 compact
* compact 完成後 `<analysis>` 不存在於新上下文
* summary 存在且包含固定 section
* recent messages 仍保留原文

### 18.2 架構測試

* compact 任務由 subagent 執行，不是 main agent
* subagent 沒有工具權限
* main agent compact 前後的工作可延續

### 18.3 精度測試

* 最近使用者要求仍存在於 summary
* 錯誤與修正資訊未丟失
* Current Work 與 Pending Tasks 可用於直接續做

---

## 十九、實作原則

這一版規格的核心原則只有三個：

第一，**壓縮不是主 agent 做，是 compaction subagent 做**。
第二，**壓縮不是一般摘要，是結構化工作狀態重寫**。
第三，**壓縮後不是重新開始，而是無縫接著做**。

---

## 二十、你現在可以直接交給 agent 的實作指令

```text
請實作 Context Compaction 完整架構，要求如下：

1. 新增 Compact Coordinator，負責監控 token、判定 compact、建立 compaction subagent、格式化摘要、重建上下文。
2. 新增 compaction subagent 型別：
   - agentType = "compaction"
   - tools = []
   - disallowedTools = ["*"]
   - maxTurns = 1
3. ConversationState 需支援：
   - fullMessages
   - compressedSummary
   - recentMessages
   - transcriptPath
   - totalTokens
   - lastCompactedMessageId
4. 實作三種 compact prompt：
   - base
   - partial_from
   - partial_up_to
5. prompt 必須強制：
   - 純文字輸出
   - 禁止工具呼叫
   - 輸出 <analysis> + <summary>
6. 實作 formatCompactSummary：
   - 移除 <analysis>
   - 提取 <summary>
   - 清理空白
7. 實作 getCompactUserSummaryMessage：
   - 支援 transcriptPath
   - 支援 recentMessagesPreserved
   - 支援 suppressFollowUpQuestions
   - 支援 proactiveMode
8. compact 後保留最近 8 則訊息原文，其餘以 summary 取代。
9. compact 失敗時需有 retry 與 fallback。
10. 為 compact coordinator、prompt parser、summary injection 寫單元測試。

不要簡化成單一函式版本，必須做成完整主 agent / subagent / coordinator 架構。
```
