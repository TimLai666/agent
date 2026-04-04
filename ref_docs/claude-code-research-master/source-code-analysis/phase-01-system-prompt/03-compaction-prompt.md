# 03 — Context Compaction Prompt 完整分析

> 來源：`src/services/compact/prompt.ts`（374 行）

---

## 一、Compaction 的設計目標

Context compaction 是 Claude Code 讓對話可以無限延伸的核心機制。當對話接近 context limit 時，系統自動觸發壓縮，把對話歷史轉化成一份詳細摘要，再繼續對話。

Compaction prompt 的設計要求：
1. 詳細保留所有技術細節（不只是摘要）
2. 用結構化格式（9 個固定 section）確保資訊完整
3. 強制不使用工具（純文字輸出）
4. 提供「分析草稿」再輸出正式摘要（Chain-of-thought）

---

## 二、NO_TOOLS_PREAMBLE

```typescript
const NO_TOOLS_PREAMBLE = `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

`
```

**設計背景（程式碼注釋解釋）：**
```
// Aggressive no-tools preamble. The cache-sharing fork path inherits the
// parent's full tool set (required for cache-key match), and on Sonnet 4.6+
// adaptive-thinking models the model sometimes attempts a tool call despite
// the weaker trailer instruction. With maxTurns: 1, a denied tool call means
// no text output → falls through to the streaming fallback (2.79% on 4.6 vs
// 0.01% on 4.5). Putting this FIRST and making it explicit about rejection
// consequences prevents the wasted turn.
```

**關鍵工程決策：**
- 原先只有一個「REMINDER」放在末尾，但 Sonnet 4.6 的 adaptive-thinking 仍有 2.79% 會嘗試工具調用
- 改為放在**最前面**（preamble），且明確說明「調用工具會被拒絕，你只有一次機會，失敗了就失敗」
- 效果：從 2.79% 降回接近 0.01%

---

## 三、分析草稿指令（Chain-of-thought）

兩個版本：完整摘要版 vs 部分摘要版

### 3.1 BASE 版（完整對話）

```typescript
const DETAILED_ANALYSIS_INSTRUCTION_BASE = `Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

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
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.`
```

### 3.2 PARTIAL 版（近期訊息）

```typescript
const DETAILED_ANALYSIS_INSTRUCTION_PARTIAL = `... Analyze the recent messages chronologically...`
```

`PARTIAL` 版把「chronologically analyze each message」改為「Analyze the recent messages chronologically」，範圍縮小到最近的訊息。

**Chain-of-Thought 策略：**
`<analysis>` 標籤是讓模型做草稿用的「思考空間」，完成後由 `formatCompactSummary()` 自動移除：

```typescript
formattedSummary = formattedSummary.replace(
  /<analysis>[\s\S]*?<\/analysis>/,
  '',
)
```

---

## 四、三種 Compaction Prompt 變體

### 4.1 BASE_COMPACT_PROMPT（完整對話壓縮）

```typescript
const BASE_COMPACT_PROMPT = `Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

${DETAILED_ANALYSIS_INSTRUCTION_BASE}

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
                       If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.`
```

### 4.2 PARTIAL_COMPACT_PROMPT（近期訊息壓縮）

當使用 `direction: 'from'`（預設），只壓縮最近一段（之前已壓縮的部分不重複處理）：

```
Your task is to create a detailed summary of the RECENT portion of the conversation — the messages that follow earlier retained context. The earlier messages are being kept intact and do NOT need to be summarized...
```

Section 8 的名稱從「Current Work」改為「Current Work: Describe precisely what was being worked on immediately before this summary request.」（簡化版）

### 4.3 PARTIAL_COMPACT_UP_TO_PROMPT（向前壓縮）

當使用 `direction: 'up_to'`，模型只看到摘要前的部分，而更新的訊息在摘要之後：

```
Your task is to create a detailed summary of this conversation. This summary will be placed at the start of a continuing session; newer messages that build on this context will follow after your summary (you do not see them here). Summarize thoroughly so that someone reading only your summary and then the newer messages can fully understand what happened and continue the work.
```

Section 8 改為「Work Completed」，Section 9 改為「Context for Continuing Work」（因為這是要銜接後續訊息的摘要）。

---

## 五、Prompt 組裝函式

### 5.1 完整對話壓縮

```typescript
export function getCompactPrompt(customInstructions?: string): string {
  let prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT

  if (customInstructions && customInstructions.trim() !== '') {
    prompt += `\n\nAdditional Instructions:\n${customInstructions}`
  }

  prompt += NO_TOOLS_TRAILER

  return prompt
}
```

### 5.2 部分對話壓縮

```typescript
export function getPartialCompactPrompt(
  customInstructions?: string,
  direction: PartialCompactDirection = 'from',
): string {
  const template = direction === 'up_to'
    ? PARTIAL_COMPACT_UP_TO_PROMPT
    : PARTIAL_COMPACT_PROMPT
  let prompt = NO_TOOLS_PREAMBLE + template

  if (customInstructions && customInstructions.trim() !== '') {
    prompt += `\n\nAdditional Instructions:\n${customInstructions}`
  }

  prompt += NO_TOOLS_TRAILER
  return prompt
}
```

### 5.3 NO_TOOLS_TRAILER（末尾提醒）

```typescript
const NO_TOOLS_TRAILER =
  '\n\nREMINDER: Do NOT call any tools. Respond with plain text only — ' +
  'an <analysis> block followed by a <summary> block. ' +
  'Tool calls will be rejected and you will fail the task.'
```

**三明治強化：** Preamble（最前） + 正文 + Trailer（最後）雙重強調不使用工具。

---

## 六、壓縮摘要格式化（`formatCompactSummary`）

```typescript
export function formatCompactSummary(summary: string): string {
  let formattedSummary = summary

  // 1. 移除 <analysis> 草稿（只是思考過程，無資訊價值）
  formattedSummary = formattedSummary.replace(
    /<analysis>[\s\S]*?<\/analysis>/,
    '',
  )

  // 2. 展開 <summary> 標籤
  const summaryMatch = formattedSummary.match(/<summary>([\s\S]*?)<\/summary>/)
  if (summaryMatch) {
    const content = summaryMatch[1] || ''
    formattedSummary = formattedSummary.replace(
      /<summary>[\s\S]*?<\/summary>/,
      `Summary:\n${content.trim()}`,
    )
  }

  // 3. 清理多餘空白行
  formattedSummary = formattedSummary.replace(/\n\n+/g, '\n\n')

  return formattedSummary.trim()
}
```

---

## 七、壓縮結果注入（`getCompactUserSummaryMessage`）

壓縮後，摘要被當作「user message」注入對話開頭：

```typescript
export function getCompactUserSummaryMessage(
  summary: string,
  suppressFollowUpQuestions?: boolean,
  transcriptPath?: string,
  recentMessagesPreserved?: boolean,
): string {
  const formattedSummary = formatCompactSummary(summary)

  let baseSummary = `This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.

${formattedSummary}`

  if (transcriptPath) {
    baseSummary += `\n\nIf you need specific details from before compaction (like exact code snippets, error messages, or content you generated), read the full transcript at: ${transcriptPath}`
  }

  if (recentMessagesPreserved) {
    baseSummary += `\n\nRecent messages are preserved verbatim.`
  }

  if (suppressFollowUpQuestions) {
    let continuation = `${baseSummary}
Continue the conversation from where it left off without asking the user any further questions. Resume directly — do not acknowledge the summary, do not recap what was happening, do not preface with "I'll continue" or similar. Pick up the last task as if the break never happened.`

    // Proactive 模式的特殊延續指令
    if ((feature('PROACTIVE') || feature('KAIROS')) && proactiveModule?.isProactiveActive()) {
      continuation += `

You are running in autonomous/proactive mode. This is NOT a first wake-up — you were already working autonomously before compaction. Continue your work loop: pick up where you left off based on the summary above. Do not greet the user or ask what to work on.`
    }

    return continuation
  }

  return baseSummary
}
```

**關鍵設計：**

1. **transcript 路徑：** 如果壓縮前的完整記錄保存到磁碟，會告知模型路徑，讓它在需要時能自行讀取原始細節
2. **suppressFollowUpQuestions：** 自動壓縮時啟用，要求模型「直接繼續，不要確認、不要重述、不要說 I'll continue」
3. **Proactive 模式：** 壓縮後重啟時，明確告知「你已在自主模式工作，這不是第一次喚醒」，防止模型重新問用戶要做什麼

---

## 八、Compaction 觸發條件（從程式碼推斷）

根據 `SUMMARIZE_TOOL_RESULTS_SECTION`：

```typescript
const SUMMARIZE_TOOL_RESULTS_SECTION = `When working with tool results, write down any important information you might need later in your response, as the original tool result may be cleared later.`
```

這行在主系統提示詞中告知模型「工具結果可能被清除」，是為 `CACHED_MICROCOMPACT`（Micro-compaction）設計的。Micro-compaction 只清除舊的工具結果，保留最近 N 個。

### Function Result Clearing（`getFunctionResultClearingSection`）

```typescript
function getFunctionResultClearingSection(model: string): string | null {
  if (!feature('CACHED_MICROCOMPACT') || !getCachedMCConfigForFRC) return null
  const config = getCachedMCConfigForFRC()
  // 檢查是否為支援的模型、是否啟用、是否允許在系統提示中建議摘要
  if (!config.enabled || !config.systemPromptSuggestSummaries || !isModelSupported) return null

  return `# Function Result Clearing

Old tool results will be automatically cleared from context to free up space. The ${config.keepRecent} most recent results are always kept.`
}
```

---

## 九、三層 Compaction 機制總覽

| 類型 | 觸發 | 範圍 | 指令 |
|------|------|------|------|
| Full Compaction | 接近 context limit | 整個對話 | `BASE_COMPACT_PROMPT` |
| Partial Compaction (`from`) | 接近 context limit | 保留早期 + 壓縮近期 | `PARTIAL_COMPACT_PROMPT` |
| Partial Compaction (`up_to`) | 特定分割點 | 壓縮到某個點 | `PARTIAL_COMPACT_UP_TO_PROMPT` |
| Micro-compaction（FRC） | 工具結果太多 | 只清除舊工具結果 | 系統自動，不用 LLM |
| Session Memory | 每 N turns | 在背景更新記憶 | 另見 extractMemories |

---

## 十、9 個 Section 的資訊保留策略分析

| Section | 資訊類型 | 為何重要 |
|---------|---------|---------|
| 1. Primary Request and Intent | 用戶意圖 | 防止在壓縮後偏離原始目標 |
| 2. Key Technical Concepts | 技術背景 | 不重複解釋已建立的知識 |
| 3. Files and Code Sections | 程式碼細節 | 最重要的技術資訊，包含 full code snippets |
| 4. Errors and fixes | 已踩過的坑 | 防止重複犯同樣錯誤 |
| 5. Problem Solving | 解決過程 | 了解問題的 root cause |
| 6. All user messages | 用戶原話 | 防止解釋漂移，保留用戶反饋 |
| 7. Pending Tasks | 待辦事項 | 確保未完成的任務不被遺忘 |
| 8. Current Work | 即時工作狀態 | 壓縮後能直接接著做 |
| 9. Optional Next Step | 直接引用對話原文 | 防止「verbatim」層面的解釋漂移 |

**最關鍵的設計：** Section 9 要求「direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.」— 用引用原文而非摘要，防止摘要過程中意圖漂移。
