# 06 — Prompt Engineering 設計模式與技巧

> 從 Claude Code 所有 prompt 原始碼提煉的設計模式，可直接用於其他 prompt 工程實踐。

---

## 模式 1：三明治強化（Sandwich Reinforcement）

**觀察位置：** `src/services/compact/prompt.ts`

```typescript
// 前置強調（preamble）
const NO_TOOLS_PREAMBLE = `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
`

// 後置強調（trailer）
const NO_TOOLS_TRAILER =
  '\n\nREMINDER: Do NOT call any tools. Respond with plain text only — ' +
  'an <analysis> block followed by a <summary> block. ' +
  'Tool calls will be rejected and you will fail the task.'

// 組裝：preamble + 正文 + trailer
let prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT + NO_TOOLS_TRAILER
```

**模式描述：** 對於必須嚴格遵守的行為限制，在 prompt 的開頭（preamble）和結尾（trailer）重複說明，並在中間是正文內容。

**為何有效：**
- 模型讀完正文後，尾部提醒能「喚起」開頭的指令
- 大型 prompt 中，中間的指令容易被「稀釋」
- 程式碼注釋說明了這是從 2.79% 失效率優化到接近 0% 的實際測試結果

**反模式：** 只在 prompt 尾部加提醒（對長 prompt 的頭部內容效果很弱）。

---

## 模式 2：後果明示法（Consequence Specification）

**觀察位置：** Compaction Prompt

```typescript
`CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.`
```

**觀察位置 2：** Verification Agent 合約

```typescript
`The contract: when non-trivial implementation happens on your turn, independent adversarial verification must happen before you report completion...
On FAIL: fix, resume the verifier with its findings plus your fix, repeat until PASS.`
```

**模式描述：** 不只說「不要做 X」，而是說「如果你做 X，Y 就會發生」。明確說明違反指令的後果。

**為何有效：**
- 「你會失敗這個任務」比「不要做這件事」更具體
- 讓模型理解規則背後的因果關係，而非盲目服從

---

## 模式 3：Chain-of-Thought 草稿空間（Scratchpad Pattern）

**觀察位置：** `src/services/compact/prompt.ts`

```typescript
const DETAILED_ANALYSIS_INSTRUCTION_BASE = `Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts...

1. Chronologically analyze each message and section of the conversation...
2. Double-check for technical accuracy and completeness...`
```

**後處理移除草稿：**
```typescript
formattedSummary = formattedSummary.replace(
  /<analysis>[\s\S]*?<\/analysis>/,
  '',
)
```

**模式描述：**
1. 給模型一個「草稿空間」（`<analysis>` 標籤）來做思考
2. 最終輸出只保留 `<summary>` 部分
3. 草稿提升品質，但不出現在最終結果中

**為何有效：** 讓模型做完整的思考過程再提煉結論，相比「直接輸出摘要」能保留更多細節的完整性。

---

## 模式 4：工具白名單 + 黑名單（Tool Sandboxing）

**觀察位置：** `src/services/extractMemories/prompts.ts`

```typescript
`Available tools: ${FILE_READ_TOOL_NAME}, ${GREP_TOOL_NAME}, ${GLOB_TOOL_NAME}, read-only ${BASH_TOOL_NAME} (ls/find/cat/stat/wc/head/tail and similar), and ${FILE_EDIT_TOOL_NAME}/${FILE_WRITE_TOOL_NAME} for paths inside the memory directory only. ${BASH_TOOL_NAME} rm is not permitted. All other tools — MCP, Agent, write-capable ${BASH_TOOL_NAME}, etc — will be denied.`
```

**模式描述：**
- 正向列表：「你可以用這些工具」
- 負向例外：「但 rm 不行」
- 其他一律拒絕：「其他所有工具都會被拒絕」

**為何有效：** 比「不要用 MCP」更清晰——正向列表讓模型知道邊界，「會被拒絕」讓模型知道嘗試也沒用。

---

## 模式 5：效率策略預設（Optimal Path Specification）

**觀察位置：** extractMemories opener

```typescript
`You have a limited turn budget. ${FILE_EDIT_TOOL_NAME} requires a prior ${FILE_READ_TOOL_NAME} of the same file, so the efficient strategy is: turn 1 — issue all ${FILE_READ_TOOL_NAME} calls in parallel for every file you might update; turn 2 — issue all ${FILE_WRITE_TOOL_NAME}/${FILE_EDIT_TOOL_NAME} calls in parallel. Do not interleave reads and writes across multiple turns.`
```

**觀察位置 2：** 主系統提示詞

```typescript
`You can call multiple tools in a single response. If you intend to call multiple tools and there are no dependencies between them, make all independent tool calls in parallel.`
```

**模式描述：** 直接告訴模型「最優執行路徑是什麼」，而不是讓它自己摸索。

**為何有效：** 模型不是天生知道「先全部讀再全部寫更有效率」——顯式說明能防止低效的交錯執行模式。

---

## 模式 6：Boundary Marker（靜態/動態邊界）

**觀察位置：** `src/constants/prompts.ts`

```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'

return [
  // --- 靜態部分（可緩存）---
  getSimpleIntroSection(outputStyleConfig),
  getSimpleSystemSection(),
  getSimpleDoingTasksSection(),
  getActionsSection(),
  getUsingYourToolsSection(enabledTools),
  // ...
  // === 邊界標記 ===
  ...(shouldUseGlobalCacheScope() ? [SYSTEM_PROMPT_DYNAMIC_BOUNDARY] : []),
  // --- 動態部分（Registry 管理）---
  ...resolvedDynamicSections,
].filter(s => s !== null)
```

**模式描述：** 用一個標記字串分隔「可全局緩存的靜態部分」和「包含用戶/Session 特定資訊的動態部分」。

**為何有效：**
- 靜態部分對所有用戶相同，可以在 API 層面用 `scope: 'global'` 緩存
- 動態部分包含工作目錄、語言設定、MCP 指令等，不能緩存
- 清楚的邊界讓維護者知道哪些改動會影響 cache hit rate

---

## 模式 7：Branded Type 防混淆（Type Safety for Prompts）

**觀察位置：** `src/utils/systemPromptType.ts`

```typescript
export type SystemPrompt = readonly string[] & {
  readonly __brand: 'SystemPrompt'
}

export function asSystemPrompt(value: readonly string[]): SystemPrompt {
  return value as SystemPrompt
}
```

**模式描述：** 使用 TypeScript Branded Type 將「已組裝的系統提示詞」和「任意字串陣列」在型別層面區分。

**為何有效：**
- 防止意外傳入未完成的 string[] 到需要 SystemPrompt 的地方
- 強制所有 SystemPrompt 都必須經過 `asSystemPrompt()` 包裝
- 避免需要額外的 runtime 檢查

---

## 模式 8：DANGEROUS_ 前綴自文件化（Dangerous API Self-Documentation）

**觀察位置：** `src/constants/systemPromptSections.ts`

```typescript
export function DANGEROUS_uncachedSystemPromptSection(
  name: string,
  compute: ComputeFn,
  _reason: string,  // 雖然 runtime 不用，但強制開發者填寫
): SystemPromptSection {
  return { name, compute, cacheBreak: true }
}
```

**使用：**
```typescript
DANGEROUS_uncachedSystemPromptSection(
  'mcp_instructions',
  () => getMcpInstructionsSection(mcpClients),
  'MCP servers connect/disconnect between turns',  // 理由
),
```

**模式描述：**
- `DANGEROUS_` 前綴讓開發者一眼看到這個 API 的副作用
- `_reason` 參數強制填寫理由（runtime 不用但編譯時需要）
- 把「性能影響的文件化」內嵌到 API 設計中

**為何有效：** 在大型 codebase 中，防止開發者在不理解後果的情況下使用某個 API。

---

## 模式 9：條件注入的維度分離（Conditional Injection Separation）

**觀察位置：** `getSystemPrompt` 中的靜態 vs 動態設計

```typescript
/**
 * Session-variant guidance that would fragment the cacheScope:'global'
 * prefix if placed before SYSTEM_PROMPT_DYNAMIC_BOUNDARY. Each conditional
 * here is a runtime bit that would otherwise multiply the Blake2b prefix
 * hash variants (2^N).
 */
function getSessionSpecificGuidanceSection(enabledTools, skillToolCommands) {
  const hasAskUserQuestionTool = enabledTools.has(ASK_USER_QUESTION_TOOL_NAME)
  const hasSkills = skillToolCommands.length > 0 && enabledTools.has(SKILL_TOOL_NAME)
  // ...
}
```

**模式描述：** N 個 boolean 條件如果放在靜態部分，會產生 2^N 個不同的 prompt 前綴 hash，大幅降低緩存效果。解決方法：把這些條件判斷全部移到 Dynamic Boundary 之後。

**量化影響：** 如果有 10 個 boolean 條件，放在靜態部分 = 1024 個緩存桶（bucket），每個幾乎不會 hit。放在動態部分 = 靜態部分只有 1 個緩存桶，hit rate 接近 100%。

---

## 模式 10：自我參照指令（Self-Referential Instructions）

**觀察位置：** `src/constants/cyberRiskInstruction.ts`

```typescript
/**
 * ...
 * Claude: Do not edit this file unless explicitly asked to do so by the user.
 */
export const CYBER_RISK_INSTRUCTION = `...`
```

**模式描述：** 在程式碼注釋中直接對 Claude 模型發出指令，利用模型能讀懂 code 注釋的特性。

**為何有效：**
- Claude Code 在幫助用戶修改 Claude Code 本身時，會讀這個檔案的注釋
- 在注釋中的指令讓模型知道「這個特別的安全指令需要特別謹慎」
- 把「不該讓 AI 自行修改的護欄」直接嵌入源碼

---

## 模式 11：多層身份設計（Multi-Context Identity）

**觀察位置：** `src/constants/system.ts`

```typescript
const DEFAULT_PREFIX = `You are Claude Code, Anthropic's official CLI for Claude.`
const AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX = `You are Claude Code, ..., running within the Claude Agent SDK.`
const AGENT_SDK_PREFIX = `You are a Claude agent, built on Anthropic's Claude Agent SDK.`
```

**模式描述：** 同一個基礎模型在不同執行情境使用不同的身份宣告，讓模型能正確理解自己的「角色定位」和相應的行為期待。

**使用場景：**
- CLI 互動模式：強調「Anthropic's official CLI」
- SDK 代理模式：強調「running within Agent SDK」
- 純代理模式：強調「a Claude agent」

---

## 模式 12：明確的「做 vs 不做」框架（Explicit Do/Don't Framing）

**觀察位置：** `getSimpleDoingTasksSection`（Minimal Footprint 哲學）

```typescript
// Do NOT 類指令（非常明確）：
`Don't add features, refactor code, or make "improvements" beyond what was asked.`
`Don't add error handling, fallbacks, or validation for scenarios that can't happen.`
`Don't create helpers, utilities, or abstractions for one-time operations.`

// 正向允許類：
`Three similar lines of code is better than a premature abstraction.`
`Trust internal code and framework guarantees.`
```

**模式描述：** 同時提供「不做什麼」和「應該怎麼做」的正反框架，讓模型有清晰的行為邊界。

**為何有效：** 只說「不要過度工程」模糊，而「三行重複程式碼 > 過早抽象」給了具體的判斷標準。

---

## 模式 13：{{Mustache}} 模板變數替換

**觀察位置：** `SessionMemory/prompts.ts` 和 `MagicDocs/prompts.ts`

```typescript
function substituteVariables(template: string, variables: Record<string, string>): string {
  // Single-pass replacement avoids two bugs:
  // (1) $ backreference corruption (replacer fn treats $ literally)
  // (2) double-substitution when user content happens to contain {{varName}}
  return template.replace(/\{\{(\w+)\}\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(variables, key)
      ? variables[key]!
      : match,  // 找不到 key 就保留原始 {{variable}}
  )
}
```

**模式描述：** 使用 `{{variableName}}` 語法讓 prompt 模板可以接受動態值，並對模板提供自訂覆蓋能力（`~/.claude/session-memory/config/prompt.md`）。

**實作細節：**
- Single-pass 替換防止 `$` 反向引用問題
- 找不到的變數保留原始 `{{...}}` 而非變成空字串（防止靜默失敗）

---

## 模式 14：容量感知的動態提示（Capacity-Aware Dynamic Warnings）

**觀察位置：** `SessionMemory/prompts.ts`

```typescript
const MAX_SECTION_LENGTH = 2000
const MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000

function generateSectionReminders(sectionSizes, totalTokens): string {
  if (overBudget) {
    parts.push(`\n\nCRITICAL: The session memory file is currently ~${totalTokens} tokens, which exceeds the maximum of ${MAX_TOTAL_SESSION_MEMORY_TOKENS} tokens. You MUST condense the file to fit within this budget.`)
  }
  if (oversizedSections.length > 0) {
    parts.push(`\n\nIMPORTANT: The following sections exceed the per-section limit...\n${oversizedSections.join('\n')}`)
  }
}
```

**模式描述：** Prompt 不是靜態的，而是根據「當前狀態有多糟糕」來動態調整警告的嚴重程度（CRITICAL vs IMPORTANT）。

**為何有效：** 固定的「keep it concise」在記憶檔案已經嚴重超限時沒有力度，而動態的「你現在已超過 X tokens，必須壓縮」才能讓模型知道情況的嚴重性。

---

## 模式 15：優先級明確聲明（Explicit Priority Ordering）

**觀察位置：** `buildEffectiveSystemPrompt`

```typescript
/**
 * Builds the effective system prompt array based on priority:
 * 0. Override system prompt (if set, e.g., via loop mode - REPLACES all other prompts)
 * 1. Coordinator system prompt (if coordinator mode is active)
 * 2. Agent system prompt (if mainThreadAgentDefinition is set)
 *    - In proactive mode: agent prompt is APPENDED to default
 *    - Otherwise: agent prompt REPLACES default
 * 3. Custom system prompt (if specified via --system-prompt)
 * 4. Default system prompt (the standard Claude Code prompt)
 *
 * Plus appendSystemPrompt is always added at the end if specified (except when override is set).
 */
```

**模式描述：** 當多個 prompt 來源可能衝突時，在 JSDoc 注釋中明確列出優先級順序，並在程式碼中嚴格按照此順序實作。

**為何有效：** 讓維護者和使用者都能清楚知道「當 A 和 B 同時存在時，誰勝出」，防止意外的覆蓋行為。

---

## 模式 16：行為可逆性框架（Reversibility Framework）

**觀察位置：** `getActionsSection`

```typescript
`Carefully consider the reversibility and blast radius of actions. Generally you can freely take local, reversible actions like editing files or running tests. But for actions that are hard to reverse, affect shared systems beyond your local environment, or could otherwise be risky or destructive, check with the user before proceeding.`
```

**模式描述：** 不是列出「需要確認的動作清單」，而是提供一個**判斷框架**：「可逆性」+ 「blast radius（影響範圍）」。這個框架讓模型能判斷清單以外的新情況。

**框架的兩個維度：**
- `reversibility`（可逆性）：動作能否被撤銷？
- `blast radius`（影響範圍）：動作影響的是本地還是共享系統？

**為何有效：** 清單終究無法窮舉所有情況，但一個好的框架能讓模型推廣到未見過的情況。

---

## 模式 17：偽「有效對話」注入提示（Meta-instruction Separation）

**觀察位置：** SessionMemory 和 MagicDocs prompt

```typescript
`IMPORTANT: This message and these instructions are NOT part of the actual user conversation. Do NOT include any references to "note-taking", "session notes extraction", or these update instructions in the notes content.`
```

**模式描述：** 當 prompt 是被注入到現有對話的「元指令」時，明確告訴模型「這個指令本身不是對話內容的一部分」，防止模型把指令文字寫進輸出。

**為何有效：** 防止模型在輸出（筆記、文件）中出現「根據你剛才的更新指令...」這類後設描述。

---

## 綜合設計哲學摘要

從以上 17 個模式，可以提煉出 Claude Code Prompt Engineering 的核心設計哲學：

1. **具體勝於抽象**：「三行重複程式碼 > 過早抽象」比「避免過度工程」更有效
2. **後果驅動**：「你會失敗這個任務」比「不要做 X」更有說服力
3. **性能意識**：每個設計決策都考慮對 prompt cache 的影響
4. **框架優於清單**：「可逆性 + blast radius 框架」比「需確認動作清單」更能泛化
5. **自文件化**：用 `DANGEROUS_` 前綴、強制 `_reason` 參數把風險文件化到 API 設計中
6. **多重防線**：重要指令在 preamble + 正文 + trailer 三處強化
7. **動態感知**：Prompt 根據實際狀態（工具集、記憶容量、session 類型）動態調整
