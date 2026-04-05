# Context Compaction 策略與 Prompt 分析

## 一、Compact 系統概述

Context Compaction 是當對話歷史接近 context window 上限時，將先前對話壓縮成摘要的機制。主要檔案：`src/services/compact/prompt.ts`（374行）。

## 二、三種 Compact 模式

### 1. BASE COMPACT（完整對話壓縮）
```typescript
export function getCompactPrompt(customInstructions?: string): string
```

觸發時機：整個對話歷史需要壓縮。

摘要結構（9個必填區段）：
1. **Primary Request and Intent** — 用戶明確請求的詳細描述
2. **Key Technical Concepts** — 重要技術概念、框架
3. **Files and Code Sections** — 檢查/修改/建立的檔案（含完整程式碼片段）
4. **Errors and fixes** — 所有錯誤及修復方式
5. **Problem Solving** — 已解決的問題與進行中的除錯
6. **All user messages** — 所有非工具呼叫的用戶訊息（全部列出）
7. **Pending Tasks** — 待完成任務
8. **Current Work** — 摘要前正在進行的確切工作
9. **Optional Next Step** — 下一步（需直接引用最新對話）

### 2. PARTIAL COMPACT FROM（部分對話摘要，from 方向）
```typescript
export function getPartialCompactPrompt(
  customInstructions?: string,
  direction: PartialCompactDirection = 'from',
): string
```

特點：只摘要「保留的舊上下文之後」的近期訊息，舊部分保持原樣。區段與 BASE 相同（第8區為 Current Work，非 Work Completed）。

### 3. PARTIAL COMPACT UP_TO（部分對話摘要，up_to 方向）
```
direction === 'up_to'
```

特點：摘要「將被放置在繼續 session 開頭」的部分，後面會有更新的訊息跟著。第8區改為 **Work Completed**，第9區改為 **Context for Continuing Work**（供後續訊息銜接用）。

## 三、NO_TOOLS_PREAMBLE — 防止工具呼叫

```typescript
const NO_TOOLS_PREAMBLE = `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
`
```

工程背景：Compact 使用 cache-sharing fork（繼承父對話的完整工具集以維持 cache key 匹配），但在 Sonnet 4.6+ 自適應思考模型上，模型偶爾會嘗試工具呼叫（即使有 `maxTurns: 1`）。被拒絕的工具呼叫 = 無文字輸出 = 觸發 streaming fallback（4.6 觀察到 2.79%，4.5 只有 0.01%）。前置強調可防止此浪費。

NO_TOOLS_TRAILER 也在 prompt 結尾重複提醒。

## 四、DETAILED_ANALYSIS_INSTRUCTION — 分析草稿機制

```typescript
const DETAILED_ANALYSIS_INSTRUCTION_BASE = `Before providing your final summary, wrap your analysis in <analysis> tags...
1. Chronologically analyze each message and section...
2. Double-check for technical accuracy and completeness...`
```

模型先在 `<analysis>` 標籤內做內部推理（草稿本），確保覆蓋所有重點，再輸出 `<summary>` 正式內容。

## 五、formatCompactSummary() — 清理輸出

```typescript
export function formatCompactSummary(summary: string): string {
  // 1. 移除 <analysis>...</analysis>（草稿，無資訊價值）
  formattedSummary = formattedSummary.replace(/<analysis>[\s\S]*?<\/analysis>/, '')

  // 2. 提取 <summary>...</summary>，替換為 "Summary:\n{content}"
  // 3. 清理多餘空白行
}
```

`<analysis>` 區塊是「提升摘要品質的推理工具」，不需要出現在最終 context 中。

## 六、getCompactUserSummaryMessage() — 摘要注入訊息

```typescript
export function getCompactUserSummaryMessage(
  summary: string,
  suppressFollowUpQuestions?: boolean,
  transcriptPath?: string,
  recentMessagesPreserved?: boolean,
): string
```

組裝的完整訊息包含：
1. 摘要內文（已格式化）
2. 若有 `transcriptPath`：「如需壓縮前的詳細資訊，請讀取 {path}」
3. 若有 `recentMessagesPreserved`：「近期訊息已原樣保留」
4. 若 `suppressFollowUpQuestions`：「繼續工作，不需詢問用戶」

**KAIROS/PROACTIVE 模式特殊處理**：
```typescript
if ((feature('PROACTIVE') || feature('KAIROS')) && proactiveModule?.isProactiveActive()) {
  continuation += `\n\nYou are running in autonomous/proactive mode. This is NOT a first wake-up — you were already working autonomously before compaction. Continue your work loop...`
}
```

## 七、自訂 Compact 指令支援

使用者可在 CLAUDE.md 或其他地方設定 Compact 指令，這些指令會被追加到 prompt 末尾（在 NO_TOOLS_TRAILER 前）：

```typescript
if (customInstructions && customInstructions.trim() !== '') {
  prompt += `\n\nAdditional Instructions:\n${customInstructions}`
}
```

支援如：
```markdown
## Compact Instructions
When summarizing focus on TypeScript code changes and also remember mistakes and how they were fixed.
```

## 八、設計哲學

### 資訊保真度原則
- 第6區段「All user messages」要求列出所有用戶訊息（非工具結果），確保用戶意圖變化被保留
- 第8區段「Current Work」要求「精確描述」（not vague summary）
- 第9區段「Optional Next Step」要求逐字引用最新對話（防止任務漂移）

### 上下文銜接設計
`transcriptPath` 的存在表明系統承認摘要有資訊損失——對於「壓縮前的精確程式碼片段、錯誤訊息或生成的內容」，提供讀取原始 transcript 的路徑。

### 三種模式的語意差異
- BASE：整個歷史 → 一份摘要
- PARTIAL FROM：保留舊上下文 + 摘要近期 → 舊 + 新摘要
- PARTIAL UP_TO：摘要到某點 → 摘要 + 保留近期原文（適合 cache-hit 場景）
