# Phase 6 — 03 Bash 權限判斷模型

## 主入口：bashToolHasPermission()

```typescript
export async function bashToolHasPermission(
  input: z.infer<typeof BashTool.inputSchema>,
  context: ToolUseContext,
  getCommandSubcommandPrefixFn = getCommandSubcommandPrefix,
): Promise<PermissionResult>
```

### 完整決策流程（14 個步驟）

```
Step 0: AST Parse (tree-sitter)
  ├── too-complex → checkEarlyExitDeny → ask（附 pendingClassifierCheck）
  ├── simple → checkSemantics → fail → checkSemanticsDeny → ask
  │                           → ok → astSubcommands 已知，繼續
  └── parse-unavailable → 進入 legacy shell-quote 路徑

Step 1: Sandbox Auto-Allow（僅當 sandbox + autoAllowBashIfSandboxed 啟用）
  ├── 有 deny rule → deny
  ├── 複合命令逐一檢查 subcommand deny rules → deny 優先
  └── 無 deny rule → allow

Step 2: Exact Match Rule Check（精確匹配）
  ├── deny rule → deny
  ├── ask rule → ask
  ├── allow rule → 暫存（等 path constraints 通過後才回傳）
  └── passthrough → 繼續

Step 3: Classifier Rules（deny + ask，Haiku 模型平行執行）
  ├── deny high confidence → deny
  └── ask high confidence → ask（附 pendingClassifierCheck）

Step 4: Command Operator Permissions（|, &, &&, ||, ;, > 等）
  ├── allow → 再做 bashCommandIsSafe + checkPathConstraints
  └── ask/deny → 回傳（attach pendingClassifierCheck if ask）

Step 5: Legacy Misparsing Gate（僅 tree-sitter 不可用時）
  ├── originalCommand 有 misparsing 旗標 → ask（或 strip heredocs 再檢查）
  └── 通過 → 繼續

Step 6: Subcommand Fanout（子命令拆分，最多 MAX_SUBCOMMANDS_FOR_SECURITY_CHECK=50）
  ├── 超過 50 個 → ask
  ├── 多個 cd → ask
  └── 逐一處理每個 subcommand → checkCommandAndSuggestRules

Step 7: 每個 subcommand 的 checkCommandAndSuggestRules
  ├── 7a. Exact match rule
  ├── 7b. Prefix/wildcard rule（deny/ask/allow）
  ├── 7c. bashCommandIsSafe（注入檢查，AST 成功則跳過）
  ├── 7d. checkPathConstraints（路徑邊界）
  ├── 7e. checkSedConstraints（sed 安全驗證）
  ├── 7f. checkPermissionMode（模式檢查）
  ├── 7g. isReadOnly → allow
  └── passthrough → 權限提示
```

## 規則系統

### 規則類型

```typescript
type ShellPermissionRule =
  | { type: 'exact';    command: string }     // 精確匹配
  | { type: 'prefix';   prefix: string }      // 前綴匹配 (cmd:*)
  | { type: 'wildcard'; pattern: string }     // 通配符匹配
```

### 安全 Env Var 列表（允許規則剝除）

```typescript
const SAFE_ENV_VARS = new Set([
  // Go: GOEXPERIMENT, GOOS, GOARCH, CGO_ENABLED, GO111MODULE
  // Rust: RUST_BACKTRACE, RUST_LOG
  // Node: NODE_ENV (不含 NODE_OPTIONS!)
  // Python: PYTHONUNBUFFERED, PYTHONDONTWRITEBYTECODE (不含 PYTHONPATH!)
  // Pytest: PYTEST_DISABLE_PLUGIN_AUTOLOAD, PYTEST_DEBUG
  // API: ANTHROPIC_API_KEY
  // Locale: LANG, LANGUAGE, LC_ALL, LC_CTYPE, LC_TIME, CHARSET
  // Terminal: TERM, COLORTERM, NO_COLOR, FORCE_COLOR, TZ
  // Colors: LS_COLORS, LSCOLORS, GREP_COLOR, GREP_COLORS, GCC_COLORS
  // Format: TIME_STYLE, BLOCK_SIZE, BLOCKSIZE
])
```

**嚴格禁止加入**：`PATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_*`, `PYTHONPATH`, `NODE_PATH`, `GOFLAGS`, `RUSTFLAGS`, `NODE_OPTIONS`, `HOME`, `TMPDIR`, `SHELL`, `BASH_ENV`

### Deny 規則剝除（更激進）

Deny 規則使用 `stripAllLeadingEnvVars()` 剝除**所有** env var（而非只剝除安全列表）：

```typescript
// 攻擊防範：FOO=bar denied_command 不應繞過 Bash(denied_command:*) 的 deny 規則
filterRulesByContentsMatchingInput(input, denyRules, matchMode, {
  stripAllEnvVars: true,  // deny/ask 規則
  skipCompoundCheck: true,
})
```

### Safe Wrapper 剝除（SAFE_WRAPPER_PATTERNS）

以下 wrapper 命令的剝除允許規則匹配：
- `timeout [flags] <duration> <cmd>` — 完整 GNU flag 解析
- `time [--] <cmd>`
- `nice [-n N | -N] [--] <cmd>`
- `stdbuf [-oNL | -eLN | ...] [--] <cmd>`
- `nohup [--] <cmd>`

**注意**：wrapper 剝除後不繼續剝除 env var（HackerOne #3543050 修復）

**BARE_SHELL_PREFIXES（不產生前綴建議）：**
`sh`, `bash`, `zsh`, `fish`, `csh`, `tcsh`, `ksh`, `dash`, `cmd`, `powershell`, `pwsh`, `env`, `xargs`, `nice`, `stdbuf`, `nohup`, `timeout`, `time`, `sudo`, `doas`, `pkexec`

## 複合命令保護

```typescript
// 前綴/通配符規則不匹配複合命令
// Bash(cd:*) 不能匹配 "cd /path && python3 evil.py"
if (isCompoundCommand.get(cmdToMatch)) {
  return false  // 在 filterRulesByContentsMatchingInput 中
}
```

例外：deny/ask 規則設 `skipCompoundCheck: true`，確保 `Bash(rm:*)` deny 仍可封鎖複合命令中的 rm。

## isNormalizedGitCommand 特殊處理

```typescript
export function isNormalizedGitCommand(command: string): boolean
```

Git 命令有特殊的 `cd + git` bare repo 保護：
- 裸 repo（pure `.git` 目錄）中的 git 操作可能觸發 `core.fsmonitor` RCE
- 偵測到 `cd X && git Y` 且 X 是裸 repo → ask

## Classifier 整合

### 允許 Classifier（BASH_CLASSIFIER feature flag）

```typescript
// 非同步後台執行，與使用者互動賽跑
export async function executeAsyncClassifierCheck(
  pendingCheck: { command: string; cwd: string; descriptions: string[] },
  signal: AbortSignal,
  isNonInteractiveSession: boolean,
  callbacks: AsyncClassifierCheckCallbacks,
): Promise<void>
```

- `classifyBashCommand()` 呼叫 Haiku 模型
- `confidence === 'high'` 且 `matches: true` → auto-approve
- 需要 `allowDescriptions.length > 0`（使用者設定的自然語言 allow 規則）

### Speculative Check（投機預取）

```typescript
// 在 pre-tool hooks 和 deny/ask classifier 並行執行期間，
// 提前啟動 allow classifier，減少總等待時間
export function startSpeculativeClassifierCheck(command, context, signal, isNonInteractive): boolean
export function peekSpeculativeClassifierCheck(command): Promise<ClassifierResult> | undefined
export function consumeSpeculativeClassifierCheck(command): Promise<ClassifierResult> | undefined
```

## 規則建議生成

### getSimpleCommandPrefix
- 提取 `command subcommand` 前綴（e.g., `git commit`）
- 必須：第二 token 是小寫字母開頭（排除旗標、路徑、URL）
- 跳過安全 env var 前綴

### suggestionForExactCommand
優先順序：
1. Heredoc 命令 → `extractPrefixBeforeHeredoc()` → 前綴規則
2. 多行命令（含 `\n`）→ 第一行 → 前綴規則
3. 單行命令 → `getSimpleCommandPrefix()` → 前綴規則
4. Fallback → 精確匹配規則

## 常數

```typescript
export const MAX_SUBCOMMANDS_FOR_SECURITY_CHECK = 50  // 子命令上限
export const MAX_SUGGESTED_RULES_FOR_COMPOUND = 5     // 複合命令規則建議上限
```
