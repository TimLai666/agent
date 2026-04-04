# Bundled Skills 完整目錄

共 16 個 bundled skills（含條件載入）。

---

## 1. `update-config`（`updateConfig.ts`，475 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `update-config` |
| allowedTools | `['Read']` |
| userInvocable | `true` |
| disableModelInvocation | 無（預設 false）|
| isEnabled | 無（永遠啟用） |
| 條件載入 | 無（無條件載入）|

### 描述原文
```
Use this skill to configure the Claude Code harness via settings.json.
Automated behaviors ("from now on when X", "each time X", "whenever X", "before/after X")
require hooks configured in settings.json - the harness executes these, not Claude,
so memory/preferences cannot fulfill them. Also use for: permissions ("allow X", "add permission",
"move permission to"), env vars ("set X=Y"), hook troubleshooting, or any changes to
settings.json/settings.local.json files. Examples: "allow npm commands", "add bq permission
to global settings", "move permission to user settings", "set DEBUG=true",
"when claude stops show X". For simple settings like theme/model, use Config tool.
```

### getPromptForCommand 邏輯

特殊的 `[hooks-only]` args 前綴：
```typescript
if (args.startsWith('[hooks-only]')) {
  const req = args.slice('[hooks-only]'.length).trim()
  let prompt = HOOKS_DOCS + '\n\n' + HOOK_VERIFICATION_FLOW
  if (req) prompt += `\n\n## Task\n\n${req}`
  return [{ type: 'text', text: prompt }]
}
```
若有此前綴則只返回 Hooks 文件（不含完整 settings schema），效能優化。

常規路徑：`UPDATE_CONFIG_PROMPT + 動態生成的 JSON Schema + 可選 User Request`

### Prompt 核心內容

**三層設定文件：**
```
~/.claude/settings.json     全域
.claude/settings.json       專案
.claude/settings.local.json 個人覆寫
```

**Hook 驗證流程（`HOOK_VERIFICATION_FLOW`）：** 6 步驟嚴格驗證（dedup check → 構建命令 → pipe-test → 寫入 JSON → 語法驗證 → 實際觸發驗證），特別強調 pipe-test 而非假設性分析。

**Schema 生成：**
```typescript
function generateSettingsSchema(): string {
  const jsonSchema = toJSONSchema(SettingsSchema(), { io: 'input' })
  return jsonStringify(jsonSchema, null, 2)
}
```
動態從 Zod schema 生成，確保 prompt 永遠與實際型別同步。

---

## 2. `keybindings-help`（`keybindings.ts`，339 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `keybindings-help` |
| allowedTools | `['Read']` |
| userInvocable | `false`（不顯示在清單）|
| isEnabled | `isKeybindingCustomizationEnabled` |
| 條件載入 | 無（無條件 import，但有 isEnabled 過濾）|

### 描述原文
```
Use when the user wants to customize keyboard shortcuts, rebind keys, add chord bindings,
or modify ~/.claude/keybindings.json. Examples: "rebind ctrl+s", "add a chord shortcut",
"change the submit key", "customize keybindings".
```

### getPromptForCommand 邏輯

動態生成三張 markdown 表格：
```typescript
const contextsTable = generateContextsTable()    // 所有有效 context 清單
const actionsTable = generateActionsTable()      // actions + 預設按鍵 + context
const reservedShortcuts = generateReservedShortcuts()  // 禁止/警告按鍵
```

這些表格從 `defaultBindings.ts`、`schema.ts`、`reservedShortcuts.ts` 動態讀取，是「自文件化」設計的典範。

### Prompt 核心段落

- `SECTION_INTRO` — 讀前寫規則（合併不覆蓋）
- `SECTION_FILE_FORMAT` — JSON 格式含 `$schema` 和 `$docs`
- `SECTION_KEYSTROKE_SYNTAX` — 修飾鍵、特殊鍵、和弦語法
- `SECTION_UNBINDING` — null 值取消綁定
- `SECTION_INTERACTION` — 用戶綁定是附加的（additive）
- `SECTION_COMMON_PATTERNS` — rebind 和 chord 範例
- `SECTION_BEHAVIORAL_RULES` — 5 條行為規則
- `SECTION_DOCTOR` — `/doctor` 指令驗證和常見錯誤表

---

## 3. `verify`（`verify.ts`，30 行 + `verifyContent.ts`）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `verify` |
| allowedTools | 無（從 SKILL.md frontmatter 讀取）|
| userInvocable | `true` |
| files | `{ 'examples/cli.md': ..., 'examples/server.md': ... }` |
| 條件載入 | `process.env.USER_TYPE !== 'ant'` 則跳過 |

### 設計特點

唯一使用 `files` 機制的技能（目前所讀 bundled skills 中）：
```typescript
export const SKILL_FILES: Record<string, string> = {
  'examples/cli.md': cliMd,
  'examples/server.md': serverMd,
}
```

Prompt 來自 Markdown 文件（`verify/SKILL.md`），用 `parseFrontmatter()` 解析：
```typescript
const { frontmatter, content: SKILL_BODY } = parseFrontmatter(SKILL_MD)
const DESCRIPTION = typeof frontmatter.description === 'string'
  ? frontmatter.description
  : 'Verify a code change does what it should by running the app.'
```

描述從 SKILL.md frontmatter 讀取，代碼與描述在同一文件維護。

---

## 4. `debug`（`debug.ts`，103 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `debug` |
| allowedTools | `['Read', 'Grep', 'Glob']` |
| userInvocable | `true` |
| disableModelInvocation | `true` |
| argumentHint | `[issue description]` |
| 條件載入 | 無（無條件），但 `disableModelInvocation` 防止模型主動觸發 |

### 描述差異（USER_TYPE）

```typescript
description: process.env.USER_TYPE === 'ant'
  ? 'Debug your current Claude Code session by reading the session debug log. Includes all event logging'
  : 'Enable debug logging for this session and help diagnose issues',
```

### getPromptForCommand 邏輯

1. `enableDebugLogging()` — 若尚未啟用，開始記錄
2. 讀取最後 64 KB debug log（tail 讀取，避免長 session 中 RSS 激增）
3. 只取最後 20 行（`DEFAULT_DEBUG_LINES_READ`）

```typescript
const TAIL_READ_BYTES = 64 * 1024
// 使用 fd.read() 而非讀整個文件
const fd = await open(debugLogPath, 'r')
const { buffer, bytesRead } = await fd.read({
  buffer: Buffer.alloc(readSize),
  position: startOffset,
})
```

Prompt 包含 log 位置、日誌摘要、設定文件位置三個部分。

---

## 5. `lorem-ipsum`（`loremIpsum.ts`）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `lorem-ipsum`（推測，未直接讀到 registerLoremIpsumSkill 實作）|
| 條件載入 | 無條件 |

（此技能在 index.ts 以 `registerLoremIpsumSkill()` 呼叫，但 loremIpsum.ts 未被完整讀取。基於 282 行規模推測為文字填充工具。）

---

## 6. `skillify`（`skillify.ts`，197 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `skillify` |
| allowedTools | `['Read', 'Write', 'Edit', 'Glob', 'Grep', 'AskUserQuestion', 'Bash(mkdir:*)']` |
| userInvocable | `true` |
| disableModelInvocation | `true` |
| argumentHint | `[description of the process you want to capture]` |
| 條件載入 | `process.env.USER_TYPE !== 'ant'` 則跳過 |

### 功能

將當前 session 的可重複流程捕捉為可重用技能（SKILL.md）。

### getPromptForCommand 邏輯

```typescript
async getPromptForCommand(args, context) {
  const sessionMemory = (await getSessionMemoryContent()) ?? 'No session memory available.'
  const userMessages = extractUserMessages(
    getMessagesAfterCompactBoundary(context.messages),
  )
  // 插入 session memory 和用戶消息到 prompt 模板
  const prompt = SKILLIFY_PROMPT
    .replace('{{sessionMemory}}', sessionMemory)
    .replace('{{userMessages}}', userMessages.join('\n\n---\n\n'))
    .replace('{{userDescriptionBlock}}', userDescriptionBlock)
  return [{ type: 'text', text: prompt }]
}
```

### 4 輪訪談流程（`SKILLIFY_PROMPT`）

**Round 1：** 命名與描述確認
**Round 2：** 步驟概覽、參數、inline/fork 選擇、儲存位置（repo vs personal）
**Round 3：** 逐步細化（成功標準、並行可能性、執行類型、硬性限制）
**Round 4：** 觸發時機確認

### 生成的 SKILL.md 格式

```markdown
---
name: {{skill-name}}
description: {{one-line description}}
allowed-tools:
  {{list of tool permission patterns observed during session}}
when_to_use: {{详细描述}}
argument-hint: "{{hint showing argument placeholders}}"
arguments:
  {{list of argument names}}
context: {{inline or fork -- omit for inline}}
---

# {{Skill Title}}

## Inputs
- `$arg_name`: Description

## Goal
...

## Steps
### 1. Step Name
What to do...
**Success criteria**: ...
```

---

## 7. `remember`（`remember.ts`，82 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `remember` |
| userInvocable | `true` |
| whenToUse | 審查、整理、提升 auto-memory 條目 |
| isEnabled | `() => isAutoMemoryEnabled()` |
| 條件載入 | `process.env.USER_TYPE !== 'ant'` 則跳過 |

### Prompt 核心（`SKILL_PROMPT`）

**4 層記憶分類：**
- `CLAUDE.md` — 專案慣例（所有貢獻者適用）
- `CLAUDE.local.md` — 個人 Claude 指令（不適用他人）
- 團隊記憶（Team memory）— 跨 repo 的組織知識
- 留在 auto-memory — 暫時性的工作筆記

**4 步工作流程：**
1. 收集所有記憶層
2. 分類每個 auto-memory 條目
3. 識別清理機會（重複、過期、衝突）
4. 呈現報告（先 propose 不先 apply）

**硬性規則：** 「Present ALL proposals before making any changes」— 審查優先於修改。

---

## 8. `simplify`（`simplify.ts`，69 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `simplify` |
| userInvocable | `true` |
| 條件載入 | 無條件 |

### getPromptForCommand 邏輯

純靜態 prompt，只在有 args 時附加 `## Additional Focus`：
```typescript
async getPromptForCommand(args) {
  let prompt = SIMPLIFY_PROMPT
  if (args) prompt += `\n\n## Additional Focus\n\n${args}`
  return [{ type: 'text', text: prompt }]
}
```

### Prompt 核心（`SIMPLIFY_PROMPT`）

**Phase 1：** `git diff` 取得變更
**Phase 2：** 平行啟動三個 review agents（`AgentTool`）

- **Agent 1：Code Reuse** — 搜索已有工具/helper，避免重複實作
- **Agent 2：Code Quality** — 7 種反模式（冗餘狀態、參數膨脹、copy-paste、洩漏抽象、string-typed code、不必要 JSX 嵌套、不必要注釋）
- **Phase 3：** 等待三個 agent 完成，聚合結果，直接修復問題

**設計特點：** 明確指示「If a finding is a false positive or not worth addressing, note it and move on — do not argue with the finding, just skip it」—避免無謂爭論。

---

## 9. `batch`（`batch.ts`，124 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `batch` |
| userInvocable | `true` |
| disableModelInvocation | `true` |
| argumentHint | `<instruction>` |
| whenToUse | 大規模機械性修改，可分解為獨立並行單元 |
| 條件載入 | 無條件 |

### getPromptForCommand 防衛邏輯

```typescript
async getPromptForCommand(args) {
  const instruction = args.trim()
  if (!instruction) return [{ type: 'text', text: MISSING_INSTRUCTION_MESSAGE }]
  const isGit = await getIsGit()
  if (!isGit) return [{ type: 'text', text: NOT_A_GIT_REPO_MESSAGE }]
  return [{ type: 'text', text: buildPrompt(instruction) }]
}
```

兩層前置驗證：缺少 instruction、不是 git repo 都直接返回錯誤訊息。

### 三階段 Prompt（`buildPrompt`）

**Phase 1（Plan Mode）：**
- 進入 Plan Mode（`EnterPlanModeTool`）
- 啟動 subagent 研究範圍
- 分解成 5-30 個獨立單元（per-directory 或 per-module 切片）
- 確定 e2e 測試方案（找不到時用 `AskUserQuestionTool` 詢問）

**Phase 2（Spawn Workers）：**
- 退出 Plan Mode，等待用戶批准
- 每個單元一個 background agent（`isolation: "worktree"`, `run_in_background: true`）
- Worker 指令含：目標、文件列表、代碼慣例、e2e 方案、固定 Worker Instructions

**Worker Instructions（`WORKER_INSTRUCTIONS`）：**
```
1. simplify — 呼叫 simplify skill
2. 跑 unit tests
3. e2e 驗證
4. commit + push + gh pr create
5. 報告：最後一行 "PR: <url>"
```

**Phase 3（Track Progress）：**
- 渲染狀態表（# | Unit | Status | PR）
- 從 `PR: <url>` 解析結果更新表格

---

## 10. `stuck`（`stuck.ts`，79 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `stuck` |
| userInvocable | `true` |
| 條件載入 | `process.env.USER_TYPE !== 'ant'` 則跳過（ANT-ONLY）|

### Prompt 核心（`STUCK_PROMPT`）

診斷凍結/卡住的 Claude Code session：

**辨識徵兆：**
- CPU ≥ 90% 持續（無限迴圈）
- 程序狀態 `D`（uninterruptible sleep，I/O hang）
- 程序狀態 `T`（stopped，可能誤按 Ctrl+Z）
- 程序狀態 `Z`（zombie）
- RSS ≥ 4GB（記憶體洩漏）
- 卡住的子程序（git, node, shell）

**調查步驟：**
```bash
ps -axo pid=,pcpu=,rss=,etime=,state=,comm=,command= | grep -E '(claude|cli)' | grep -v grep
```

**回報機制：** 用 Slack MCP 工具回報至 `#claude-code-feedback`（channel ID: `C07VBSHV7EV`），雙消息結構（頂層簡短 + thread 詳情）。

---

## 11. `loop`（`loop.ts`，92 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `loop` |
| userInvocable | `true` |
| argumentHint | `[interval] <prompt>` |
| isEnabled | `isKairosCronEnabled` |
| 條件載入 | `feature('AGENT_TRIGGERS')` 才 require |

### 解析邏輯（優先順序）

1. **前綴 token**：若首個 token 符合 `^\d+[smhd]$`，視為 interval
2. **尾部 "every" 子句**：`every <N><unit>` 或 `every <N> <unit-word>`
3. **預設**：`10m`，整個 input 是 prompt

### 精確的 Cron 轉換表

| 格式 | Cron | 說明 |
|------|------|------|
| `Nm`（N ≤ 59） | `*/N * * * *` | 每 N 分鐘 |
| `Nm`（N ≥ 60） | `0 */H * * *` | 轉小時 |
| `Nh`（N ≤ 23） | `0 */N * * *` | 每 N 小時 |
| `Nd` | `0 0 */N * *` | 每 N 天 |
| `Ns` | `ceil(N/60)m` | 四捨五入到分鐘 |

**邊界處理：** 若 interval 不能整除（如 7m 在 :56→:00 有不均間隔），選最近的整除值並告知用戶。

---

## 12. `schedule`（`scheduleRemoteAgents.ts`，447 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `schedule` |
| allowedTools | `[REMOTE_TRIGGER_TOOL_NAME, ASK_USER_QUESTION_TOOL_NAME]` |
| userInvocable | `true` |
| isEnabled | `getFeatureValue_CACHED_MAY_BE_STALE('tengu_surreal_dali', false) && isPolicyAllowed('allow_remote_sessions')` |
| 條件載入 | `feature('AGENT_TRIGGERS_REMOTE')` 才 require |

### getPromptForCommand 前置檢查

1. OAuth 驗證（API key 不支援，需 claude.ai 帳號）
2. `fetchEnvironments()` 取遠端環境列表
3. 若無環境，自動建立 `claude-code-default` 環境
4. 軟性前置檢查（收集 setupNotes，不阻擋）：
   - 是否在 git repo
   - GitHub App 是否已安裝
   - 是否有 MCP connectors

### Prompt 動態構建（`buildPrompt`）

注入以下動態資訊：
- `userTimezone`（Intl.DateTimeFormat）
- `connectorsInfo`（已連接的 claude.ai MCP connectors，含 Base58 UUID 解碼）
- `gitRepoUrl`（從 git remote 解析的 HTTPS URL）
- `environmentsInfo`（可用環境清單）

包含 4 個工作流程：CREATE / UPDATE / LIST / RUN

---

## 13. `claude-api`（`claudeApi.ts`，196 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `claude-api` |
| allowedTools | `['Read', 'Grep', 'Glob', 'WebFetch']` |
| userInvocable | `true` |
| 條件載入 | `feature('BUILDING_CLAUDE_APPS')` 才 require |

### 懶載入設計

```typescript
// claudeApiContent.js bundles 247KB of .md strings. Lazy-load inside
// getPromptForCommand so they only enter memory when /claude-api is invoked.
type SkillContent = typeof import('./claudeApiContent.js')
```

`claudeApiContent.ts` 在呼叫時才 `import()`，避免 247 KB 字串在啟動時佔用記憶體。

### 語言偵測

```typescript
const LANGUAGE_INDICATORS: Record<DetectedLanguage, string[]> = {
  python: ['.py', 'requirements.txt', 'pyproject.toml', 'setup.py', 'Pipfile'],
  typescript: ['.ts', '.tsx', 'tsconfig.json', 'package.json'],
  java: ['.java', 'pom.xml', 'build.gradle'],
  go: ['.go', 'go.mod'],
  // ...
}
```

偵測 cwd 中的文件，選擇對應語言的文件集（含 `shared/` 文件）。

### 文件注入格式

```
<doc path="python/claude-api/README.md">
...content...
</doc>
```

---

## 14. `claude-in-chrome`（`claudeInChrome.ts`，34 行）

### 基本資訊

| 屬性 | 值 |
|------|---|
| 名稱 | `claude-in-chrome` |
| allowedTools | MCP 工具清單（`mcp__claude-in-chrome__*`）|
| userInvocable | `true` |
| isEnabled | `shouldAutoEnableClaudeInChrome` |
| 條件載入 | `shouldAutoEnableClaudeInChrome()` 才 register |

### 工具名稱生成

```typescript
const CLAUDE_IN_CHROME_MCP_TOOLS = BROWSER_TOOLS.map(
  tool => `mcp__claude-in-chrome__${tool.name}`,
)
```

從 `@ant/claude-for-chrome-mcp` 套件的 `BROWSER_TOOLS` 動態生成。

### 啟動動作

```
IMPORTANT: Start by calling mcp__claude-in-chrome__tabs_context_mcp
to get information about the user's current browser tabs.
```

每次呼叫時強制先讀取 tabs 上下文。

---

## 15. `loremIpsum`（未完整讀取，基於 index.ts 確認存在）

在 `index.ts` 中：`registerLoremIpsumSkill()` 無條件呼叫，為生成填充文本的工具。

---

## 16. `verify`（Content 部分：`verifyContent.ts`，13 行）

見 #3 分析。`verifyContent.ts` 是 content bundle，使用 Bun text loader 將 .md 文件內嵌為字串：
```typescript
import cliMd from './verify/examples/cli.md'
import serverMd from './verify/examples/server.md'
import skillMd from './verify/SKILL.md'
```

---

## 附錄：條件載入總覽

| 技能 | 條件 |
|------|------|
| `update-config` | 無條件 |
| `keybindings-help` | 無條件載入；`isEnabled: isKeybindingCustomizationEnabled` |
| `verify` | `USER_TYPE === 'ant'` |
| `debug` | 無條件載入；`disableModelInvocation` 防主動觸發 |
| `lorem-ipsum` | 無條件 |
| `skillify` | `USER_TYPE === 'ant'` |
| `remember` | `USER_TYPE === 'ant'`；`isEnabled: isAutoMemoryEnabled` |
| `simplify` | 無條件 |
| `batch` | 無條件 |
| `stuck` | `USER_TYPE === 'ant'` |
| `loop` | `feature('AGENT_TRIGGERS')` |
| `schedule` | `feature('AGENT_TRIGGERS_REMOTE')` |
| `claude-api` | `feature('BUILDING_CLAUDE_APPS')` |
| `claude-in-chrome` | `shouldAutoEnableClaudeInChrome()` |
| `dream` | `feature('KAIROS') \|\| feature('KAIROS_DREAM')` |
| `hunter` | `feature('REVIEW_ARTIFACT')` |
| `runSkillGenerator` | `feature('RUN_SKILL_GENERATOR')` |
