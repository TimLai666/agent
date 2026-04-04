# 04 — 輔助 Prompt 集合分析

> 來源：`extractMemories/prompts.ts`、`SessionMemory/prompts.ts`、`MagicDocs/prompts.ts`、`buddy/prompt.ts`、`claudeInChrome/prompt.ts`

---

## 一、extractMemories — 記憶提取 Prompt

> 來源：`src/services/extractMemories/prompts.ts`

### 1.1 架構設計

```typescript
/**
 * The extraction agent runs as a perfect fork of the main conversation — same
 * system prompt, same message prefix. The main agent's system prompt always
 * has full save instructions; when the main agent writes memories itself,
 * extractMemories.ts skips that turn (hasMemoryWritesSince). This prompt
 * fires only when the main agent didn't write, so the save-criteria here
 * overlap the system prompt's harmlessly.
 */
```

**設計亮點：** 記憶提取代理是主對話的「完美 fork」——使用完全相同的系統提示和訊息前綴。只有當主代理在本輪沒有自行寫入記憶時，才觸發提取代理。這樣避免重複寫入，同時確保記憶被捕捉。

### 1.2 opener 函式（兩種變體的共用開頭）

```typescript
function opener(newMessageCount: number, existingMemories: string): string {
  const manifest = existingMemories.length > 0
    ? `\n\n## Existing memory files\n\n${existingMemories}\n\nCheck this list before writing — update an existing file rather than creating a duplicate.`
    : ''
  return [
    `You are now acting as the memory extraction subagent. Analyze the most recent ~${newMessageCount} messages above and use them to update your persistent memory systems.`,
    '',
    `Available tools: ${FILE_READ_TOOL_NAME}, ${GREP_TOOL_NAME}, ${GLOB_TOOL_NAME}, read-only ${BASH_TOOL_NAME} (ls/find/cat/stat/wc/head/tail and similar), and ${FILE_EDIT_TOOL_NAME}/${FILE_WRITE_TOOL_NAME} for paths inside the memory directory only. ${BASH_TOOL_NAME} rm is not permitted. All other tools — MCP, Agent, write-capable ${BASH_TOOL_NAME}, etc — will be denied.`,
    '',
    `You have a limited turn budget. ${FILE_EDIT_TOOL_NAME} requires a prior ${FILE_READ_TOOL_NAME} of the same file, so the efficient strategy is: turn 1 — issue all ${FILE_READ_TOOL_NAME} calls in parallel for every file you might update; turn 2 — issue all ${FILE_WRITE_TOOL_NAME}/${FILE_EDIT_TOOL_NAME} calls in parallel. Do not interleave reads and writes across multiple turns.`,
    '',
    `You MUST only use content from the last ~${newMessageCount} messages to update your persistent memories. Do not waste any turns attempting to investigate or verify that content further — no grepping source files, no reading code to confirm a pattern exists, no git commands.` + manifest,
  ].join('\n')
}
```

**精心設計的工具限制：**
- 允許：讀取工具、在記憶目錄內的寫入工具、只讀 Bash（ls/cat/stat 等）
- 禁止：MCP 工具、Agent 工具、`rm`、任何寫入到非記憶目錄的操作

**Two-turn 效率策略：**
明確告訴模型最優執行順序：Turn 1 並行讀所有要更新的檔案，Turn 2 並行寫。防止模型「read → write → read → write」的低效交錯模式。

### 1.3 Auto-only 版本（`buildExtractAutoOnlyPrompt`）

```typescript
export function buildExtractAutoOnlyPrompt(
  newMessageCount: number,
  existingMemories: string,
  skipIndex = false,
): string {
  const howToSave = skipIndex
    ? [
        '## How to save memories',
        'Write each memory to its own file (e.g., user_role.md, feedback_testing.md) using this frontmatter format:',
        ...MEMORY_FRONTMATTER_EXAMPLE,
        '- Organize memory semantically by topic, not chronologically',
        '- Update or remove memories that turn out to be wrong or outdated',
        '- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.',
      ]
    : [
        '## How to save memories',
        'Saving a memory is a two-step process:',
        '**Step 1** — write the memory to its own file...',
        '**Step 2** — add a pointer to that file in MEMORY.md. MEMORY.md is an index, not a memory — each entry should be one line, under ~150 characters: - [Title](file.md) — one-line hook. It has no frontmatter. Never write memory content directly into MEMORY.md.',
        '- MEMORY.md is always loaded into your system prompt — lines after 200 will be truncated, so keep the index concise',
      ]

  return [
    opener(newMessageCount, existingMemories),
    '',
    'If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.',
    '',
    ...TYPES_SECTION_INDIVIDUAL,
    ...WHAT_NOT_TO_SAVE_SECTION,
    '',
    ...howToSave,
  ].join('\n')
}
```

**MEMORY.md 索引設計：**
- 200 行截斷限制（會載入系統提示詞）
- 每條目不超過 150 字元
- 格式：`- [Title](file.md) — one-line hook`
- MEMORY.md 只是索引，不存實際記憶內容

### 1.4 Combined 版本（Auto + Team Memory）

```typescript
export function buildExtractCombinedPrompt(...): string {
  if (!feature('TEAMMEM')) {
    return buildExtractAutoOnlyPrompt(...)
  }
  // Team memory 特有規則：
  '- You MUST avoid saving sensitive data within shared team memories. For example, never save API keys or user credentials.',
  // per-type <scope> 指引（決定存入 private 還是 team 目錄）
}
```

Team memory 模式新增安全規則：禁止在共享記憶中存儲敏感資料（API keys、憑據）。

---

## 二、SessionMemory — Session 記憶 Prompt

> 來源：`src/services/SessionMemory/prompts.ts`

### 2.1 預設模板結構

```typescript
export const DEFAULT_SESSION_MEMORY_TEMPLATE = `
# Session Title
_A short and distinctive 5-10 word descriptive title for the session. Super info dense, no filler_

# Current State
_What is actively being worked on right now? Pending tasks not yet completed. Immediate next steps._

# Task specification
_What did the user ask to build? Any design decisions or other explanatory context_

# Files and Functions
_What are the important files? In short, what do they contain and why are they relevant?_

# Workflow
_What bash commands are usually run and in what order? How to interpret their output if not obvious?_

# Errors & Corrections
_Errors encountered and how they were fixed. What did the user correct? What approaches failed and should not be tried again?_

# Codebase and System Documentation
_What are the important system components? How do they work/fit together?_

# Learnings
_What has worked well? What has not? What to avoid? Do not duplicate items from other sections_

# Key results
_If the user asked a specific output such as an answer to a question, a table, or other document, repeat the exact result here_

# Worklog
_Step by step, what was attempted, done? Very terse summary for each step_
`
```

**設計特點：** 每個 section 都有 `_italicized description_` 作為模板指令，這些描述行必須被保留，不能被修改（更新規則裡特別強調這點）。

### 2.2 Update Prompt 的結構保留規則

```typescript
function getDefaultUpdatePrompt(): string {
  return `IMPORTANT: This message and these instructions are NOT part of the actual user conversation. Do NOT include any references to "note-taking", "session notes extraction", or these update instructions in the notes content.

...

CRITICAL RULES FOR EDITING:
- The file must maintain its exact structure with all sections, headers, and italic descriptions intact
-- NEVER modify, delete, or add section headers (the lines starting with '#' like # Task specification)
-- NEVER modify or delete the italic _section description_ lines
-- The italic _section descriptions_ are TEMPLATE INSTRUCTIONS that must be preserved exactly as-is
-- ONLY update the actual content that appears BELOW the italic _section descriptions_ within each existing section
-- Do NOT add any new sections, summaries, or information outside the existing structure
- Do NOT reference this note-taking process or instructions anywhere in the notes
- It's OK to skip updating a section if there are no substantial new insights to add. Do not add filler content like "No info yet", just leave sections blank/unedited if appropriate.
- Write DETAILED, INFO-DENSE content for each section - include specifics like file paths, function names, error messages, exact commands, technical details, etc.
- For "Key results", include the complete, exact output the user requested
- Keep each section under ~${MAX_SECTION_LENGTH} tokens/words
- IMPORTANT: Always update "Current State" to reflect the most recent work - this is critical for continuity after compaction`
}
```

**最重要的規則：** 「Current State」section 必須總是被更新，這是 compaction 後恢復的關鍵。

### 2.3 容量管理

```typescript
const MAX_SECTION_LENGTH = 2000  // tokens/words per section
const MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000

function generateSectionReminders(sectionSizes, totalTokens): string {
  const overBudget = totalTokens > MAX_TOTAL_SESSION_MEMORY_TOKENS
  // 超過總預算 → CRITICAL 提醒，必須壓縮
  // 某 section 超過 2000 → IMPORTANT 提醒，必須壓縮
}
```

**容量控制策略：**
- 每個 section 2000 token 上限
- 整體 12000 token 上限
- 超限時動態生成警告，加入更新 prompt

### 2.4 可自訂性

```typescript
export async function loadSessionMemoryTemplate(): Promise<string> {
  const templatePath = join(getClaudeConfigHomeDir(), 'session-memory', 'config', 'template.md')
  // 讀取 ~/.claude/session-memory/config/template.md
  // 不存在則用預設模板
}

export async function loadSessionMemoryPrompt(): Promise<string> {
  const promptPath = join(getClaudeConfigHomeDir(), 'session-memory', 'config', 'prompt.md')
  // 讀取 ~/.claude/session-memory/config/prompt.md
  // 不存在則用預設 prompt
}
```

用戶可以用 `{{variableName}}` 語法自訂 prompt 模板（substitution 變數：`currentNotes`、`notesPath`）。

---

## 三、MagicDocs — 文件更新 Prompt

> 來源：`src/services/MagicDocs/prompts.ts`

### 3.1 主 Prompt 模板

```typescript
function getUpdatePromptTemplate(): string {
  return `IMPORTANT: This message and these instructions are NOT part of the actual user conversation. Do NOT include any references to "documentation updates", "magic docs", or these update instructions in the document content.

Based on the user conversation above (EXCLUDING this documentation update instruction message), update the Magic Doc file to incorporate any NEW learnings, insights, or information that would be valuable to preserve.

...

CRITICAL RULES FOR EDITING:
- Preserve the Magic Doc header exactly as-is: # MAGIC DOC: {{docTitle}}
- Keep the document CURRENT with the latest state of the codebase - this is NOT a changelog or history
- Update information IN-PLACE to reflect the current state - do NOT append historical notes or track changes over time
- Remove or replace outdated information rather than adding "Previously..." or "Updated to..." notes
- Clean up or DELETE sections that are no longer relevant...

DOCUMENTATION PHILOSOPHY - READ CAREFULLY:
- BE TERSE. High signal only. No filler words or unnecessary elaboration.
- Documentation is for OVERVIEWS, ARCHITECTURE, and ENTRY POINTS - not detailed code walkthroughs
- Do NOT duplicate information that's already obvious from reading the source code
- Focus on: WHY things exist, HOW components connect, WHERE to start reading, WHAT patterns are used
- Skip: detailed implementation steps, exhaustive API docs, play-by-play narratives`
}
```

### 3.2 What TO / NOT TO Document

**要寫的：**
```
- High-level architecture and system design
- Non-obvious patterns, conventions, or gotchas
- Key entry points and where to start reading code
- Important design decisions and their rationale
- Critical dependencies or integration points
- References to related files, docs, or code (like a wiki)
```

**不要寫的：**
```
- Anything obvious from reading the code itself
- Exhaustive lists of files, functions, or parameters
- Step-by-step implementation details
- Low-level code mechanics
- Information already in CLAUDE.md or other project docs
```

**設計哲學：** MagicDocs 的重點是「不重複」——不重複程式碼本身已能表達的東西，也不重複 CLAUDE.md 已有的東西。只記錄「WHY」和「HOW components connect」。

### 3.3 文件特定指令（自訂優先）

```typescript
const customInstructions = instructions
  ? `

DOCUMENT-SPECIFIC UPDATE INSTRUCTIONS:
The document author has provided specific instructions for how this file should be updated. Pay extra attention to these instructions and follow them carefully:

"${instructions}"

These instructions take priority over the general rules below.`
  : ''
```

可以對每份 MagicDoc 設定特定的更新指令，且這些指令優先於通用規則。

### 3.4 可自訂性

```typescript
async function loadMagicDocsPrompt(): Promise<string> {
  const promptPath = join(getClaudeConfigHomeDir(), 'magic-docs', 'prompt.md')
  // 讀取 ~/.claude/magic-docs/prompt.md
  // 失敗則靜默使用預設
}
```

---

## 四、Buddy — 虛擬陪伴 Prompt

> 來源：`src/buddy/prompt.ts`

```typescript
export function companionIntroText(name: string, species: string): string {
  return `# Companion

A small ${species} named ${name} sits beside the user's input box and occasionally comments in a speech bubble. You're not ${name} — it's a separate watcher.

When the user addresses ${name} directly (by name), its bubble will answer. Your job in that moment is to stay out of the way: respond in ONE line or less, or just answer any part of the message meant for you. Don't explain that you're not ${name} — they know. Don't narrate what ${name} might say — the bubble handles that.`
}
```

**設計精妙：** 這段 prompt 解決了一個介面設計問題——畫面上同時存在「主模型」和「虛擬陪伴（Buddy）」，需要讓主模型知道：
- 自己不是 Buddy（角色分離）
- 當用戶叫 Buddy 的名字時，主模型只需「退到旁邊」
- 最多回應一行，不要嘗試模仿或描述 Buddy 的行為（Bubble 自己處理）

**注入機制：**
```typescript
export function getCompanionIntroAttachment(messages: Message[] | undefined): Attachment[] {
  if (!feature('BUDDY')) return []
  const companion = getCompanion()
  if (!companion || getGlobalConfig().companionMuted) return []

  // 防止重複注入：檢查是否已有相同 companion 名字的 intro attachment
  for (const msg of messages ?? []) {
    if (msg.type !== 'attachment') continue
    if (msg.attachment.type !== 'companion_intro') continue
    if (msg.attachment.name === companion.name) return []
  }

  return [{ type: 'companion_intro', name: companion.name, species: companion.species }]
}
```

防重複注入：掃描現有訊息，避免同一個 companion 的 intro 被注入兩次。

---

## 五、Claude in Chrome — 瀏覽器自動化 Prompt

> 來源：`src/utils/claudeInChrome/prompt.ts`

### 5.1 BASE_CHROME_PROMPT

```typescript
export const BASE_CHROME_PROMPT = `# Claude in Chrome browser automation

You have access to browser automation tools (mcp__claude-in-chrome__*) for interacting with web pages in Chrome. Follow these guidelines for effective browser automation.

## GIF recording
When performing multi-step browser interactions that the user may want to review or share, use mcp__claude-in-chrome__gif_creator to record them.
You must ALWAYS:
* Capture extra frames before and after taking actions to ensure smooth playback
* Name the file meaningfully to help the user identify it later (e.g., "login_process.gif")

## Console log debugging
You can use mcp__claude-in-chrome__read_console_messages to read console output. Console output may be verbose. If you are looking for specific log entries, use the 'pattern' parameter with a regex-compatible pattern.

## Alerts and dialogs
IMPORTANT: Do not trigger JavaScript alerts, confirms, prompts, or browser modal dialogs through your actions. These browser dialogs block all further browser events and will prevent the extension from receiving any subsequent commands. Instead, when possible, use console.log for debugging and then use the mcp__claude-in-chrome__read_console_messages tool to read those log messages.

## Avoid rabbit holes and loops
When using browser automation tools, stay focused on the specific task. If you encounter any of the following, stop and ask the user for guidance:
- Unexpected complexity or tangential browser exploration
- Browser tool calls failing or returning errors after 2-3 attempts
- No response from the browser extension
- Page elements not responding to clicks or input
- Pages not loading or timing out
- Unable to complete the browser task despite multiple approaches

## Tab context and session startup
IMPORTANT: At the start of each browser automation session, call mcp__claude-in-chrome__tabs_context_mcp first to get information about the user's current browser tabs.

Never reuse tab IDs from a previous/other session...`
```

**設計重點：**
- JavaScript Alert 警告：Alert 會阻塞瀏覽器事件，導致擴充功能失去控制，必須避免
- 2-3 次失敗就停止：防止無限重試陷入死循環
- Session 啟動儀式：每次都先 `tabs_context_mcp`，不假設 tab ID 的有效性

### 5.2 CHROME_TOOL_SEARCH_INSTRUCTIONS（Tool Search 整合）

```typescript
export const CHROME_TOOL_SEARCH_INSTRUCTIONS = `**IMPORTANT: Before using any chrome browser tools, you MUST first load them using ToolSearch.**

Chrome browser tools are MCP tools that require loading before use. Before calling any mcp__claude-in-chrome__* tool:
1. Use ToolSearch with \`select:mcp__claude-in-chrome__<tool_name>\` to load the specific tool
2. Then call the tool

For example, to get tab context:
1. First: ToolSearch with query "select:mcp__claude-in-chrome__tabs_context_mcp"
2. Then: Call mcp__claude-in-chrome__tabs_context_mcp`
```

這個指令在 Tool Search 啟用時才注入，作為「懶惰載入工具」的使用說明。

### 5.3 Skill Hint（啟動引導）

兩個版本（有無 WebBrowser 工具）：

```typescript
// 純 Chrome 版
export const CLAUDE_IN_CHROME_SKILL_HINT = `**Browser Automation**: Chrome browser tools are available via the "claude-in-chrome" skill. CRITICAL: Before using any mcp__claude-in-chrome__* tools, invoke the skill by calling the Skill tool with skill: "claude-in-chrome".`

// 同時有 WebBrowser 工具的版本
export const CLAUDE_IN_CHROME_SKILL_HINT_WITH_WEBBROWSER = `**Browser Automation**: Use WebBrowser for development (dev servers, JS eval, console, screenshots). Use claude-in-chrome for the user's real Chrome when you need logged-in sessions, OAuth, or computer-use — invoke Skill(skill: "claude-in-chrome") before any mcp__claude-in-chrome__* tool.`
```

**兩工具的明確分工：**
- `WebBrowser`：開發用途（dev server、JS eval、截圖）
- `claude-in-chrome`：用戶真實 Chrome（需要登入狀態、OAuth、電腦使用）

---

## 六、各輔助 Prompt 的共同模式

| 模式 | extractMemories | SessionMemory | MagicDocs | Buddy | Chrome |
|------|----------------|---------------|-----------|-------|--------|
| 強制不使用不該用的工具 | ✓（列白名單） | ✓（只用 Edit） | ✓（只用 Edit） | — | ✓（禁 Alert） |
| 防止重複/冗餘 | ✓（check before create） | ✓（不加 filler） | ✓（update in-place） | ✓（anti-dup inject） | — |
| 結構保留 | ✓（MEMORY.md 格式） | ✓（嚴格保留 headers） | ✓（保留 MAGIC DOC: 標頭） | — | — |
| 自訂化 | ✓ | ✓ | ✓ | ✓ | — |
| 與系統提示詞的關係 | fork 繼承主 prompt | 獨立指令注入 | 獨立指令注入 | 附加 attachment | 附加 attachment/skill |
