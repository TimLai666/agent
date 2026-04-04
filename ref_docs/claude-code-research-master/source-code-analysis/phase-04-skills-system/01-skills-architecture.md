# Skills 系統架構分析

## 1. 系統概覽

Skills 系統是 Claude Code 的「可程式化指令擴充」機制。它讓一段結構化的 Markdown prompt（加上可選的 TypeScript 程式碼）能以 `skill: "name"` 的形式被模型呼叫，並在執行時獲得特定工具授權與可選的子 agent 隔離環境。

---

## 2. 核心元件

### 2.1 SkillTool（`src/tools/SkillTool/SkillTool.ts`）

Skills 的對外入口，實作為標準 `Tool<InputSchema, Output, Progress>`。

**輸入 schema：**
```typescript
z.object({
  skill: z.string().describe('The skill name. E.g., "commit", "review-pr", or "pdf"'),
  args: z.string().optional().describe('Optional arguments for the skill'),
})
```

**輸出 schema（union）：**
```typescript
// 內聯執行（inline）
z.object({
  success: z.boolean(),
  commandName: z.string(),
  allowedTools: z.array(z.string()).optional(),
  model: z.string().optional(),
  status: z.literal('inline').optional(),
})
// 分叉執行（forked）
z.object({
  success: z.boolean(),
  commandName: z.string(),
  status: z.literal('forked'),
  agentId: z.string(),
  result: z.string(),
})
```

### 2.2 BundledSkills（`src/skills/bundledSkills.ts`）

內建技能的登錄系統：

```typescript
export type BundledSkillDefinition = {
  name: string
  description: string
  aliases?: string[]
  whenToUse?: string
  argumentHint?: string
  allowedTools?: string[]
  model?: string
  disableModelInvocation?: boolean
  userInvocable?: boolean
  isEnabled?: () => boolean
  hooks?: HooksSettings
  context?: 'inline' | 'fork'
  agent?: string
  files?: Record<string, string>   // 額外參考檔案，懶載入解壓
  getPromptForCommand: (args: string, context: ToolUseContext) => Promise<ContentBlockParam[]>
}
```

`registerBundledSkill()` 將定義轉為 `Command` 物件並推入 `bundledSkills[]` 陣列，`getBundledSkills()` 提供唯讀副本。

### 2.3 SkillTool Prompt（`src/tools/SkillTool/prompt.ts`）

管理 system-reminder 中技能清單的格式化與 budget 控制。

---

## 3. 載入流程

```
程式啟動
   └─ initBundledSkills()              (src/skills/bundled/index.ts)
       ├─ registerUpdateConfigSkill()
       ├─ registerKeybindingsSkill()
       ├─ registerVerifySkill()
       ├─ ... (全部無條件)
       ├─ feature('KAIROS') → registerDreamSkill()       (動態 require)
       ├─ feature('AGENT_TRIGGERS') → registerLoopSkill()
       ├─ feature('AGENT_TRIGGERS_REMOTE') → registerScheduleRemoteAgentsSkill()
       ├─ feature('BUILDING_CLAUDE_APPS') → registerClaudeApiSkill()
       └─ shouldAutoEnableClaudeInChrome() → registerClaudeInChromeSkill()
```

**功能旗標機制：** 高風險 / 實驗性技能用 `feature('FLAG_NAME')` 控制 require 時機，非旗標技能直接靜態 import。`isEnabled` callback 是執行期可見性過濾（不影響載入）。

**懶載入優化：** `claudeApiContent.ts`（247 KB of .md strings）、`remoteSkillModules`（EXPERIMENTAL_SKILL_SEARCH）全部採懶載入，避免啟動時佔用記憶體。

---

## 4. 技能發現流程（system-reminder）

每輪對話前，系統在 system-reminder 中注入技能清單：

```
getSkillToolCommands(cwd)
   ├─ getBundledSkills()              (來源：bundled)
   ├─ getCommands(projectRoot)        (來源：.claude/skills/, .claude/commands/)
   └─ mcpSkills (loadedFrom === 'mcp') (來源：MCP server)
```

**Budget 控制（`prompt.ts`）：**
- 技能清單佔對話視窗的 1%（字元數）
- `SKILL_BUDGET_CONTEXT_PERCENT = 0.01`，`CHARS_PER_TOKEN = 4`，`DEFAULT_CHAR_BUDGET = 8000`
- Bundled skills 永不截斷；非 bundled skills 在超出 budget 時按比例縮短描述
- 每個條目最多 250 字元（`MAX_LISTING_DESC_CHARS`）

---

## 5. 執行流程

```
模型呼叫 Skill tool { skill: "xxx", args: "..." }
    │
    ├─ validateInput()
    │   ├─ 正規化 skill 名稱（去除前綴 '/'）
    │   ├─ 查找 command（getAllCommands → local + MCP）
    │   ├─ 檢查 disableModelInvocation（不允許則拒絕）
    │   └─ 確認 type === 'prompt'
    │
    ├─ checkPermissions()
    │   ├─ 檢查 deny rules → 拒絕
    │   ├─ EXPERIMENTAL_SKILL_SEARCH canonical → 自動允許
    │   ├─ 檢查 allow rules → 允許
    │   ├─ skillHasOnlySafeProperties() → 自動允許
    │   └─ 預設 behavior: 'ask'（提示用戶）
    │
    └─ call()
        ├─ [若 command.context === 'fork'] executeForkedSkill()
        │   ├─ prepareForkedCommandContext() → promptMessages
        │   ├─ runAgent() (獨立子 agent)
        │   └─ 返回 { status: 'forked', result: extractResultText() }
        │
        └─ [內聯執行] processPromptSlashCommand()
            ├─ 展開 prompt content（呼叫 getPromptForCommand(args, context)）
            ├─ 建立 newMessages（注入對話）
            └─ 返回 contextModifier（修改 allowedTools / model / effort）
```

---

## 6. 執行模式比較

| 維度 | 內聯（inline） | 分叉（fork） |
|------|--------------|------------|
| 上下文 | 與主對話共享 | 獨立子 agent，隔離 token budget |
| 結果注入方式 | `newMessages` 注入 | `result` 字串返回 |
| 適合場景 | 需要與用戶互動、修改主對話狀態 | 自含式任務，無需中途輸入 |
| 觸發方式 | `command.context !== 'fork'`（預設） | `command.context === 'fork'` |
| 進度回報 | 無 | `onProgress` 傳遞工具使用消息 |

---

## 7. 權限系統

### 自動允許條件（`skillHasOnlySafeProperties`）
技能只有以下「安全屬性」（無敏感工具）時自動允許，不詢問用戶：
- 無 `allowedTools`（空陣列）
- 或全部工具屬於安全列表

### 手動規則語法（settings.json）
```json
{
  "permissions": {
    "allow": ["Skill(update-config)", "Skill(review-pr:*)"],
    "deny": ["Skill(dangerous-skill)"]
  }
}
```

規則匹配優先順序：deny → allow → 自動允許 → ask

---

## 8. 文件監控（`src/utils/skills/skillChangeDetector.ts`）

**監控路徑：**
- `~/.claude/skills/` — 用戶技能
- `~/.claude/commands/` — 用戶指令（舊格式）
- `.claude/skills/` — 專案技能
- `.claude/commands/` — 專案指令
- `--add-dir` 參數指定的額外目錄

**關鍵實作細節：**
- 使用 `chokidar`（`depth: 2`，因為技能格式是 `skill-name/SKILL.md`）
- Bun 環境下強制 `usePolling: true`（規避 `oven-sh/bun#27469` PathWatcherManager 死鎖 bug）
- 300ms debounce 避免批量檔案變更時的重複 reload（git 操作可能觸發數十個事件）
- 1s `awaitWriteFinish` 等待寫入穩定

**reload 順序：**
```
chokidar change event
   └─ scheduleReload()（300ms debounce）
       ├─ executeConfigChangeHooks('skills', path)
       ├─ clearSkillCaches()
       ├─ clearCommandsCache()
       ├─ resetSentSkillNames()
       └─ skillsChanged.emit()
```

---

## 9. 來源分類

| 來源 (`source`) | `loadedFrom` | 說明 |
|----------------|-------------|------|
| `bundled` | `bundled` | 編譯進二進位，TypeScript 定義 |
| `project` | `skills` | `.claude/skills/<name>/SKILL.md` |
| `project` | `commands` | `.claude/commands/<name>.md`（舊格式） |
| `userSettings` | `skills` | `~/.claude/skills/<name>/SKILL.md` |
| `plugin` | `mcp` | MCP server 提供的 prompts |
| `remote` | `_canonical_` | 實驗性：從 AKI/GCS 載入（ant-only） |

---

## 10. Bundled Skill 的 `files` 機制

當 skill 定義包含 `files: Record<string, string>` 時：

1. 技能第一次被呼叫時，懶解壓至 `~/.claude/bundled-skills/<nonce>/<skill-name>/`
2. 安全措施：`O_EXCL | O_NOFOLLOW` flags + `0o600` 權限（防 symlink 攻擊）
3. Prompt 前綴加 `Base directory for this skill: <dir>` 讓模型能 Read/Grep 這些檔案
4. 使用 per-process nonce 目錄（防預先建立攻擊）

目前使用此機制的技能：`verify`（含 `examples/cli.md`、`examples/server.md`）
