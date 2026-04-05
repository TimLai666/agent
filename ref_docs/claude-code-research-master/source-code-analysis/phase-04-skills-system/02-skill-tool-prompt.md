# SkillTool Prompt 完整原文 + 分析

## 來源檔案

`src/tools/SkillTool/prompt.ts`（241 行）

---

## 一、getPrompt() — 模型系統提示原文

這是注入給模型的 SkillTool 描述，用 `memoize` 快取（`_cwd` 為 key，但實際回傳內容與 cwd 無關，快取的目的是避免重複函數呼叫）：

```typescript
export const getPrompt = memoize(async (_cwd: string): Promise<string> => {
  return `Execute a skill within the main conversation

When users ask you to perform tasks, check if any of the available skills match. Skills provide specialized capabilities and domain knowledge.

When users reference a "slash command" or "/<something>" (e.g., "/commit", "/review-pr"), they are referring to a skill. Use this tool to invoke it.

How to invoke:
- Use this tool with the skill name and optional arguments
- Examples:
  - \`skill: "pdf"\` - invoke the pdf skill
  - \`skill: "commit", args: "-m 'Fix bug'"\` - invoke with arguments
  - \`skill: "review-pr", args: "123"\` - invoke with arguments
  - \`skill: "ms-office-suite:pdf"\` - invoke using fully qualified name

Important:
- Available skills are listed in system-reminder messages in the conversation
- When a skill matches the user's request, this is a BLOCKING REQUIREMENT: invoke the relevant Skill tool BEFORE generating any other response about the task
- NEVER mention a skill without actually calling this tool
- Do not invoke a skill that is already running
- Do not use this tool for built-in CLI commands (like /help, /clear, etc.)
- If you see a <command-name> tag in the current conversation turn, the skill has ALREADY been loaded - follow the instructions directly instead of calling this tool again
`
})
```

---

## 二、system-reminder 技能清單格式

技能列表以以下格式注入 system-reminder：

```
- update-config: Use this skill to configure the Claude Code harness via settings.json...
- keybindings-help: Use when the user wants to customize keyboard shortcuts...
- simplify: Review changed code for reuse, quality, and efficiency...
...（最多 budget 允許的行數）
```

每行格式：`- {name}: {description}[ - {whenToUse}]`

### 來源函數

```typescript
function formatCommandDescription(cmd: Command): string {
  const displayName = getCommandName(cmd)
  return `- ${cmd.name}: ${getCommandDescription(cmd)}`
}

function getCommandDescription(cmd: Command): string {
  const desc = cmd.whenToUse
    ? `${cmd.description} - ${cmd.whenToUse}`
    : cmd.description
  return desc.length > MAX_LISTING_DESC_CHARS
    ? desc.slice(0, MAX_LISTING_DESC_CHARS - 1) + '…'
    : desc
}
```

---

## 三、Budget 管理機制

### 關鍵常數

```typescript
export const SKILL_BUDGET_CONTEXT_PERCENT = 0.01   // 1% 上下文視窗
export const CHARS_PER_TOKEN = 4                   // 字元/token 估算
export const DEFAULT_CHAR_BUDGET = 8_000           // 備用預設（200k × 1% × 4）
export const MAX_LISTING_DESC_CHARS = 250          // 每條目最大字元數
const MIN_DESC_LENGTH = 20                         // 最小描述長度
```

### Budget 計算

```typescript
export function getCharBudget(contextWindowTokens?: number): number {
  if (Number(process.env.SLASH_COMMAND_TOOL_CHAR_BUDGET)) {
    return Number(process.env.SLASH_COMMAND_TOOL_CHAR_BUDGET)  // 環境變數覆寫
  }
  if (contextWindowTokens) {
    return Math.floor(contextWindowTokens * CHARS_PER_TOKEN * SKILL_BUDGET_CONTEXT_PERCENT)
  }
  return DEFAULT_CHAR_BUDGET
}
```

### 三層截斷策略（`formatCommandsWithinBudget`）

```typescript
export function formatCommandsWithinBudget(
  commands: Command[],
  contextWindowTokens?: number,
): string {
  // 1. 嘗試完整描述（不截斷）
  if (fullTotal <= budget) return fullEntries.map(e => e.full).join('\n')

  // 2. Bundled skills 永不截斷；非 bundled 按比例縮短描述
  const maxDescLen = Math.floor(availableForDescs / restCommands.length)
  if (maxDescLen >= MIN_DESC_LENGTH) {
    return commands.map((cmd, i) => {
      if (bundledIndices.has(i)) return fullEntries[i]!.full  // bundled: 完整
      return `- ${cmd.name}: ${truncate(description, maxDescLen)}`
    }).join('\n')
  }

  // 3. 極端情況：非 bundled 僅顯示名稱
  return commands.map((cmd, i) =>
    bundledIndices.has(i) ? fullEntries[i]!.full : `- ${cmd.name}`
  ).join('\n')
}
```

**設計邏輯：** Bundled skills 是官方技能，描述品質有保證且被視為 context 的基礎設施；第三方/用戶自定義技能在 budget 緊張時犧牲描述，但不消失。

---

## 四、Prompt 設計分析

### 4.1 強制觸發機制

> "this is a BLOCKING REQUIREMENT: invoke the relevant Skill tool BEFORE generating any other response about the task"

這是故意使用大寫 + 強硬語氣的「行為鎖」。與其讓模型「考慮」是否呼叫 skill，不如直接指令化。對比普通工具描述的建議性語氣，SkillTool 使用的是命令語氣。

### 4.2 防止提及不呼叫（mention without calling）

> "NEVER mention a skill without actually calling this tool"

解決的問題：模型可能說「你可以用 /commit skill」但不實際呼叫。這條規則強制所有技能提及都必須伴隨工具呼叫。

### 4.3 重入防護（re-entry guard）

> "Do not invoke a skill that is already running"
> "If you see a `<command-name>` tag in the current conversation turn, the skill has ALREADY been loaded"

`<command-name>` XML tag 是技能已載入的信號標記（在 `COMMAND_NAME_TAG` 常數定義）。防止技能呼叫自己或在已展開的 prompt 中再次觸發。

### 4.4 內建指令豁免

> "Do not use this tool for built-in CLI commands (like /help, /clear, etc.)"

區分技能（skills）和內建 CLI 指令（`/help`, `/clear`, `/config` 等）。內建指令由 `builtInCommandNames()` 管理，不走 SkillTool 路徑。

### 4.5 完整限定名稱（fully qualified name）

```
skill: "ms-office-suite:pdf"  - invoke using fully qualified name
```

支援 Plugin 系統的命名空間：`pluginName:skillName`。允許多個 plugin 提供同名技能而不衝突。

---

## 五、getSkillToolInfo / getSkillInfo 差異

```typescript
// getSkillToolInfo：計算 SkillTool 的 command 數量（含 MCP skills）
export async function getSkillToolInfo(cwd: string): Promise<{
  totalCommands: number
  includedCommands: number
}>

// getSkillInfo：計算 SlashCommandTool 的 skills 數量（子集）
export async function getSkillInfo(cwd: string): Promise<{
  totalSkills: number
  includedSkills: number
}>
```

目前兩者都是 total = included（沒有上限截斷），差異在於命令來源不同。`getSkillInfo` 若拋出錯誤會靜默返回 `{0, 0}` 而不中斷執行。

---

## 六、快取管理

```typescript
export function clearPromptCache(): void {
  getPrompt.cache?.clear?.()
}
```

`getPrompt` 用 lodash `memoize` 快取。在技能目錄變更（`skillChangeDetector` 觸發）後需呼叫 `clearPromptCache()` 確保下次 prompt 反映最新狀態。注意技能清單本身是動態生成的（在 system-reminder 中每輪注入），不受此快取影響。
