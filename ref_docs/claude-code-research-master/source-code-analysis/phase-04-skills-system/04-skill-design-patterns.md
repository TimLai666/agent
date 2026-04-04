# Skill 設計模式：從原始碼提煉

本文從 16 個 bundled skills 的原始碼中，提煉出設計一個高品質 skill 的模式與反模式。

---

## 模式一：防衛性 getPromptForCommand

**問題：** Skills 可能在環境不符時被呼叫（無 args、不在 git repo、未登入等）。

**模式：** 在返回主 prompt 之前，先做環境檢查，返回清晰的錯誤訊息。

**原始碼（batch.ts）：**
```typescript
async getPromptForCommand(args) {
  const instruction = args.trim()
  if (!instruction) {
    return [{ type: 'text', text: MISSING_INSTRUCTION_MESSAGE }]  // 清晰指引
  }
  const isGit = await getIsGit()
  if (!isGit) {
    return [{ type: 'text', text: NOT_A_GIT_REPO_MESSAGE }]      // 環境前提
  }
  return [{ type: 'text', text: buildPrompt(instruction) }]       // 正常路徑
}
```

**原始碼（schedule.ts）：**
```typescript
if (!getClaudeAIOAuthTokens()?.accessToken) {
  return [{ type: 'text', text: 'You need to authenticate...' }]
}
let environments: EnvironmentResource[]
try {
  environments = await fetchEnvironments()
} catch (err) {
  return [{ type: 'text', text: "We're having trouble connecting..." }]
}
```

**規則：** 每個前提條件都有一個具體的失敗訊息，告知用戶如何修復。

---

## 模式二：動態 Prompt 構建（Dynamic Prompt Building）

**問題：** Hardcoded prompt 會與實際型別/配置脫節。

**模式：** 在 `getPromptForCommand` 內動態生成 prompt 的關鍵部分，確保 prompt 永遠是「活文件」。

**原始碼（updateConfig.ts）：**
```typescript
function generateSettingsSchema(): string {
  const jsonSchema = toJSONSchema(SettingsSchema(), { io: 'input' })  // 從 Zod schema 生成
  return jsonStringify(jsonSchema, null, 2)
}

async getPromptForCommand(args) {
  const jsonSchema = generateSettingsSchema()  // 每次呼叫都重新生成
  let prompt = UPDATE_CONFIG_PROMPT
  prompt += `\n\n## Full Settings JSON Schema\n\n\`\`\`json\n${jsonSchema}\n\`\`\``
  // ...
}
```

**原始碼（keybindings.ts）：**
```typescript
async getPromptForCommand(args) {
  const contextsTable = generateContextsTable()     // 從 KEYBINDING_CONTEXTS 生成
  const actionsTable = generateActionsTable()       // 從 DEFAULT_BINDINGS 生成
  const reservedShortcuts = generateReservedShortcuts()  // 從常數生成
  // ...
}
```

**原始碼（scheduleRemoteAgents.ts）：**
```typescript
const prompt = buildPrompt({
  userTimezone: Intl.DateTimeFormat().resolvedOptions().timeZone,  // 執行期資訊
  connectorsInfo: formatConnectorsInfo(connectors),                 // 來自 MCP
  gitRepoUrl: await getCurrentRepoHttpsUrl(),                       // 來自 git
  environmentsInfo: lines.join('\n'),                               // 來自 API
  // ...
})
```

**規則：** 「事實」從 source of truth 讀取，不 hardcode 在 prompt 字串中。

---

## 模式三：懶載入大型內容（Lazy Content Loading）

**問題：** 技能內容（尤其是文件）可能很大，若所有技能都在啟動時載入會增加記憶體使用。

**模式：** 大型內容在 `getPromptForCommand` 內部才 import，而非模組級別。

**原始碼（claudeApi.ts）：**
```typescript
// 在文件頂部：只定義型別，不 import 實際內容
type SkillContent = typeof import('./claudeApiContent.js')

async getPromptForCommand(args) {
  const content = await import('./claudeApiContent.js')  // 呼叫時才載入 247 KB
  const lang = await detectLanguage()
  const prompt = buildPrompt(lang, args, content)
  return [{ type: 'text', text: prompt }]
}
```

**原始碼（bundled/index.ts）：**
```typescript
if (feature('BUILDING_CLAUDE_APPS')) {
  const { registerClaudeApiSkill } = require('./claudeApi.js')  // 整個模組懶載入
  registerClaudeApiSkill()
}
```

**規則：** 技能的 content 模組只在技能被啟用且被呼叫時才進入記憶體。

---

## 模式四：語境感知 Prompt（Context-Aware Prompt）

**問題：** 通用 prompt 無法針對用戶的具體環境給出最佳指引。

**模式：** 在生成 prompt 時，注入執行期環境資訊（語言、時區、git 狀態、已連接服務等）。

**原始碼（claudeApi.ts）— 語言偵測：**
```typescript
async function detectLanguage(): Promise<DetectedLanguage | null> {
  const cwd = getCwd()
  const entries = await readdir(cwd)
  for (const [lang, indicators] of Object.entries(LANGUAGE_INDICATORS)) {
    for (const indicator of indicators) {
      if (indicator.startsWith('.')) {
        if (entries.some(e => e.endsWith(indicator))) return lang
      } else {
        if (entries.includes(indicator)) return lang
      }
    }
  }
  return null
}
```

語言偵測後，只注入對應語言的文件（不載入所有語言）。

**原始碼（scheduleRemoteAgents.ts）— 時區轉換提示：**
```typescript
const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
// 在 prompt 中：
`When the user says a local time, convert it to UTC for the cron expression
but confirm with them: "9am ${userTimezone} = Xam UTC, so the cron would be ..."`
```

**規則：** 用戶不需要告訴技能他們的環境，技能自己去探索。

---

## 模式五：逐步揭露（Progressive Disclosure）

**問題：** 複雜技能的 prompt 可能過長，模型難以把握優先順序。

**模式：** 先提供核心任務，再附加詳細文件；高優先規則放在 prompt 開頭。

**原始碼（updateConfig.ts）— prompt 結構：**
```
# Update Config Skill
## When Hooks Are Required (Not Memory)   ← 最重要的判斷先講
## CRITICAL: Read Before Write            ← 最容易犯的錯誤
## Decision: Config Tool vs Direct Edit   ← 關鍵決策點
## Workflow                               ← 步驟
## Merging Arrays (Important!)            ← 常見陷阱
${SETTINGS_EXAMPLES_DOCS}                 ← 詳細參考
${HOOKS_DOCS}                            ← 更多文件
${HOOK_VERIFICATION_FLOW}                ← 最詳細的流程
## Example Workflows                     ← 具體例子
```

**原始碼（debug.ts）— `[hooks-only]` 前綴優化：**
```typescript
if (args.startsWith('[hooks-only]')) {
  // 只返回 Hooks 文件子集，不載入完整 settings schema
  let prompt = HOOKS_DOCS + '\n\n' + HOOK_VERIFICATION_FLOW
  return [{ type: 'text', text: prompt }]
}
```

---

## 模式六：強制步驟順序（Strict Phase Ordering）

**問題：** 模型可能跳過重要步驟（如測試、審查）。

**模式：** 將工作分成明確的 Phase，每個 Phase 有清晰的成功標準和退出條件。

**原始碼（batch.ts）：**
```
## Phase 1: Research and Plan (Plan Mode)
  → 呼叫 EnterPlanModeTool
  → 研究範圍
  → 分解成 5-30 個單元
  → 確定 e2e 測試方案
  → 撰寫計劃
  → 呼叫 ExitPlanModeTool（等待用戶批准）

## Phase 2: Spawn Workers (After Plan Approval)
  → 每個單元一個 background agent
  → 所有 agents 必須使用 isolation: "worktree" 和 run_in_background: true

## Phase 3: Track Progress
  → 渲染狀態表
  → 解析 PR URL
```

**原始碼（skillify.ts）：**
```
### Step 1: Analyze the Session
### Step 2: Interview the User（4 輪）
### Step 3: Write the SKILL.md
### Step 4: Confirm and Save
```

**規則：** Phase 之間有明確的觸發條件（Plan Mode 批准、用戶確認等），防止模型跳過。

---

## 模式七：並行 Agent 編排（Parallel Agent Orchestration）

**問題：** 多個獨立子任務若串行執行效率低。

**模式：** 明確指示模型「在同一個 message 中」啟動所有 parallel agents。

**原始碼（simplify.ts）：**
```
## Phase 2: Launch Three Review Agents in Parallel

Use the ${AGENT_TOOL_NAME} tool to launch all three agents concurrently in a single message.
Pass each agent the full diff so it has the complete context.
```

**原始碼（batch.ts）：**
```
Once the plan is approved, spawn one background agent per work unit using the AgentTool.
All agents must use isolation: "worktree" and run_in_background: true.
Launch them all in a single message block so they run in parallel.
```

**規則：** 使用「in a single message」、「concurrently」等措辭，強制並行而非串行。

---

## 模式八：最小 allowedTools 原則

**問題：** 過寬的工具授權增加安全風險。

**模式：** `allowedTools` 只包含技能完成任務所需的最小工具集，且用 pattern 縮小範圍。

**對比：**
```typescript
// Bad：過寬
allowedTools: ['Bash']

// Good：最小化
allowedTools: ['Bash(mkdir:*)']          // batch.ts 中的 skillify

// Good：明確列舉
allowedTools: ['Read', 'Grep', 'Glob', 'WebFetch']   // claude-api.ts
```

**原始碼（keybindings.ts）：**
```typescript
allowedTools: ['Read'],   // 只讀，不寫（寫入操作讓模型用 Write/Edit tool 負責）
```

---

## 模式九：User Request 末尾附加（Append, Don't Prepend）

**問題：** 若 args 放在 prompt 開頭，可能讓模型忽略後面的指引。

**模式：** `args`（用戶請求）附加在 prompt 末尾，讓指引優先於請求。

```typescript
// 幾乎所有技能都採用相同模式：
if (args) {
  prompt += `\n\n## User Request\n\n${args}`
}
return [{ type: 'text', text: prompt }]
```

或用 section 明確標記：
```typescript
if (userArgs) {
  prompt += `\n## User Request\n\nThe user said: "${userArgs}"\n\nStart by understanding their intent...`
}
```

---

## 模式十：disableModelInvocation 控制觸發方式

**問題：** 某些技能有破壞性或需要明確意圖，不應由模型主動觸發。

**模式：** `disableModelInvocation: true` 讓技能只能由用戶直接呼叫（`/skill-name`）。

**使用此模式的技能：**
- `skillify`（捕捉 session — 應有意識地呼叫）
- `batch`（大規模並行修改 — 需要明確 instruction）
- `debug`（診斷工具 — 主動觸發描述浪費 context）

```typescript
disableModelInvocation: true,  // 從 system-reminder 列表中隱藏 description
userInvocable: true,           // 但用戶可以 /debug 呼叫
```

SkillTool validate 時會拒絕模型呼叫這些技能：
```typescript
if (foundCommand.disableModelInvocation) {
  return {
    result: false,
    message: `Skill ${normalizedCommandName} cannot be used with Skill tool due to disable-model-invocation`,
    errorCode: 4,
  }
}
```

---

## 模式十一：Session 上下文注入

**問題：** 技能需要了解當前 session 的上下文（用戶做了什麼）。

**模式：** 在 `getPromptForCommand(args, context)` 中從 `context` 讀取 session 資訊。

**原始碼（skillify.ts）：**
```typescript
async getPromptForCommand(args, context) {
  const sessionMemory = (await getSessionMemoryContent()) ?? 'No session memory available.'
  const userMessages = extractUserMessages(
    getMessagesAfterCompactBoundary(context.messages),  // context 包含完整對話歷史
  )
  // 注入到 prompt
}
```

---

## 模式十二：isEnabled 動態可見性

**問題：** 某些技能只在特定功能啟用時才有意義（如 auto-memory 功能）。

**模式：** `isEnabled: () => boolean` 在技能列表渲染時過濾，技能仍被 registered，但不出現在清單中。

```typescript
registerBundledSkill({
  name: 'remember',
  isEnabled: () => isAutoMemoryEnabled(),    // 執行期決定可見性
  // ...
})

registerBundledSkill({
  name: 'schedule',
  isEnabled: () =>
    getFeatureValue_CACHED_MAY_BE_STALE('tengu_surreal_dali', false) &&
    isPolicyAllowed('allow_remote_sessions'),  // 兩個條件都滿足才可見
  // ...
})
```

---

## 反模式

### 反模式 1：過度依賴靜態 Prompt

若 skill 有 `allowedTools`、schema、或引用了程式碼中的型別，應動態生成那部分，否則隨代碼演進會脫節。

### 反模式 2：將「大型文件」放在啟動路徑

247 KB 的 API 文件若在模組級別 import，會讓 CLI 啟動時多佔記憶體。應使用 dynamic import 懶載入。

### 反模式 3：忽略防衛性前置檢查

直接返回主 prompt 而不驗證環境（auth、git、args）會讓技能在錯誤環境中傳出無用的 prompt，浪費 token。

### 反模式 4：任意寬廣的 allowedTools

`allowedTools: ['Bash']` 給了過多權限。應縮小到 `'Bash(npm:*)'` 或類似的最小集合。

### 反模式 5：串行執行可並行的子任務

如果多個 review/analysis 任務之間無依賴，應在 prompt 中明確指示並行。`simplify.ts` 的「in a single message」是正確做法。
