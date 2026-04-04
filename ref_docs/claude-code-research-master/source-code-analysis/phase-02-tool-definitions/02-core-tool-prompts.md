# 02 — 核心工具 Prompt 原文集

> 涵蓋：BashTool、AgentTool、SkillTool、FileEditTool、FileReadTool、FileWriteTool、GrepTool、GlobTool

---

## 1. BashTool（Bash）

**檔案**：`src/tools/BashTool/prompt.ts`（369 行）

### 核心 prompt 結構（`getSimplePrompt()` 動態生成）

```
Executes a given bash command and returns its output.

The working directory persists between commands, but shell state does not.
The shell environment is initialized from the user's profile (bash or zsh).

IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`, `tail`, `sed`, `awk`, or `echo`
commands, unless explicitly instructed or after you have verified that a dedicated tool cannot accomplish
your task. Instead, use the appropriate dedicated tool as this will provide a much better experience for
the user:

 - File search: Use Glob (NOT find or ls)
 - Content search: Use Grep (NOT grep or rg)
 - Read files: Use Read (NOT cat/head/tail)
 - Edit files: Use Edit (NOT sed/awk)
 - Write files: Use Write (NOT echo >/cat <<EOF)
 - Communication: Output text directly (NOT echo/printf)

While the Bash tool can do similar things, it's better to use the built-in tools as they provide a better
user experience and make it easier to review tool calls and give permission.

# Instructions
 - If your command will create new directories or files, first use this tool to run `ls` to verify the
   parent directory exists and is the correct location.
 - Always quote file paths that contain spaces with double quotes
 - Try to maintain your current working directory throughout the session by using absolute paths and
   avoiding usage of `cd`. You may use `cd` if the User explicitly requests it.
 - You may specify an optional timeout in milliseconds (up to {MAX_MS}/{MAX_MINUTES} minutes). By default,
   your command will timeout after {DEFAULT_MS} ({DEFAULT_MINUTES} minutes).
 - [background task note if enabled]
 - When issuing multiple commands:
   - If the commands are independent and can run in parallel, make multiple Bash tool calls in a single message.
   - If the commands depend on each other and must run sequentially, use a single Bash call with '&&'.
   - Use ';' only when you need to run commands sequentially but don't care if earlier commands fail.
   - DO NOT use newlines to separate commands
 - For git commands:
   - Prefer to create a new commit rather than amending an existing commit.
   - Before running destructive operations consider whether there is a safer alternative.
   - Never skip hooks (--no-verify) or bypass signing unless user explicitly asked.
 - Avoid unnecessary `sleep` commands:
   - Do not sleep between commands that can run immediately.
   - If long running: use `run_in_background`. No sleep needed.
   - Do not retry failing commands in a sleep loop — diagnose the root cause.
   - [Monitor tool note if MONITOR_TOOL feature enabled]

## Command sandbox（僅沙箱模式）
By default, your command will be run in a sandbox. This sandbox controls which directories and
network hosts commands may access or modify without an explicit override.

The sandbox has the following restrictions:
Filesystem: {...}
Network: {...}

 - [沙箱覆蓋規則：dangerouslyDisableSandbox 使用條件]
 - For temporary files, always use the `$TMPDIR` environment variable. Do NOT use `/tmp` directly.
```

### Git/PR 指令區塊（外部使用者完整版）

```
# Committing changes with git

Only create commits when requested by the user. If unclear, ask first.

Git Safety Protocol:
- NEVER update the git config
- NEVER run destructive git commands (push --force, reset --hard, checkout ., restore ., clean -f, branch -D)
  unless the user explicitly requests these actions.
- NEVER skip hooks (--no-verify, --no-gpg-sign, etc) unless the user explicitly requests it
- NEVER run force push to main/master, warn the user if they request it
- CRITICAL: Always create NEW commits rather than amending, unless the user explicitly requests a git amend.
  When a pre-commit hook fails, the commit did NOT happen — so --amend would modify the PREVIOUS commit.
- When staging files, prefer adding specific files by name rather than using "git add -A" or "git add ."
- NEVER commit changes unless the user explicitly asks you to.

1. [parallel] git status (no -uall flag) + git diff + git log (for style)
2. Draft commit message: summarize why (not what), warn about .env/credentials
3. [parallel] git add + git commit with HEREDOC + git status to verify
4. If pre-commit hook fails: fix the issue and create a NEW commit

# Creating pull requests
... [full PR workflow with steps 1-3]
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 工具偏好優先 | 明確列出何時用 Bash 以外的工具，降低 Bash 濫用 |
| 並行/串行明確區分 | `&&`（依賴鏈）vs 多個 tool call（獨立）|
| 沙箱 prompt 動態生成 | 從 `SandboxManager` 實時讀取允許/拒絕規則，內聯進 prompt |
| Git 安全協議 | 詳列破壞性操作守則，commit 需 HEREDOC 格式化 |
| 背景任務控制 | `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` 環境變數控制是否說明 `run_in_background` |
| ant vs 外部 分支 | ant 使用者指向 `/commit` /`/commit-push-pr` skills；外部使用者收到完整 inline 說明 |

---

## 2. AgentTool（Agent）

**檔案**：`src/tools/AgentTool/prompt.ts`（287 行）

### 核心 prompt（非 coordinator 模式）

```
Launch a new agent to handle complex, multi-step tasks autonomously.

The Agent tool launches specialized agents (subprocesses) that autonomously handle complex tasks.
Each agent type has specific capabilities and tools available to it.

[agentListSection — 可能是 inline 或 system-reminder attachment]

When using the Agent tool, specify a subagent_type to use a specialized agent, or omit it to fork yourself
— a fork inherits your full conversation context. [fork mode]

When NOT to use the Agent tool:
- If you want to read a specific file path, use the Read tool
- If you are searching for a specific class definition like "class Foo", use Glob instead
- If you are searching for code within a specific file or set of 2-3 files, use the Read tool
- Other tasks that are not related to the agent descriptions above

Usage notes:
- Always include a short description (3-5 words) summarizing what the agent will do
- [subscription-gated] Launch multiple agents concurrently whenever possible
- When the agent is done, it will return a single message back to you. The result returned by the agent
  is not visible to the user. To show the user the result, you should send a text message.
- [background agent support]
- To continue a previously spawned agent, use SendMessage with the agent's ID or name
- The agent's outputs should generally be trusted
- Clearly tell the agent whether you expect it to write code or just to do research
- [parallel launch note]
- You can optionally set `isolation: "worktree"` to run the agent in a temporary git worktree
```

### Fork 模式額外區塊（`isForkSubagentEnabled()` = true）

```
## When to fork

Fork yourself (omit `subagent_type`) when the intermediate tool output isn't worth keeping in your
context. The criterion is qualitative — "will I need this output again" — not task size.
- Research: fork open-ended questions. Parallel forks share your cache.
- Implementation: prefer to fork implementation work that requires more than a couple of edits.

Forks are cheap because they share your prompt cache. Don't set `model` on a fork.
Pass a short `name` (one or two words, lowercase) so the user can see the fork.

Don't peek. The tool result includes an `output_file` path — do not Read or tail it
unless the user explicitly asks for a progress check.

Don't race. Never fabricate or predict fork results.

## Writing the prompt

Brief the agent like a smart colleague who just walked into the room.
- Explain what you're trying to accomplish and why.
- Describe what you've already learned or ruled out.
- Give enough context that the agent can make judgment calls.
- If you need a short response, say so.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| Agent 列表可切換為 attachment | `shouldInjectAgentListInMessages()` gate — 避免 MCP reload 使 tool-schema cache bust |
| coordinator 模式精簡 | coordinator 只收到 `shared` 基礎段，不含 whenNotToUse/examples |
| fork 語義 | fork = 繼承 context；subagent = 全新 context，需完整 briefing |
| "不要窺探" 原則 | fork 執行中不要 Read output_file |
| 並發訂閱限制 | pro 訂閱不顯示「多 agent 並發」提示（單獨在 attachment 處理）|

---

## 3. SkillTool（Skill）

**檔案**：`src/tools/SkillTool/prompt.ts`（241 行）

### Prompt 原文（`getPrompt()` memoized）

```
Execute a skill within the main conversation

When users ask you to perform tasks, check if any of the available skills match. Skills provide
specialized capabilities and domain knowledge.

When users reference a "slash command" or "/<something>" (e.g., "/commit", "/review-pr"),
they are referring to a skill. Use this tool to invoke it.

How to invoke:
- Use this tool with the skill name and optional arguments
- Examples:
  - `skill: "pdf"` - invoke the pdf skill
  - `skill: "commit", args: "-m 'Fix bug'"` - invoke with arguments
  - `skill: "review-pr", args: "123"` - invoke with arguments
  - `skill: "ms-office-suite:pdf"` - invoke using fully qualified name

Important:
- Available skills are listed in system-reminder messages in the conversation
- When a skill matches the user's request, this is a BLOCKING REQUIREMENT: invoke the relevant Skill
  tool BEFORE generating any other response about the task
- NEVER mention a skill without actually calling this tool
- Do not invoke a skill that is already running
- Do not use this tool for built-in CLI commands (like /help, /clear, etc.)
- If you see a <command-name> tag in the current conversation turn, the skill has ALREADY been loaded -
  follow the instructions directly instead of calling this tool again
```

### Budget 計算邏輯

```typescript
SKILL_BUDGET_CONTEXT_PERCENT = 0.01  // context window 的 1%
CHARS_PER_TOKEN = 4
DEFAULT_CHAR_BUDGET = 8_000           // fallback: 200k × 4 × 0.01
MAX_LISTING_DESC_CHARS = 250          // 每條 skill 描述上限
```

budget 不足時：bundled skills 永不截斷，non-bundled skills 先截斷描述，極端情況只顯示名稱。

### 分析

| 設計特點 | 說明 |
|---|---|
| BLOCKING REQUIREMENT | 匹配到 skill 必須先呼叫工具，不得直接回應 |
| memoize by cwd | prompt 按 cwd 快取，避免重複計算 |
| 防重入 | 已執行中的 skill 不可再次呼叫 |
| bundled vs non-bundled | bundled skills 永遠保留完整描述 |

---

## 4. FileEditTool（Edit）

**檔案**：`src/tools/FileEditTool/prompt.ts`（28 行）

### Prompt 原文（`getEditToolDescription()`）

```
Performs exact string replacements in files.

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error
  if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it
  appears AFTER the line number prefix. The line number prefix format is: {line number + tab OR spaces +
  number + arrow}. Everything after that is the actual file content to match. Never include any part of
  the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more
  surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- [ant-only] Use the smallest old_string that's clearly unique — usually 2-4 adjacent lines is sufficient.
- Use `replace_all` for replacing and renaming strings across the file.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 強制先 Read | 防止盲目編輯 |
| 行號前綴處理 | 明確說明 Read 輸出格式（cat -n）及如何提取正確字串 |
| ant 特化提示 | ant 使用者收到「最小唯一字串」提示，節省 token |
| 唯一性守則 | old_string 重複則 FAIL，需加上下文或用 replace_all |

---

## 5. FileReadTool（Read）

**檔案**：`src/tools/FileReadTool/prompt.ts`（49 行）

### Prompt 原文（`renderPromptTemplate()`）

```
Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file
assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file {maxSizeInstruction}
- {offsetInstruction: "recommend reading whole file" OR "only read the part you need"}
- Results are returned using cat -n format, with line numbers starting at 1
- This tool allows Claude Code to read images (eg PNG, JPG, etc). When reading an image file the
  contents are presented visually as Claude Code is a multimodal LLM.
- [PDF support if isPDFSupported()]: For large PDFs (more than 10 pages), you MUST provide the pages
  parameter to read specific page ranges. Maximum 20 pages per request.
- This tool can read Jupyter notebooks (.ipynb files) and returns all cells with their outputs.
- This tool can only read files, not directories. To read a directory, use an ls command via the Bash tool.
- You will regularly be asked to read screenshots. If the user provides a path to a screenshot,
  ALWAYS use this tool to view the file at the path.
- If you read a file that exists but has empty contents you will receive a system reminder warning.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 兩種 offset 指令 | Default（建議讀完整）vs Targeted（只讀需要的部分）— 由 FileReadTool 決定傳哪個 |
| 多媒體支援 | 圖片視覺解析、PDF 分頁、Jupyter notebook 整合 |
| 截斷規則 | `MAX_LINES_TO_READ = 2000` |
| 快取優化 | 如內容未變則回傳 `FILE_UNCHANGED_STUB`，節省 context |

---

## 6. FileWriteTool（Write）

**檔案**：`src/tools/FileWriteTool/prompt.ts`（18 行）

### Prompt 原文（`getWriteToolDescription()`）

```
Writes a file to the local filesystem.

Usage:
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the Read tool first to read the file's contents.
  This tool will fail if you did not read the file first.
- Prefer the Edit tool for modifying existing files — it only sends the diff. Only use this tool to
  create new files or for complete rewrites.
- NEVER create documentation files (*.md) or README files unless explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.
```

### 分析

| 設計特點 | 說明 |
|---|---|
| Edit 優先原則 | Write 只用於新建或完全重寫，日常修改用 Edit |
| *.md 禁止 | 防止 AI 主動建立文件 |
| 強制先 Read | 同 Edit，覆蓋前需確認內容 |

---

## 7. GrepTool（Grep）

**檔案**：`src/tools/GrepTool/prompt.ts`（18 行）

### Prompt 原文（`getDescription()`）

```
A powerful search tool built on ripgrep

  Usage:
  - ALWAYS use Grep for search tasks. NEVER invoke `grep` or `rg` as a Bash command.
    The Grep tool has been optimized for correct permissions and access.
  - Supports full regex syntax (e.g., "log.*Error", "function\s+\w+")
  - Filter files with glob parameter (e.g., "*.js", "**/*.tsx") or type parameter (e.g., "js", "py", "rust")
  - Output modes: "content" shows matching lines, "files_with_matches" shows only file paths (default),
    "count" shows match counts
  - Use Agent tool for open-ended searches requiring multiple rounds
  - Pattern syntax: Uses ripgrep (not grep) - literal braces need escaping (use `interface\{\}` to find
    `interface{}` in Go code)
  - Multiline matching: By default patterns match within single lines only. For cross-line patterns like
    `struct \{[\s\S]*?field`, use `multiline: true`
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 工具排他性 | 明確禁止 bash grep/rg，強制用此工具 |
| ripgrep 語法警告 | `{}` 需轉義，與 grep 行為不同 |
| 多行模式說明 | 預設單行，需跨行用 `multiline: true` |

---

## 8. GlobTool（Glob）

**檔案**：`src/tools/GlobTool/prompt.ts`（7 行）

### Prompt 原文（`DESCRIPTION`）

```
- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping,
  use the Agent tool instead
```

### 分析

| 設計特點 | 說明 |
|---|---|
| 按修改時間排序 | 最新修改的檔案優先，符合常見使用情境 |
| Agent tool 升級路徑 | 明確指出複雜多輪搜尋的升級方案 |
| 極簡 prompt | 7 行，只有必要說明 |

---

## 核心工具設計對比

| 工具 | 防誤用設計 | 強制前置操作 | 優化路徑說明 |
|---|---|---|---|
| Bash | 禁止代替 File/Search 工具 | ls 驗證目錄 | `&&` 串行 vs 多 call 並行 |
| Agent | 禁止 File/Search 能解決的任務 | 無 | fork vs subagent 選擇 |
| Skill | 禁止在執行中的 skill 上重呼叫 | 無 | budget 截斷 + bundled 保護 |
| Edit | 禁止直接 Write 修改 | 必須先 Read | replace_all 重複字串 |
| Read | 禁止讀目錄 | 無 | 絕對路徑 + 分頁大型 PDF |
| Write | 禁止 *.md/README | 必須先 Read | Edit 優先 |
| Grep | 禁止 bash grep/rg | 無 | multiline 模式 |
| Glob | 開放式搜尋改用 Agent | 無 | 無 |
