# 06 — 團隊/設定工具 Prompt 集

> 涵蓋：TeamCreateTool、TeamDeleteTool、ConfigTool、SkillTool、PowerShellTool
> 以及補充：SleepTool、BriefTool（SendUserMessage）、LSPTool、AskUserQuestionTool

---

## 1. TeamCreateTool（TeamCreate）

**檔案**：`src/tools/TeamCreateTool/prompt.ts`（113 行）

### Prompt 原文（`getPrompt()`，部分節選）

```
# TeamCreate

## When to Use

Use this tool proactively whenever:
- The user explicitly asks to use a team, swarm, or group of agents
- The user mentions wanting agents to work together, coordinate, or collaborate
- A task is complex enough that it would benefit from parallel work by multiple agents

When in doubt about whether a task warrants a team, prefer spawning a team.

## Choosing Agent Types for Teammates

Match the agent to the work:
- Read-only agents (e.g., Explore, Plan) cannot edit or write files. Only assign them research,
  search, or planning tasks. Never assign them implementation work.
- Full-capability agents (general-purpose) have access to all tools including file editing, writing,
  and bash. Use these for tasks that require making changes.
- Custom agents in `.claude/agents/` may have their own tool restrictions.

Create a new team to coordinate multiple agents working on a project.
Teams have a 1:1 correspondence with task lists (Team = TaskList).

{"team_name": "my-project", "description": "Working on feature X"}

This creates:
- A team file at `~/.claude/teams/{team-name}/config.json`
- A corresponding task list directory at `~/.claude/tasks/{team-name}/`

## Team Workflow

1. Create a team with TeamCreate
2. Create tasks using the Task tools
3. Spawn teammates using the Agent tool with `team_name` and `name` parameters
4. Assign tasks using TaskUpdate with `owner`
5. Teammates work on assigned tasks and mark them completed via TaskUpdate
6. Teammates go idle between turns — Be patient! Don't comment on their idleness until it
   actually impacts your work.
7. Shutdown your team via SendMessage with `message: {type: "shutdown_request"}`

## Automatic Message Delivery

IMPORTANT: Messages from teammates are automatically delivered to you. You do NOT need to manually
check your inbox.

When you spawn teammates:
- They will send you messages when they complete tasks or need help
- These messages appear automatically as new conversation turns (like user messages)
- The UI shows a brief notification with the sender's name when messages are waiting

## Teammate Idle State

Teammates go idle after every turn — this is completely normal.
- Idle teammates can receive messages. Sending a message to an idle teammate wakes them up.
- Do not treat idle as an error. A teammate sending a message and then going idle is the normal flow.
- Peer DM visibility: When a teammate sends a DM to another teammate, a brief summary is included
  in their idle notification. You do not need to respond to these summaries.

## Discovering Team Members

Read `~/.claude/teams/{team-name}/config.json` to discover other team members.
The config file contains a `members` array with: name, agentId, agentType.

IMPORTANT: Always refer to teammates by their NAME (not UUID).
Names are used for:
- `to` when sending messages
- Identifying task owners

## Task List Coordination

Teams share a task list at `~/.claude/tasks/{team-name}/`.

Teammates should:
1. Check TaskList periodically, especially after completing each task
2. Claim unassigned, unblocked tasks with TaskUpdate (set `owner` to your name)
   Prefer tasks in ID order (lowest ID first)
3. Create new tasks with TaskCreate when identifying additional work
4. Mark tasks as completed with TaskUpdate when done, then check TaskList for next work

IMPORTANT notes for communication with your team:
- Do not use terminal tools to view your team's activity; always send a message
- Your team cannot hear you if you do not use the SendMessage tool
- Do NOT send structured JSON status messages like `{"type":"idle",...}`. Use plain text.
- Use TaskUpdate to mark tasks completed.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| Team = TaskList | 嚴格 1:1 對應，不可分離 |
| idle 誤解矯正 | 大量篇幅解釋 idle 是正常狀態，防止 coordinator 誤判 |
| 名稱 vs UUID | 反覆強調用名字，UUID 僅供參考 |
| 自動送達 | 不需 polling，訊息自動到達 |
| 工具能力審查 | 選擇 subagent_type 前先確認 agent 有哪些工具 |

---

## 2. TeamDeleteTool（TeamDelete）

**檔案**：`src/tools/TeamDeleteTool/prompt.ts`（16 行）

### Prompt 原文（`getPrompt()`）

```
# TeamDelete

Remove team and task directories when the swarm work is complete.

This operation:
- Removes the team directory (`~/.claude/teams/{team-name}/`)
- Removes the task directory (`~/.claude/tasks/{team-name}/`)
- Clears team context from the current session

IMPORTANT: TeamDelete will fail if the team still has active members. Gracefully terminate
teammates first, then call TeamDelete after all teammates have shut down.

Use this when all teammates have finished their work and you want to clean up the team resources.
The team name is automatically determined from the current session's team context.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 必須先關閉隊友 | 有 active members 時 fail，強制正確關閉順序 |
| team_name 自動獲取 | 從 session context 自動解析，不需手動輸入 |
| 清理範圍明確 | teams/ + tasks/ 兩個目錄全清 |

---

## 3. ConfigTool（Config）

**檔案**：`src/tools/ConfigTool/prompt.ts`（93 行）

### Prompt 原文（`generatePrompt()`，動態生成）

```
Get or set Claude Code configuration settings.

View or change Claude Code settings. Use when the user requests configuration changes, asks about
current settings, or when adjusting a setting would benefit them.

## Usage
- Get current value: Omit the "value" parameter
- Set new value: Include the "value" parameter

## Configurable settings list

### Global Settings (stored in ~/.claude.json)
- theme: "dark", "light", "light-daltonism", "dark-daltonism" — Set the color theme
- editorMode: "default", "emacs", "vim" — Set editor keybindings
- preferredNotifChannel: "iterm2", "terminal-bell", "notifications", "none" — Set notification channel
- [voiceEnabled: true/false — if VOICE_MODE feature enabled and GrowthBook gate passes]
... [其他 global settings 從 SUPPORTED_SETTINGS 動態生成]

### Project Settings (stored in settings.json)
- permissions.defaultMode: "plan", "auto", "acceptEdits", "bypassPermissions" — Set permission mode
... [其他 project settings 從 SUPPORTED_SETTINGS 動態生成]

## Model
- model — Override the default model. Available options:
  - "sonnet": claude-sonnet-... - {description}
  - "opus": claude-opus-... - {description}
  - "haiku": claude-haiku-... - {description}
  - null/"default": {description}

## Examples
- Get theme: { "setting": "theme" }
- Set dark theme: { "setting": "theme", "value": "dark" }
- Enable vim mode: { "setting": "editorMode", "value": "vim" }
- Enable verbose: { "setting": "verbose", "value": true }
- Change model: { "setting": "model", "value": "opus" }
- Change permission mode: { "setting": "permissions.defaultMode", "value": "plan" }
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 動態生成 | 從 `SUPPORTED_SETTINGS` registry 生成，確保 prompt 與程式碼同步 |
| 兩層儲存 | global（`~/.claude.json`）vs project（`settings.json`） |
| model 特殊處理 | model 設定從 `getModelOptions()` 動態取值，有獨立 section |
| voice gate | `voiceEnabled` 只在 GrowthBook gate 通過時顯示 |

---

## 4. SkillTool（Skill）

**檔案**：`src/tools/SkillTool/prompt.ts`（241 行）
> 完整 prompt 原文已在 02-core-tool-prompts.md 中詳述，此處補充設定/管理面向。

### Skill 預算管理邏輯

```typescript
// 1% context window 的字元預算
budget = contextWindowTokens × 4 bytes/token × 0.01

// 優先序：
// 1. bundled skills → 永遠保留完整描述（不截斷）
// 2. non-bundled skills → 按比例截斷描述
// 3. 極端情況 → non-bundled 只顯示名稱

MAX_LISTING_DESC_CHARS = 250  // 每條描述硬上限
MIN_DESC_LENGTH = 20          // 截斷下限，低於此就只顯示名稱
```

### Skill 類型分類

| 類型 | source | 截斷保護 |
|---|---|---|
| Bundled skills | `source === 'bundled'` | 永遠完整描述 |
| Plugin skills | `source === 'plugin'` | 可截斷 |
| User skills | 其他 | 可截斷 |

---

## 5. PowerShellTool（PowerShell）

**檔案**：`src/tools/PowerShellTool/prompt.ts`（145 行）

### Prompt 原文（`getPrompt()`，動態生成）— 重要部分

```
Executes a given PowerShell command with optional timeout. Working directory persists between
commands; shell state (variables, functions) does not.

IMPORTANT: This tool is for terminal operations via PowerShell: git, npm, docker, and PS cmdlets.
DO NOT use it for file operations (reading, writing, editing, searching, finding files) — use the
specialized tools instead.

{getEditionSection(edition)}   ← 版本感知語法指引

Before executing the command:
1. Directory Verification: Use Get-ChildItem (ls) to verify the parent directory exists

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes
   - Capture the output of the command

PowerShell Syntax Notes:
   - Variables use $ prefix: $myVar = "value"
   - Escape character is backtick (`), not backslash
   - Verb-Noun cmdlet naming: Get-ChildItem, Set-Location, New-Item, Remove-Item
   - Common aliases: ls, cd, cat, rm
   - Pipe passes objects, not text
   - String interpolation: "Hello $name" or "Hello $($obj.Property)"
   - Registry: `HKLM:\SOFTWARE\...`, `HKCU:\...` (NOT raw HKEY_LOCAL_MACHINE\...)
   - Environment vars: read $env:NAME, set $env:NAME = "value"
   - Native exe with spaces: `& "C:\Program Files\App\app.exe" arg1 arg2`

Interactive and blocking commands (will hang — -NonInteractive):
   - NEVER use `Read-Host`, `Get-Credential`, `Out-GridView`, `$Host.UI.PromptForChoice`, `pause`
   - Destructive cmdlets may prompt for confirmation. Add `-Confirm:$false`.
   - Never use `git rebase -i`, `git add -i`

Passing multiline strings (commit messages) to native executables:
   - Use single-quoted here-string: @'...'@
   - The closing '@' MUST be at column 0 — indenting it is a parse error
   - Example:
     git commit -m @'
     Commit message here.
     '@

Usage notes:
  - timeout in milliseconds (up to {MAX_MS}/{MAX_MIN} minutes), default {DEFAULT_MS}
  - Output exceeds {MAX_CHARS} chars → truncated
  - [background note if enabled]
  - Avoid using PowerShell for dedicated-tool tasks (Glob/Grep/Read/Edit/Write)
  - Multiple commands: parallel → multiple PS tool calls; sequential → chain with ; or if ($?)
  - For git commands: safety protocol same as Bash
```

### 版本感知 prompt（`getEditionSection()`）

**Windows PowerShell 5.1（desktop）：**
```
PowerShell edition: Windows PowerShell 5.1 (powershell.exe)
- Pipeline chain operators `&&` and `||` are NOT available.
  To run B only if A succeeds: `A; if ($?) { B }`.
- Ternary (`?:`), null-coalescing (`??`), and null-conditional (`?.`) NOT available.
- Avoid `2>&1` on native executables in 5.1 — it wraps stderr in ErrorRecord.
- Default file encoding is UTF-16 LE (with BOM). Pass `-Encoding utf8` when needed.
- `ConvertFrom-Json` returns PSCustomObject, not hashtable.
```

**PowerShell 7+（core）：**
```
PowerShell edition: PowerShell 7+ (pwsh)
- Pipeline chain operators `&&` and `||` ARE available.
- Ternary, null-coalescing, null-conditional available.
- Default file encoding is UTF-8 without BOM.
```

**未知版本（保守模式）：**
```
PowerShell edition: unknown — assume Windows PowerShell 5.1 for compatibility
- Do NOT use `&&`, `||`, ternary `?:`, null-coalescing `??`, null-conditional `?.`.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 版本感知 | 執行前偵測 PowerShell 版本，生成適合的語法提示 |
| 與 Bash 平行設計 | 同樣禁止用 PS 做 File/Search，同樣有 git 安全協議 |
| Windows 特化 | Registry 路徑格式、環境變數語法、here-string 格式、encoding 差異 |
| 互動命令封鎖 | `-NonInteractive` 模式下 Read-Host 等命令會卡住 |

---

## 6. 補充工具

### SleepTool（Sleep）

```
Wait for a specified duration. The user can interrupt the sleep at any time.

Use this when the user tells you to sleep or rest, when you have nothing to do, or when you're
waiting for something.

You may receive <tick> prompts — these are periodic check-ins. Look for useful work to do before
sleeping.

You can call this concurrently with other tools — it won't interfere with them.

Prefer this over `Bash(sleep ...)` — it doesn't hold a shell process.

Each wake-up costs an API call, but the prompt cache expires after 5 minutes of inactivity —
balance accordingly.
```

### BriefTool（SendUserMessage）

```
Send a message the user will read. Text outside this tool is visible in the detail view, but most
won't open it — the answer lives here.

`message` supports markdown. `attachments` takes file paths (absolute or cwd-relative) for images,
diffs, logs.

`status` labels intent: 'normal' when replying to what they just asked; 'proactive' when you're
initiating — a scheduled task finished, a blocker surfaced during background work. Set it honestly;
downstream routing uses it.
```

**BRIEF_PROACTIVE_SECTION（完整通訊規則）：**
```
SendUserMessage is where your replies go. Text outside it is visible if the user expands the detail
view, but most won't — assume unread. Anything you want them to actually see goes through
SendUserMessage. The failure mode: the real answer lives in plain text while SendUserMessage just says
"done!" — they see "done!" and miss everything.

So: every time the user says something, the reply they actually read comes through SendUserMessage.
Even for "hi". Even for "thanks".

If you can answer right away, send the answer. If you need to go look — ack first in one line ("On
it — checking the test output"), then work, then send the result.

For longer work: ack → work → result. Between those, send a checkpoint when something useful
happened — a decision you made, a surprise you hit, a phase boundary. Skip the filler.

Keep messages tight — the decision, the file:line, the PR number. Second person always ("your
config"), never third.
```

### AskUserQuestionTool（AskUserQuestion）

```
Use this tool when you need to ask the user questions during execution.

Usage notes:
- Users will always be able to select "Other" to provide custom text input
- Use multiSelect: true to allow multiple answers
- If you recommend a specific option, make that the first option and add "(Recommended)"

Plan mode note: In plan mode, use this tool to clarify requirements or choose between approaches
BEFORE finalizing your plan. Do NOT use this tool to ask "Is my plan ready?" — use ExitPlanMode
for plan approval. IMPORTANT: Do not reference "the plan" in your questions because the user cannot
see the plan in the UI until you call ExitPlanMode.

[Preview feature]: Use the `preview` field on options when presenting concrete artifacts for visual
comparison (ASCII mockups, code snippets, diagram variations). Only for single-select questions.
```

### LSPTool（LSP）

```
Interact with Language Server Protocol (LSP) servers to get code intelligence features.

Supported operations:
- goToDefinition: Find where a symbol is defined
- findReferences: Find all references to a symbol
- hover: Get hover information (documentation, type info)
- documentSymbol: Get all symbols in a document
- workspaceSymbol: Search for symbols across the entire workspace
- goToImplementation: Find implementations of an interface or abstract method
- prepareCallHierarchy: Get call hierarchy item at a position
- incomingCalls: Find all functions/methods that call the function at a position
- outgoingCalls: Find all functions/methods called by the function at a position

All operations require:
- filePath: The file to operate on
- line: The line number (1-based, as shown in editors)
- character: The character offset (1-based, as shown in editors)

Note: LSP servers must be configured for the file type.
```

---

## 團隊工具生命週期

```
TeamCreate
  ├── 建立 ~/.claude/teams/{name}/config.json
  └── 建立 ~/.claude/tasks/{name}/

Agent tool（with team_name + name）
  └── 生成 teammate，加入 team member 列表

SendMessage + TaskCreate/Update/List/Get
  └── 協調執行

SendMessage（shutdown_request）
  └── 各 teammate 回應 shutdown_response

TeamDelete（所有 teammate 已關閉後）
  ├── 清除 ~/.claude/teams/{name}/
  └── 清除 ~/.claude/tasks/{name}/
```
