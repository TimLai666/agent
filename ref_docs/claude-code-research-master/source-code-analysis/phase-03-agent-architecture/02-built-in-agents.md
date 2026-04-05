# 02 — Built-in Agents 完整分析

## 概覽

Claude Code 內建 6 個 built-in agent，定義於 `src/tools/AgentTool/built-in/`。每個 agent 透過 `BuiltInAgentDefinition` 介面聲明其類型、使用時機、工具權限與系統 prompt。

```typescript
// loadAgentsDir.ts 中的 BuiltInAgentDefinition 結構
type BuiltInAgentDefinition = {
  agentType: string        // 唯一識別 ID
  whenToUse: string        // 給 coordinator 看的使用說明
  tools?: string[]         // 白名單工具（'*' 表示全部）
  disallowedTools?: string[] // 黑名單工具
  source: 'built-in'
  baseDir: 'built-in'
  model?: string           // 'haiku'|'sonnet'|'inherit'|undefined（預設 subagent model）
  color?: string           // UI 顯示顏色
  background?: boolean     // 是否為背景 agent
  omitClaudeMd?: boolean   // 是否略過 CLAUDE.md 注入
  permissionMode?: string  // 'dontAsk' 等
  getSystemPrompt: (ctx?) => string
}
```

---

## 1. general-purpose（通用代理）

**檔案**：`generalPurposeAgent.ts`（34 行）

**agentType**：`general-purpose`

**whenToUse**：
> General-purpose agent for researching complex questions, searching for code, and executing multi-step tasks. When you are searching for a keyword or file and are not confident that you will find the right match in the first few tries use this agent to perform the search for you.

**工具權限**：`tools: ['*']`（所有工具）

**模型**：未指定（使用 `getDefaultSubagentModel()`）

**系統 Prompt 原文**：
```
You are an agent for Claude Code, Anthropic's official CLI for Claude. Given the user's message,
you should use the tools available to complete the task. Complete the task fully—don't gold-plate,
but don't leave it half-done. When you complete the task, respond with a concise report covering
what was done and any key findings — the caller will relay this to the user, so it only needs
the essentials.

Your strengths:
- Searching for code, configurations, and patterns across large codebases
- Analyzing multiple files to understand system architecture
- Investigating complex questions that require exploring many files
- Performing multi-step research tasks

Guidelines:
- For file searches: search broadly when you don't know where something lives. Use Read when you
  know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search strategies if the first doesn't
  yield results.
- Be thorough: Check multiple locations, consider different naming conventions, look for related files.
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing
  an existing file to creating a new one.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation
  files if explicitly requested.
```
（注：`enhanceSystemPromptWithEnvDetails()` 額外追加絕對路徑 + emoji 指導）

**能力分析**：
- 定位：最通用、工具最完整的 agent，作為兜底選項
- 強調「完整但不鍍金」（don't gold-plate, don't leave half-done）
- 明確禁止主動建立文件
- 輸出格式：簡潔報告給 caller 轉達

---

## 2. Explore（探索代理）

**檔案**：`exploreAgent.ts`（83 行）

**agentType**：`Explore`

**whenToUse**：
> Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?"). When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions.

**工具限制**（disallowedTools）：
- `AgentTool`（不能派生子 agent）
- `ExitPlanModeTool`
- `FileEditTool`
- `FileWriteTool`
- `NotebookEditTool`

**模型**：外部用戶 `haiku`（速度優先），Ant 內部 `inherit`（由 GrowthBook flag `tengu_explore_agent` 決定）

**特殊設定**：`omitClaudeMd: true`（跳過 CLAUDE.md 注入，減少 token）

**系統 Prompt 原文**（核心部分）：
```
You are a file search specialist for Claude Code, Anthropic's official CLI for Claude. You excel
at thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
...

NOTE: You are meant to be a fast agent that returns output as quickly as possible. In order to
achieve this you must:
- Make efficient use of the tools that you have at your disposal
- Wherever possible you should try to spawn multiple parallel tool calls for grepping and reading files
```

**最小查詢次數常量**：`EXPLORE_AGENT_MIN_QUERIES = 3`

**能力分析**：
- 定位：快速唯讀探索，速度優先
- 三段吞吐量模式：quick / medium / very thorough（由 caller 指定）
- 強制平行工具呼叫
- 不可遞迴派生子 agent（防止深度爆炸）

---

## 3. Plan（規劃代理）

**檔案**：`planAgent.ts`（92 行）

**agentType**：`Plan`

**whenToUse**：
> Software architect agent for designing implementation plans. Use this when you need to plan the implementation strategy for a task. Returns step-by-step plans, identifies critical files, and considers architectural trade-offs.

**工具限制**（disallowedTools）：同 Explore 的黑名單（AgentTool, ExitPlanMode, FileEdit, FileWrite, NotebookEdit）

**工具白名單**：繼承 `EXPLORE_AGENT.tools`（read-only 工具集）

**模型**：`inherit`（使用父 agent 的模型，保留高品質推理）

**特殊設定**：`omitClaudeMd: true`

**系統 Prompt 原文**（核心部分）：
```
You are a software architect and planning specialist for Claude Code. Your role is to explore the
codebase and design implementation plans.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
...

## Your Process
1. Understand Requirements
2. Explore Thoroughly: Read files, find patterns, understand architecture, trace code paths
3. Design Solution: Based on perspective, consider trade-offs
4. Detail the Plan: Step-by-step strategy, dependencies, challenges

## Required Output
End your response with:
### Critical Files for Implementation
List 3-5 files most critical for implementing this plan:
- path/to/file1.ts
...
```

**能力分析**：
- 定位：軟體架構師角色，探索→設計→輸出計劃
- 強制輸出「Critical Files」列表（供後續 implementer agent 精確定位）
- 唯讀：只探索不執行，保持計劃階段純粹性
- 繼承父模型：允許使用 Sonnet/Opus 進行深度架構分析

---

## 4. verification（驗證代理）

**檔案**：`verificationAgent.ts`（152 行）

**agentType**：`verification`

**whenToUse**：
> Use this agent to verify that implementation work is correct before reporting completion. Invoke after non-trivial tasks (3+ file edits, backend/API changes, infrastructure changes). Pass the ORIGINAL user task description, list of files changed, and approach taken. The agent runs builds, tests, linters, and checks to produce a PASS/FAIL/PARTIAL verdict with evidence.

**工具限制**（disallowedTools）：AgentTool, ExitPlanMode, FileEdit, FileWrite, NotebookEdit

**模型**：`inherit`

**特殊屬性**：
- `color: 'red'`（UI 紅色標識）
- `background: true`（預設背景執行）

**criticalSystemReminder_EXPERIMENTAL**：
```
CRITICAL: This is a VERIFICATION-ONLY task. You CANNOT edit, write, or create files IN THE PROJECT
DIRECTORY (tmp is allowed for ephemeral test scripts). You MUST end with VERDICT: PASS, VERDICT: FAIL,
or VERDICT: PARTIAL.
```

**系統 Prompt 核心設計**：

1. **兩大失敗模式警告**：
   - verification avoidance（找藉口不執行檢查，只讀程式碼）
   - 被前 80% 迷惑（看到漂亮 UI 就通過，沒測 edge case）

2. **按變更類型的驗證策略**：
   - Frontend、Backend/API、CLI、Infrastructure、Library、Bug fixes、Mobile、Database migrations 等各有具體策略

3. **強制輸出格式**：
```
### Check: [what you're verifying]
**Command run:** [exact command]
**Output observed:** [actual terminal output]
**Result: PASS** (or FAIL)
```

4. **最終判決格式**（機器可解析）：
   - `VERDICT: PASS`
   - `VERDICT: FAIL`
   - `VERDICT: PARTIAL`

**能力分析**：
- 定位：對抗性驗證者，設計上鼓勵挑剔而非橡皮圖章
- 明確列出「rationalization 清單」讓 agent 識別並抗拒自身懶惰
- 必須有命令輸出為證，純讀程式碼不算通過
- caller 可 re-run 命令驗證報告真實性

---

## 5. claude-code-guide（文件查詢代理）

**檔案**：`claudeCodeGuideAgent.ts`（205 行）

**agentType**：`claude-code-guide`

**whenToUse**：
> Use this agent when the user asks questions ("Can Claude...", "Does Claude...", "How do I...") about: (1) Claude Code CLI, (2) Claude Agent SDK, (3) Claude API. IMPORTANT: Before spawning a new agent, check if there is already a running or recently completed claude-code-guide agent that you can continue via SendMessage.

**工具集**：
- 標準環境：`Glob, Grep, Read, WebFetch, WebSearch`
- Ant 內部環境：`Bash, Read, WebFetch, WebSearch`

**模型**：`haiku`（快速查詢）

**特殊設定**：`permissionMode: 'dontAsk'`（不詢問權限）

**系統 Prompt 三大知識域**：
1. **Claude Code（CLI）**：文件來源 `https://code.claude.com/docs/en/claude_code_docs_map.md`
2. **Claude Agent SDK**：文件來源 `https://platform.claude.com/llms.txt`
3. **Claude API**：文件來源同上（SDK 和 API 共用）

**動態注入的 Context**（`getSystemPrompt({ toolUseContext })`）：
- 使用者的自訂 skills（`commands.filter(cmd => cmd.type === 'prompt')`）
- 自訂 agents（`.claude/agents/` 中非 built-in 的）
- MCP servers 列表
- Plugin commands
- User settings.json

**能力分析**：
- 定位：Claude 生態文件查詢專家，三域知識
- 動態感知使用者的實際配置（skills/agents/MCP），回答更具針對性
- 建議重用已有的 agent 實例（SendMessage 繼續）而非重新 spawn

---

## 6. statusline-setup（狀態列設定代理）

**檔案**：`statuslineSetup.ts`（144 行）

**agentType**：`statusline-setup`

**whenToUse**：
> Use this agent to configure the user's Claude Code status line setting.

**工具集**：`['Read', 'Edit']`（最小工具集）

**模型**：`sonnet`

**特殊屬性**：`color: 'orange'`

**系統 Prompt 功能**：
1. 讀取 shell 設定（`~/.zshrc` → `~/.bashrc` → `~/.bash_profile` → `~/.profile`）
2. 用正則抽取 PS1：`/(?:^|\n)\s*(?:export\s+)?PS1\s*=\s*["']([^"']+)["']/m`
3. 轉換 PS1 跳脫序列（`\u` → `$(whoami)` 等 11 種）
4. JSON stdin 結構說明（statusLine 可接收的欄位：session_id, cwd, model, context_window, rate_limits, vim, agent, worktree 等）
5. 寫入 `~/.claude/settings.json`

**能力分析**：
- 定位：高度特化的設定輔助工具
- 只讀寫 settings 相關文件，工具集最小化
- 使用 Sonnet（需要理解 bash/zsh 語法轉換邏輯）

---

## 工具限制對比表

| Agent | 可用工具 | 禁止工具 | 模型 |
|-------|----------|----------|------|
| general-purpose | 全部 (`*`) | 無 | 預設 subagent |
| Explore | 唯讀工具 | AgentTool, Edit, Write, etc. | haiku |
| Plan | 唯讀工具（繼承 Explore） | AgentTool, Edit, Write, etc. | inherit |
| verification | 多數工具 | AgentTool, Edit, Write | inherit |
| claude-code-guide | Glob/Grep/Read/WebFetch/WebSearch | 無指定 | haiku |
| statusline-setup | Read, Edit | 無指定 | sonnet |
