# 07 — Context Compaction 作為成本節約的手段

## 概述

Context Compaction（對話壓縮）是 Claude Code 最重要的成本控制機制之一。當對話 context 超出模型 context window 的特定比例時，自動將歷史對話壓縮為結構化摘要，減少後續 API 呼叫的 input token 數量，從而大幅降低成本。

---

## 一、Compact Prompt 設計（compact/prompt.ts）

### 三種 Compact 模式

**1. 全量壓縮（`getCompactPrompt`）**

對整個對話歷史執行壓縮：

```typescript
export function getCompactPrompt(customInstructions?: string): string {
  let prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT
  if (customInstructions?.trim() !== '') {
    prompt += `\n\nAdditional Instructions:\n${customInstructions}`
  }
  prompt += NO_TOOLS_TRAILER
  return prompt
}
```

**2. 部分壓縮 - 正向（`direction: 'from'`）**

保留早期訊息，壓縮最近的訊息：

```typescript
const PARTIAL_COMPACT_PROMPT = `Your task is to create a detailed summary of the RECENT portion of the conversation...`
// 摘要只涵蓋 "recent messages"，早期訊息保持原樣
```

**3. 部分壓縮 - 反向（`direction: 'up_to'`）**

壓縮早期訊息，保留最近訊息：

```typescript
const PARTIAL_COMPACT_UP_TO_PROMPT = `Your task is to create a detailed summary of this conversation.
This summary will be placed at the start of a continuing session; newer messages that build on this
context will follow after your summary...`
// 用於 cache-sharing fork path，摘要會置於對話開頭
```

---

## 二、NO_TOOLS_PREAMBLE — 成本最佳化的細節

```typescript
const NO_TOOLS_PREAMBLE = `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
`
```

**設計背景（程式碼注釋揭示）**：

> Aggressive no-tools preamble. The cache-sharing fork path inherits the parent's full tool set (required for cache-key match), and on Sonnet 4.6+ adaptive-thinking models the model sometimes attempts a tool call despite the weaker trailer instruction. With maxTurns: 1, a denied tool call means no text output → falls through to the streaming fallback (2.79% on 4.6 vs 0.01% on 4.5).

cache-sharing fork 繼承了父 agent 的完整工具集（維持快取 key 匹配），但 Sonnet 4.6 的 adaptive thinking 偶爾會嘗試呼叫工具。在 `maxTurns: 1` 下工具呼叫被拒絕 = 無文字輸出 = 回退到備援路徑，在 4.6 上發生率 2.79%（vs 4.5 的 0.01%）。

此 preamble 放在最前面以強調重要性，搭配結尾的 `NO_TOOLS_TRAILER` 再次提醒，將失敗率從 2.79% 大幅降低。

---

## 三、壓縮摘要的結構

BASE_COMPACT_PROMPT 要求 9 個標準段落：

1. **Primary Request and Intent** — 用戶需求
2. **Key Technical Concepts** — 技術概念清單
3. **Files and Code Sections** — 關鍵檔案與程式碼片段
4. **Errors and fixes** — 錯誤與修復記錄
5. **Problem Solving** — 問題解決過程
6. **All user messages** — 所有用戶訊息（非 tool result）
7. **Pending Tasks** — 待完成任務
8. **Current Work** — 當前工作狀態
9. **Optional Next Step** — 下一步行動（需引用原文）

**`<analysis>` 區塊設計**：

```typescript
export function formatCompactSummary(summary: string): string {
  // 移除 <analysis> 區塊（這是 scratchpad，對後續 context 無資訊價值）
  formattedSummary = formattedSummary.replace(
    /<analysis>[\s\S]*?<\/analysis>/,
    '',
  )
  // ...
}
```

`<analysis>` 是模型的「草稿空間」，提高摘要品質但不會出現在最終注入 context 的摘要中，因此不消耗後續 API 呼叫的 input tokens。

---

## 四、壓縮後的 Context 重建

```typescript
export function getCompactUserSummaryMessage(
  summary: string,
  suppressFollowUpQuestions?: boolean,
  transcriptPath?: string,
  recentMessagesPreserved?: boolean,
): string {
  const formattedSummary = formatCompactSummary(summary)

  let baseSummary = `This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.\n\n${formattedSummary}`

  // 完整 transcript 的路徑（供查詢細節）
  if (transcriptPath) {
    baseSummary += `\n\nIf you need specific details from before compaction (like exact code snippets, error messages, or content you generated), read the full transcript at: ${transcriptPath}`
  }

  // 如果保留了最近訊息則標記
  if (recentMessagesPreserved) {
    baseSummary += `\n\nRecent messages are preserved verbatim.`
  }

  // 非互動模式：直接繼續，不提問
  if (suppressFollowUpQuestions) {
    return `${baseSummary}\nContinue the conversation from where it left off without asking the user any further questions...`
  }
}
```

---

## 五、Proactive Mode 整合

```typescript
// Dead code elimination: conditional import for proactive mode
const proactiveModule =
  feature('PROACTIVE') || feature('KAIROS')
    ? require('../../proactive/index.js')
    : null

// Proactive mode 下的 compaction 繼續行為
if ((feature('PROACTIVE') || feature('KAIROS')) && proactiveModule?.isProactiveActive()) {
  continuation += `
You are running in autonomous/proactive mode. This is NOT a first wake-up — you were already working autonomously before compaction. Continue your work loop: pick up where you left off based on the summary above. Do not greet the user or ask what to work on.`
}
```

Proactive 模式（自主執行模式）在壓縮後明確指示模型繼續自主工作，不重新問用戶需求。

---

## 六、與快取的交互（成本最佳化的核心）

**promptCacheBreakDetection.ts 中的 compaction 通知：**

```typescript
export function notifyCompaction(querySource: QuerySource, agentId?: AgentId): void {
  const key = getTrackingKey(querySource, agentId)
  const state = key ? previousStateBySource.get(key) : undefined
  if (state) {
    state.prevCacheReadTokens = null  // 重置 cache break 偵測基線
  }
}
```

壓縮後 `prevCacheReadTokens` 重置為 null，避免將正常的 cache read 下降誤報為 cache break。

**cache-sharing fork path：**

Compact 請求繼承父 agent 的完整工具集和系統提示，確保與主 thread 共享同一份 prompt cache，避免為 compact 操作單獨付出 cache creation 費用。

---

## 七、成本節約機制分析

### 直接成本節約

假設對話已累積 150K tokens：
- 壓縮後摘要約 5-10K tokens
- 後續每次 API 呼叫節省 140K input tokens
- 以 Sonnet 定價：每次節省 $0.42（140K × $3/1M）
- 如有快取命中：每次節省 $0.04x（140K × $0.30/1M）

### 間接成本節約

1. **避免 context window 超限**：超限會導致整個 session 無法繼續，不得不重新開始
2. **維持快取命中率**：較短的 context 更容易被完整快取
3. **減少重試成本**：較小的請求更不容易超時

### 壓縮本身的成本

- 壓縮操作需要一次完整的 API 呼叫（送入完整 context 換出摘要）
- 以 150K tokens 的 context 為例，壓縮成本約 $0.45（Sonnet input）+ 少量 output
- 此後每次對話節省 $0.42，**1-2 輪對話後回本**

---

## 八、Custom Instructions 整合

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

用戶可在 CLAUDE.md 中設定壓縮指令，例如：
```
## Compact Instructions
When summarizing the conversation focus on typescript code changes and also remember the mistakes you made and how you fixed them.
```

---

## 九、小結

| 功能 | 說明 |
|------|------|
| 壓縮模式 | 全量 / 部分-from / 部分-up_to |
| 成本節約原理 | 將歷史 context 壓縮為結構化摘要，大幅減少後續 input tokens |
| 快取整合 | cache-sharing fork 繼承父 tool set；compaction 後重置 cache break 基線 |
| 品質保障 | `<analysis>` scratchpad 提升摘要品質但不留在 context 中 |
| No-tools 設計 | Preamble + Trailer 雙重強調，防止 Sonnet 4.6 adaptive thinking 觸發工具呼叫 |
| 回本時間 | 約 1-2 輪對話後節省成本超過壓縮操作本身的費用 |
