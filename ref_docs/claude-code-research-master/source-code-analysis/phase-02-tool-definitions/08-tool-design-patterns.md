# 08 — Tool Prompt 設計模式

> 從 36 個工具 prompt 中提煉的設計原則與模式

---

## 模式 1：工具偏好金字塔（Tool Preference Hierarchy）

**定義：** 在工具 prompt 中明確聲明「何時用其他工具替代我」，建立明確的使用優先級。

**典型範例（BashTool）：**
```
IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`, `tail`, `sed`, `awk`, or
`echo` commands... Instead, use the appropriate dedicated tool:
- File search: Use Glob (NOT find or ls)
- Content search: Use Grep (NOT grep or rg)
- Read files: Use Read (NOT cat/head/tail)
```

**也用於：**
- PowerShellTool → 禁止用 PS 做 File/Search
- GrepTool → "ALWAYS use Grep... NEVER invoke `grep` or `rg` as a Bash command"
- WebFetchTool → "If MCP-provided web fetch is available, prefer using that tool"
- GlobTool → "open ended search... use the Agent tool instead"

**設計目的：**
1. 防止濫用強力工具替代專用工具
2. 引導 model 選擇最小權限、最透明的方案
3. 保護 UX（專用工具讓使用者有更好的 review 體驗）

---

## 模式 2：強制前置操作（Mandatory Pre-operation）

**定義：** 某些工具要求在本對話中必須先執行前置操作才能呼叫。

**典型範例：**

| 工具 | 強制前置 | 違反後果 |
|---|---|---|
| FileEditTool | 必須先 Read | 工具回傳 error |
| FileWriteTool（現有檔案）| 必須先 Read | 工具回傳 error |
| TaskUpdateTool | 建議先 TaskGet | staleness 風險 |
| TaskGetTool | 無，但建議先 TaskList | 重複創建任務 |

**實作特點：**
- FileEditTool/FileWriteTool 在執行層有實際驗證（不只是建議）
- TaskUpdate 只有「建議」因為多 agent 環境下強制驗證代價過高
- 防誤用設計防止「盲目修改」

---

## 模式 3：明確的觸發/不觸發規則（Binary Trigger Rules）

**定義：** 用 "When to Use" + "When NOT to Use" 的二元結構，而非模糊的「根據情況判斷」。

**典型範例（EnterPlanModeTool）：**
```
## When to Use This Tool (ANY of these applies)
1. New Feature Implementation
2. Multiple Valid Approaches
3. Code Modifications
...

## When NOT to Use This Tool
- Single-line or few-line fixes
- Tasks where the user has given very specific, detailed instructions
```

**也用於：**
- EnterWorktreeTool（"ONLY when the user explicitly says 'worktree'"）
- AgentTool（whenNotToUse：File/Search 任務）
- TodoWriteTool（2個 When + 範例對比）
- ExitPlanModeTool（ONLY for code planning, NOT for research）

**設計目的：**
1. 減少 ambiguity，提高一致性
2. 防止工具被過度/過少使用
3. ant vs 外部版本可調整閾值（EnterPlanMode）

---

## 模式 4：使用者角色分支（User Persona Branching）

**定義：** 根據 `USER_TYPE === 'ant'` 或 feature flag 提供不同版本的 prompt。

**典型範例：**

| 工具 | ant 版 | 外部版 |
|---|---|---|
| BashTool | 指向 `/commit` skill | 完整 inline Git 說明 |
| EnterPlanMode | 閾值更嚴格（genuinely unclear）| 更低閾值（非簡單任務即用）|
| FileEditTool | 額外「最小 old_string」提示 | 無 |
| AgentTool | 允許 nested agents | 禁用 AgentTool 遞迴 |

**設計目的：**
1. ant 使用者（Anthropic 員工）有更多背景知識，不需要詳細說明
2. 外部使用者需要更完整的指引
3. 分支讓 prompt 在不同受眾都是最優版本

---

## 模式 5：Feature Flag 動態開關（Feature-gated Sections）

**定義：** 用 `feature('FLAG_NAME')` 或 `getFeatureValue_CACHED_*()` 控制 prompt 段落出現與否。

**典型範例：**

| Feature Flag | 影響工具/段落 |
|---|---|
| `FORK_SUBAGENT` | AgentTool → fork 語義 + "When to fork" section |
| `AGENT_TRIGGERS` | ScheduleCronTool 整個工具啟用 |
| `KAIROS` / `KAIROS_BRIEF` | BriefTool 不 defer |
| `UDS_INBOX` | SendMessageTool → cross-session 段落 |
| `MONITOR_TOOL` | BashTool → Monitor tool 替代 sleep |
| `TRANSCRIPT_CLASSIFIER` | 執行層 PermissionDenied hook 路徑 |
| `VOICE_MODE` + GrowthBook | ConfigTool → voiceEnabled 設定顯示 |

**設計目的：**
1. Dead code elimination（bun:bundle 靜態分析）
2. GrowthBook runtime kill switch（可即時關閉 fleet 上的功能）
3. A/B testing（例如 agent list 的 attachment vs inline）

---

## 模式 6：狀態機說明（State Machine Documentation）

**定義：** 在 prompt 中明確說明狀態轉移規則，包含非法狀態的處理。

**典型範例（TaskUpdateTool）：**
```
## Status Workflow
Status progresses: `pending` → `in_progress` → `completed`

ONLY mark a task as completed when you have FULLY accomplished it.
If you encounter errors, keep the task as in_progress.
Never mark a task as completed if:
  - Tests are failing
  - Implementation is partial
  - You encountered unresolved errors
```

**也用於：**
- TodoWriteTool（相同狀態機，含 activeForm/content 雙形態）
- TeamCreate → TeamDelete（team 生命週期）
- EnterWorktree → ExitWorktree（worktree session 生命週期）

**設計目的：**
1. 強制執行任務狀態的完整性（tests passing 才算 completed）
2. 防止假完成（partial implementation marked as done）
3. 文件即守則

---

## 模式 7：安全層級聲明（Safety Level Declaration）

**定義：** 明確列出哪些操作是安全的（可自動執行），哪些需要使用者確認或被禁止。

**典型範例（BashTool Git Safety Protocol）：**
```
Git Safety Protocol:
- NEVER update the git config
- NEVER run destructive git commands (...) unless the user explicitly requests
- NEVER skip hooks
- CRITICAL: Always create NEW commits rather than amending
```

**BashTool 沙箱：**
```
Evidence of sandbox-caused failures includes:
- "Operation not permitted" errors for file/network operations
- Access denied to specific paths

When you see evidence of sandbox-caused failure:
  Immediately retry with `dangerouslyDisableSandbox: true` (don't ask, just do it)
```

**EnterPlanMode：**
```
This tool REQUIRES user approval — they must consent to entering plan mode.
```

**設計目的：**
1. 不同等級的保護：automatic / ask / never
2. 「defence-in-depth」：多層保護（prompt level + execution level）
3. 明確的操作邊界讓 model 不必猜測

---

## 模式 8：並行操作指引（Parallelism Guidance）

**定義：** 明確告知哪些操作可以並行，以及如何正確並行。

**典型範例（BashTool）：**
```
When issuing multiple commands:
- If the commands are independent and can run in parallel, make multiple Bash tool calls in a
  single message.
- If the commands depend on each other, use a single Bash call with '&&'.
- Use ';' only when you need to run commands sequentially but don't care if earlier commands fail.
- DO NOT use newlines to separate commands.
```

**AgentTool：**
```
- Launch multiple agents concurrently whenever possible
- If the user specifies "in parallel", you MUST send a single message with multiple Agent tool use
  content blocks.
```

**BashTool git commit 流程：**
```
1. Run the following bash commands in parallel: [git status, git diff, git log]
3. Run the following commands in parallel: [git add, git commit, git status after]
```

**設計目的：**
1. 主動引導 model 做並行最佳化
2. 區分 `&&`（依賴）vs 多 tool call（獨立）vs `;`（忽略錯誤）
3. 顯式說明「不要用換行分隔」防止常見錯誤

---

## 模式 9：反模式列舉（Anti-pattern Enumeration）

**定義：** 明確列出「不要這樣做」，往往比「要這樣做」更有效。

**典型範例集合：**

**AgentTool（fork mode）：**
```
Don't peek. [...] do not Read or tail it unless the user explicitly asks.
Don't race. Never fabricate or predict fork results in any format — not as prose, summary, or
structured output.
```

**SendMessageTool：**
```
Do NOT send structured JSON status messages like `{"type":"idle",...}` or
`{"type":"task_completed",...}`. Just communicate in plain text.
```

**BashTool sleep：**
```
Do not sleep between commands that can run immediately.
Do not retry failing commands in a sleep loop — diagnose the root cause.
```

**TodoWriteTool：**
```
NOTE: do not use this tool if there is only one trivial task to do. In this case you are better
off just doing the task directly.
```

**EnterWorktreeTool：**
```
When NOT to Use:
- The user asks to create a branch, switch branches — use git commands instead
- Never use this tool unless the user explicitly mentions "worktree"
```

**設計目的：**
1. 消除模型傾向於觸及「感覺相關但錯誤」的工具
2. 打破訓練資料偏見（例如模型傾向用 sleep polling）
3. 節省 token（反模式說明往往比正面說明更有效）

---

## 模式 10：預算感知設計（Budget-aware Design）

**定義：** prompt 設計時考慮 token 消耗，主動做截斷和快取最佳化。

**典型範例：**

**SkillTool listing budget：**
```typescript
// 只用 context window 的 1%
SKILL_BUDGET_CONTEXT_PERCENT = 0.01
// 按優先序截斷：bundled > 有描述 > 名稱-only
```

**AgentTool agent list cache：**
```typescript
// agent list 可切換為 attachment，避免 MCP reload 造成 cache bust
// ~10.2% of fleet cache_creation tokens
shouldInjectAgentListInMessages() → 切換 attachment 模式
```

**BashTool sandbox prompt：**
```typescript
// 正規化 temp dir 路徑（$TMPDIR 替代實際路徑）
// 避免 per-uid 路徑不同造成跨用戶 cache miss
const normalizeAllowOnly = (paths) =>
  paths.map(p => (p === claudeTempDir ? '$TMPDIR' : p))
```

**BashTool sandbox dedup：**
```typescript
// SandboxManager 可能有重複路徑，dedup 後嵌入 prompt
// 節省 ~150-200 tokens/request
function dedup<T>(arr: T[]): T[] { return [...new Set(arr)] }
```

**FileReadTool unchanged stub：**
```typescript
// 同一對話中再次讀取相同未修改的檔案
FILE_UNCHANGED_STUB = "File unchanged since last read. Refer to earlier Read tool_result."
// 節省大量 context
```

**設計目的：**
1. 控制 prompt 大小，維持快取效率
2. 防止 cache bust（deterministic prompt 才能 hit cache）
3. 大型 fleet 的 token 節省直接影響成本

---

## 模式 11：版本感知指引（Version-aware Guidance）

**定義：** 在執行時偵測環境版本，動態生成對應的語法指引。

**唯一範例：PowerShellTool（`getEditionSection()`）：**

```typescript
// 執行時偵測 PS 版本
const edition = await getPowerShellEdition()

// 生成對應 prompt 段落
if (edition === 'desktop') {
  // PS 5.1 限制：不可用 &&, ||, ternary, null-coalescing
  // 2>&1 的 stderr 處理差異
  // 預設 UTF-16 LE encoding
} else if (edition === 'core') {
  // PS 7+ 支援：&& || ternary ?? ?.
  // 預設 UTF-8
} else {
  // 未知版本 → 保守模式（假設 5.1）
}
```

**設計目的：**
1. 防止模型生成在目標版本上語法錯誤的命令
2. 保守預設（未知 → 較嚴格限制）
3. 版本資訊一次偵測，prompt 生成時注入

---

## 模式 12：通訊可見性契約（Communication Visibility Contract）

**定義：** 明確聲明哪些輸出對哪些對象可見，強制使用正確的通訊管道。

**典型範例（BriefTool / SendUserMessage）：**
```
SendUserMessage is where your replies go. Text outside it is visible in the detail view, but
most won't open it — the answer lives here.

The failure mode: the real answer lives in plain text while SendUserMessage just says "done!"
— they see "done!" and miss everything.
```

**SendMessageTool：**
```
Your plain text output is NOT visible to other agents — to communicate, you MUST call this tool.
```

**AgentTool（fork）：**
```
When the agent is done, it will return a single message back to you. The result returned by the
agent is not visible to the user. To show the user the result, you should send a text message.
```

**TeamCreate：**
```
Your team cannot hear you if you do not use the SendMessage tool.
```

**設計目的：**
1. 消除「文字輸出 = 通訊」的假設
2. 強制顯式通訊，確保訊息不被遺漏
3. 解釋 "why" 而非只說 "what"（防止 detail view 陷阱）

---

## 設計模式統計

| 模式 | 使用工具數 | 重要性 |
|---|---|---|
| 工具偏好金字塔 | 7+ | 防止工具濫用 |
| 強制前置操作 | 4 | 資料完整性 |
| 明確觸發規則 | 8+ | 降低歧義 |
| 使用者角色分支 | 5+ | 分眾最佳化 |
| Feature Flag 開關 | 10+ | 靈活部署 |
| 狀態機說明 | 5 | 業務邏輯守則 |
| 安全層級聲明 | 4 | 防止破壞性操作 |
| 並行操作指引 | 4 | 效能最佳化 |
| 反模式列舉 | 10+ | 消除常見錯誤 |
| 預算感知設計 | 6 | Token/快取效率 |
| 版本感知指引 | 1 | 環境相容性 |
| 通訊可見性契約 | 5 | 確保訊息到達 |

---

## 綜合設計原則

從 36 個工具 prompt 的整體分析，歸納出以下設計哲學：

### 1. 最小驚喜原則（Principle of Least Surprise）
每個工具都明確聲明自己的邊界，讓模型不需猜測「我能用這個工具做什麼」。

### 2. 防禦性深度（Defence in Depth）
重要的安全約束在 prompt 層 + execution 層雙重實施（例如 FileEdit 的 Read 前置要求）。

### 3. 解釋 Why，不只是 What
好的限制說明是「不要 `git add -A`，因為可能包含 .env 等敏感檔案」，而不只是「不要 `git add -A`」。

### 4. 靜態結構 + 動態內容分離
工具的核心邏輯靜態化（有利於 cache），動態資訊（沙箱規則、可用 agents、cron 設定）注入時機明確控制。

### 5. 分眾差異化
同一工具對 ant/外部使用者、不同 feature flag 狀態、不同 PS 版本提供最適合的說明，而非一刀切。
